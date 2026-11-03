"""Exercise checkout with real Qt undo state and a small serializer fixture."""

import copy
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtGui import QUndoCommand, QUndoStack
from PyQt6.QtWidgets import QApplication, QComboBox, QMessageBox, QWidget

from app.model_history_controller import ModelHistoryController
from core.model_history import atomic_save_model

class FixtureModel:
    def __init__(self):
        self.data = {"info": {"name": "Fixture", "units": "kN, m, C"}, "nodes": [{"id": 1, "z": 0}]}
        self.graphics_settings = {"show_grid": True}
        self.load_cases = {"DEFAULT": {}}
        self.mass_sources = {"DEFAULT": {}}
        self.results = {"displacements": [1.0]}
        self.has_results = True

    def save_to_file(self, path, progress=None):
        data = copy.deepcopy(self.data)
        data["graphics"] = self.graphics_settings
        Path(path).write_text(json.dumps(data), encoding="utf-8")

    def load_from_file(self, path):
        self.data = json.loads(Path(path).read_text(encoding="utf-8"))
        self.graphics_settings = self.data.get("graphics", {})
        self.saved_unit_system = self.data["info"]["units"]

class Window(QWidget):
    def __init__(self, path):
        super().__init__()
        self.model = FixtureModel()
        self.model.file_path = str(path)
        self.graphics_settings = {"show_grid": True, "background_color": [1, 1, 1, 1]}
        self.undo_stack = QUndoStack(self)
        self.status_messages = []
        self.status = SimpleNamespace(showMessage=lambda message, timeout=0: self.status_messages.append(message))
        self.canvas = SimpleNamespace(show_grid=True, set_standard_view=lambda value: None)
        self.terminal_panel = SimpleNamespace(set_model=lambda model: setattr(self, "terminal_model", model))
        self.model_tree = SimpleNamespace(refresh=lambda: None)
        self.combo_units = QComboBox(self)
        self.combo_units.addItem("kN, m, C")
        self.selected_ids = [5]
        self.selected_node_ids = [1]
        self.fail_next_draw = False
        self.purges = 0
        self.controller = ModelHistoryController(self, FixtureModel)

    def _purge_results_and_visuals(self):
        self.purges += 1

    def _apply_canvas_view_settings(self, settings):
        self.canvas.show_grid = settings.get("show_grid", True)

    def update_graphics_settings(self, settings):
        pass

    def on_units_changed(self, value, redraw=True):
        pass

    def draw_both_canvases(self):
        if self.fail_next_draw:
            self.fail_next_draw = False
            raise RuntimeError("Drawing fixture failed")

    def update_yield_lines(self):
        pass

    def set_interface_state(self, value):
        pass

    def update_window_title(self):
        pass

    def on_save_model(self):
        path = self.model.file_path
        self.controller.before_save(path)
        atomic_save_model(self.model, path)
        self.undo_stack.setClean()
        self.controller.note_saved(path)
        return True

class ControllerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.application = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.path = Path(self.temporary.name) / "fixture.mf"
        self.window = Window(self.path)
        self.assertTrue(self.window.on_save_model())
        self.controller = self.window.controller
        self.first = self.controller.store.state()["current_commit"]
        self.window.model.data["nodes"][0]["z"] = 3
        self.window.on_save_model()
        self.latest = self.controller.store.state()["current_commit"]

    def tearDown(self):
        self.window.close()
        self.window.deleteLater()
        self.application.processEvents()
        self.temporary.cleanup()

    def test_load_normalization_is_not_mistaken_for_an_edit(self):
        self.assertFalse(self.controller.has_unsaved_changes())
        self.window.model.data["nodes"][0]["z"] = 5
        self.assertTrue(self.window.undo_stack.isClean())
        self.assertTrue(self.controller.has_unsaved_changes())

    def test_checkout_preserves_later_saves_and_clears_results(self):
        self.assertTrue(self.controller.open_commit(self.first))
        self.assertEqual(self.window.model.data["nodes"][0]["z"], 0)
        self.assertEqual(self.controller.store.state()["branches"]["main"], self.latest)
        self.assertEqual(self.controller.store.state()["current_commit"], self.first)
        self.assertFalse(self.window.model.has_results)
        self.assertEqual(self.window.model.results, {})
        self.assertEqual(self.window.selected_node_ids, [])
        self.assertEqual(self.window.model.load_cases, {})
        self.assertEqual(self.window.model.mass_sources, {})
        self.assertTrue(self.window.undo_stack.isClean())
        self.assertFalse(self.controller.has_unsaved_changes())

    def test_named_branch_and_future_saves_work_after_restart(self):
        self.assertTrue(self.controller.open_commit(self.first, "Bracing"))
        self.assertEqual(self.controller.store.state()["active_branch"], "Bracing")
        self.window.model.data["nodes"][0]["z"] = 8
        self.window.on_save_model()
        head = self.controller.store.state()["current_commit"]
        from core.model_history import HistoryStore
        reopened = HistoryStore(self.path)
        self.assertEqual(reopened.state()["branches"], {"Bracing": head, "main": self.latest})

    def test_changed_save_at_old_point_automatically_forks(self):
        self.assertTrue(self.controller.open_commit(self.first))
        self.window.model.data["nodes"][0]["z"] = 8
        self.window.on_save_model()
        state = self.controller.store.state()
        self.assertEqual(state["branches"]["main"], self.latest)
        self.assertEqual(state["active_branch"], "branch-1")

    def test_cancel_protects_edits_not_registered_with_undo(self):
        self.window.model.data["nodes"][0]["z"] = 12
        original = self.window.model
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Cancel) as prompt:
            self.assertFalse(self.controller.open_commit(self.first))
        prompt.assert_called_once()
        self.assertIs(self.window.model, original)
        self.assertEqual(self.window.model.data["nodes"][0]["z"], 12)
        self.assertEqual(self.controller.store.state()["current_commit"], self.latest)

    def test_save_before_checkout_preserves_uncommitted_edits(self):
        self.window.model.data["nodes"][0]["z"] = 12
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Save):
            self.assertTrue(self.controller.open_commit(self.first))
        commits = self.controller.store.list_commits()
        self.assertEqual(len(commits), 3)
        self.assertEqual(self.controller.store.get_snapshot(commits[-1]["id"])["nodes"][0]["z"], 12)

    def test_failed_metadata_mutation_preserves_file_model_undo_results(self):
        self.window.undo_stack.push(QUndoCommand("Fixture edit"))
        old_model = self.window.model
        original_bytes = self.path.read_bytes()
        old_state = self.controller.store.state()
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Discard),\
                patch.object(QMessageBox, "warning"),\
                patch.object(self.controller.store, "create_branch", side_effect=RuntimeError("Database is locked")):
            self.assertFalse(self.controller.open_commit(self.first, "Trial"))
        self.assertEqual(self.path.read_bytes(), original_bytes)
        self.assertIs(self.window.model, old_model)
        self.assertEqual(self.window.undo_stack.count(), 1)
        self.assertFalse(self.window.undo_stack.isClean())
        self.assertEqual(self.window.model.results, {"displacements": [1.0]})
        self.assertTrue(self.window.model.has_results)
        self.assertEqual(self.controller.store.state(), old_state)

    def test_invalid_branch_never_replaces_file_or_purges_session(self):
        original = self.window.model
        with patch.object(QMessageBox, "warning"):
            self.assertFalse(self.controller.open_commit(self.first, "x" * 101))
        self.assertIs(self.window.model, original)
        self.assertEqual(self.window.purges, 0)

    def test_failed_candidate_load_preserves_original_session(self):
        original = self.window.model
        original_bytes = self.path.read_bytes()
        with patch.object(self.controller, "_load_candidate", side_effect=ValueError("Unsupported model")),\
                patch.object(QMessageBox, "warning"):
            self.assertFalse(self.controller.open_commit(self.first))
        self.assertIs(self.window.model, original)
        self.assertEqual(self.path.read_bytes(), original_bytes)
        self.assertEqual(self.window.purges, 0)

    def test_failed_ui_adoption_rolls_back_inputs_and_history(self):
        original = self.window.model
        original_bytes = self.path.read_bytes()
        self.window.fail_next_draw = True
        with patch.object(QMessageBox, "warning"):
            self.assertFalse(self.controller.open_commit(self.first))
        self.assertIs(self.window.model, original)
        self.assertEqual(self.path.read_bytes(), original_bytes)
        self.assertEqual(self.controller.store.state()["current_commit"], self.latest)

    def test_new_model_first_save_does_not_inherit_previous_history(self):
        second_path = Path(self.temporary.name) / "other.mf"
        self.window.model = FixtureModel()
        self.window.model.file_path = str(second_path)
        self.window.on_save_model()
        self.assertEqual(len(self.controller.store.list_commits()), 1)
        self.assertNotEqual(self.controller.store.state()["current_commit"], self.first)

    def test_save_as_preserves_history_after_a_checkout(self):
        self.assertTrue(self.controller.open_commit(self.first, "Trial"))
        second_path = Path(self.temporary.name) / "copy.mf"
        self.window.model.file_path = str(second_path)
        self.window.on_save_model()
        self.assertEqual(len(self.controller.store.list_commits()), 2)
        self.assertEqual(self.controller.store.state()["active_branch"], "Trial")

if __name__ == "__main__":
    unittest.main()
