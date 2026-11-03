"""Connect project snapshots to the existing OpenCivil save and viewport flow."""

import contextlib
import hashlib
import io
import json
import os
import shutil
import tempfile

from PyQt6.QtWidgets import QMessageBox

from core.model_history import HistoryStore

_VIEW_KEYS = (
    "view_extruded", "show_slabs", "show_joints", "show_supports", "show_loads",
    "show_local_axes", "show_constraints", "show_releases", "load_type_filter",
    "visible_load_patterns", "show_grid", "show_ghost_structure", "show_hinges",
    "tributary_loads", "tributary_heatmap", "tributary_mesh",
)
_APP_KEYS = (
    "msaa_level", "background_color", "edge_color", "shell_edge_color", "ui_theme",
    "extrude_opacity", "glass_strength", "glass_transparency", "fxaa_strength",
)

def _path_key(path):
    return os.path.normcase(os.path.abspath(os.fspath(path))) if path else None

def _fingerprint(data):
    payload = json.dumps(data, sort_keys=True, separators=(",", ":"),
                         ensure_ascii=True, allow_nan=False).encode("ascii")
    return hashlib.sha256(payload).hexdigest()

class ModelHistoryController:
    def __init__(self, window, model_factory=None):
        self.window = window
        self.model_factory = model_factory
        self.model_path = None
        self.tracked_model = None
        self.store = None
        self.baseline = None
        self._restoring = False
        self._problem = None

    def reset(self):
        self.model_path = None
        self.tracked_model = None
        self.store = None
        self.baseline = None
        self._problem = None

    def _status(self, message):
        self.window.status.showMessage(message, 8000)

    def _unavailable(self, error, saved=False):
        self._problem = str(error)
        prefix = "Model saved, but history could not be recorded" if saved else "History unavailable"
        self._status(f"{prefix}: {error}")
        print(f"{prefix}: {error}")

    def before_save(self, filepath):
        """Preserve the existing disk version before a successful save replaces it."""
        try:
            destination = HistoryStore(filepath)
            if (self.tracked_model is self.window.model and self.store and self.store.exists and not destination.exists
                    and _path_key(filepath) != _path_key(self.model_path)):
                self.store.copy_to(filepath)
            if os.path.isfile(filepath):
                destination.record_file("Existing saved model")
            self._problem = None
        except Exception as error:
            self._unavailable(error)

    def note_saved(self, filepath, label="Saved model"):
        try:
            self.model_path = os.path.abspath(filepath)
            self.tracked_model = self.window.model
            self.store = HistoryStore(self.model_path)
            commit = self.store.record_file(label)
            self.baseline = self._live_fingerprint()
            self._problem = None
            if commit.get("auto_branch"):
                self._status(f"Saved on new branch: {self.store.state()['active_branch']}")
        except Exception as error:
            self._unavailable(error, saved=True)

    def note_opened(self, filepath):
        if self._restoring:
            return
        try:
            self.model_path = os.path.abspath(filepath)
            self.tracked_model = self.window.model
            self.store = HistoryStore(self.model_path)
            self.store.record_file("Existing saved model")
                                                                                   
            self.baseline = self._live_fingerprint()
            self._problem = None
        except Exception as error:
            self._unavailable(error)

    def _live_fingerprint(self):
        model = self.window.model
        previous_graphics = model.graphics_settings
        settings = self.window.graphics_settings.copy()
        canvas = getattr(self.window, "canvas", None)
        if canvas is not None:
            for key in _VIEW_KEYS:
                if hasattr(canvas, key):
                    settings[key] = getattr(canvas, key)
            if getattr(canvas, "reaction_diagram_active", False):
                settings["show_grid"] = getattr(canvas, "_pre_reaction_was_grid", canvas.show_grid)
            elif getattr(canvas, "_pre_force_was_grid", False):
                settings["show_grid"] = True
        for key in tuple(settings):
            if key in ("glass_strength", "glass_transparency", "msaa_level", "fxaa_strength") or key.startswith("crosshair_"):
                settings.pop(key, None)
        descriptor, path = tempfile.mkstemp(suffix=".mf")
        os.close(descriptor)
        try:
            model.graphics_settings = settings
            with contextlib.redirect_stdout(io.StringIO()):
                model.save_to_file(path)
            with open(path, "r") as stream:
                return _fingerprint(json.load(stream))
        finally:
            model.graphics_settings = previous_graphics
            if os.path.exists(path):
                os.remove(path)

    def has_unsaved_changes(self):
        if not self.window.undo_stack.isClean():
            return True
        if self.baseline is None:
                                                                                
            return True
        try:
            return self._live_fingerprint() != self.baseline
        except Exception:
            return True

    def _busy(self):
        for name in ("worker", "_buckling_thread"):
            worker = getattr(self.window, name, None)
            if worker is not None and worker.isRunning():
                return True
        generator = getattr(self.window, "_tributary_generator", None)
        return generator is not None and generator.is_busy()

    def show_dialog(self):
        if self.window.model is None:
            self._status("Open or create a model to use its history.")
            return
        filepath = getattr(self.window.model, "file_path", None)
        if not filepath:
            if not self.window.on_save_model():
                return
            filepath = self.window.model.file_path
        if self._busy():
            QMessageBox.information(self.window, "Model history", "Finish or stop the analysis before opening model history.")
            return
        if _path_key(self.model_path) != _path_key(filepath):
            self.note_opened(filepath)
        try:
            if self._problem:
                raise RuntimeError(self._problem)
            from app.dialogs.model_history_dialog import ModelHistoryDialog
            dialog = ModelHistoryDialog(self.store, self.open_commit, parent=self.window)
            dialog.exec()
        except Exception as error:
            QMessageBox.warning(self.window, "Model history", str(error))

    def _load_candidate(self, path):
        if self.model_factory is None:
            from core.model import StructuralModel
            model = StructuralModel("History snapshot")
        else:
            model = self.model_factory()
                                                                                
        for name in ("load_cases", "mass_sources"):
            collection = getattr(model, name, None)
            if collection is not None:
                collection.clear()
        model.load_from_file(path)
        return model

    def _adopt_model(self, candidate, filepath):
        window = self.window
        old_model = window.model
        window._purge_results_and_visuals()
        window.model = candidate
        candidate.file_path = filepath
        candidate.active_model_path = filepath
        candidate.active_project_dir = os.path.dirname(filepath)
        candidate.results = {}
        candidate.has_results = False
        window._solver_mesh_ctx = None
        window.solver_input_path = None
        window.solver_output_path = None
        window.terminal_panel.set_model(candidate)
        for name in ("selected_ids", "selected_node_ids", "selected_area_ids", "selected_link_ids", "selected_tendon_ids", "selected_cable_ids"):
            setattr(window, name, [])

        graphics = window.graphics_settings
        preserved = {key: value for key, value in graphics.items()
                     if key in _APP_KEYS or key.startswith("crosshair_")}
        for key in _VIEW_KEYS:
            graphics.pop(key, None)
        graphics.update(candidate.graphics_settings or {})
        graphics.update(preserved)
        window._apply_canvas_view_settings(graphics)
        window.update_graphics_settings(graphics)
        if hasattr(candidate, "saved_unit_system"):
            window.combo_units.blockSignals(True)
            try:
                window.combo_units.setCurrentText(candidate.saved_unit_system)
            finally:
                window.combo_units.blockSignals(False)
            window.on_units_changed(0, redraw=False)
        window.draw_both_canvases()
        window.update_yield_lines()
        window.canvas.set_standard_view("3D")
        window.set_interface_state(True)
        window.model_tree.refresh()
        window.update_window_title()

    def _finish_checkout(self, old_model):
        """Discard undo/dialog references only after the checkout has committed."""
        from PyQt6.QtWidgets import QDialog
        window = self.window
        window.undo_stack.blockSignals(True)
        try:
            window.undo_stack.clear()
            window.undo_stack.setClean()
        finally:
            window.undo_stack.blockSignals(False)
        for name, value in list(vars(window).items()):
            if isinstance(value, QDialog) and getattr(value, "model", None) is old_model:
                setattr(window, name, None)
                try:
                    value.close()
                    value.deleteLater()
                except RuntimeError:
                    pass                                                
        window.update_window_title()

    def open_commit(self, commit_id, branch_name=None):
        if self._busy():
            QMessageBox.information(self.window, "Model history", "Finish or stop the analysis before switching saved points.")
            return False
        filepath = self.model_path
        if _path_key(getattr(self.window.model, "file_path", None)) != _path_key(filepath):
            QMessageBox.warning(self.window, "Model history", "The active project changed. Reopen its history.")
            return False
        if self.has_unsaved_changes():
            reply = QMessageBox.question(
                self.window, "Unsaved changes", "Save your current changes before opening this saved point?",
                QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Save,
            )
            if reply == QMessageBox.StandardButton.Cancel:
                return False
            if reply == QMessageBox.StandardButton.Save and not self.window.on_save_model():
                return False
            if _path_key(self.window.model.file_path) != _path_key(filepath):
                return False

        old_model = self.window.model
        old_results = getattr(old_model, "results", {})
        old_has_results = getattr(old_model, "has_results", False)
        old_graphics = self.window.graphics_settings.copy()
        old_baseline = self.baseline
        old_selections = {name: list(getattr(self.window, name, [])) for name in (
            "selected_ids", "selected_node_ids", "selected_area_ids", "selected_link_ids", "selected_tendon_ids", "selected_cable_ids")}
        original_path = staged_path = None
        replaced = adopted = False
        try:
                                                                                
            payload = self.store.snapshot_bytes(commit_id)
            original_state = self.store.state()
            branches = original_state["branches"]
            if branch_name is not None:
                branch_name = str(branch_name).strip()
                if not branch_name or len(branch_name) > 100 or any(ord(char) < 32 for char in branch_name):
                    raise ValueError("Use a branch name of 1–100 characters without control characters.")
            if branch_name is not None and branch_name in branches and branches[branch_name] != commit_id:
                raise ValueError("That branch already exists at a different saved point.")
            descriptor, staged_path = tempfile.mkstemp(prefix=".history-open-", suffix=".mf", dir=os.path.dirname(filepath))
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            candidate = self._load_candidate(staged_path)
            descriptor, original_path = tempfile.mkstemp(prefix=".history-previous-", suffix=".mf", dir=os.path.dirname(filepath))
            os.close(descriptor)
            shutil.copyfile(filepath, original_path)
            os.replace(staged_path, filepath)
            staged_path = None
            replaced = True
            self._restoring = True
            adopted = True
            self._adopt_model(candidate, filepath)
            new_baseline = self._live_fingerprint()
            if branch_name is not None and branch_name not in branches:
                self.store.create_branch(branch_name, commit_id)
            else:
                self.store.select_commit(commit_id, branch=branch_name)
            self.baseline = new_baseline
            self.tracked_model = candidate
        except Exception as error:
            rollback_error = None
            if replaced and original_path:
                try:
                    os.replace(original_path, filepath)
                    original_path = None
                except OSError as problem:
                    rollback_error = str(problem)
            if adopted:
                try:
                    self.window.graphics_settings = old_graphics
                    self._adopt_model(old_model, filepath)
                    for name, values in old_selections.items():
                        setattr(self.window, name, values)
                    self.window.draw_both_canvases()
                except Exception as problem:
                    rollback_error = rollback_error or str(problem)
                finally:
                    old_model.results = old_results
                    old_model.has_results = old_has_results
            self.baseline = old_baseline
            message = f"Could not open the saved point: {error}"
            if rollback_error:
                message += f"\nCould not fully restore the previous session: {rollback_error}"
                if original_path:
                    message += f"\nPrevious model copy: {original_path}"
                    original_path = None                                                 
            QMessageBox.warning(self.window, "Model history", message)
            return False
        finally:
            self._restoring = False
            for path in (staged_path, original_path):
                if path and os.path.exists(path):
                    os.remove(path)
                                                                                
        try:
            self._finish_checkout(old_model)
            self._status(f"Opened {commit_id[:8]}. Analysis results cleared.")
        except Exception as error:
            print(f"History point opened; interface cleanup: {error}")
        return True
