"""Offscreen checks for safe history navigation and branch creation."""

import importlib.util
import os
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication

def _load_dialog():
                                                                             
    theme = types.ModuleType("app.ui.theme")
    theme.COLORS = {"accent": "#0078D7"}
    theme.apply_dialog_style = lambda widget: None
    history = types.ModuleType("core.model_history")
    history.describe_changes = lambda before, after, limit=80: [
        f"value: {before['value']} → {after['value']}"
    ] if before != after else []
    path = Path(__file__).resolve().parents[1] / "app/dialogs/model_history_dialog.py"
    spec = importlib.util.spec_from_file_location("history_dialog_under_test", path)
    module = importlib.util.module_from_spec(spec)
    graph_path = path.with_name("model_history_graph.py")
    graph_spec = importlib.util.spec_from_file_location("app.dialogs.model_history_graph", graph_path)
    graph_module = importlib.util.module_from_spec(graph_spec)
    with patch.dict(sys.modules, {"app.ui.theme": theme, "core.model_history": history,
                                 "app.dialogs.model_history_graph": graph_module}):
        graph_spec.loader.exec_module(graph_module)
        spec.loader.exec_module(module)
    return module

dialog_module = _load_dialog()
ModelHistoryDialog = dialog_module.ModelHistoryDialog

class FakeStore:
    def __init__(self):
        self.commits = [
            {"id": "a", "parent_id": None, "label": "Initial model", "branch": "main"},
            {"id": "b", "parent_id": "a", "label": "Added loads", "branch": "main"},
            {"id": "c", "parent_id": "b", "label": "Larger columns", "branch": "main"},
            {"id": "d", "parent_id": "b", "label": "Added bracing", "branch": "bracing"},
            {"id": "e", "parent_id": "d", "label": "Adjusted bracing", "branch": "bracing"},
        ]
        for index, commit in enumerate(self.commits):
            commit.update(created_at=f"2026-10-30T12:0{index}:00+00:00", summary="")
        self.current = "e"
        self.active = "bracing"
        self.branches = {"main": "c", "bracing": "e"}
        self.corrupt = set()

    def state(self):
        return {"current_commit": self.current, "active_branch": self.active,
                "branches": dict(self.branches)}

    def list_commits(self):
        return list(self.commits)

    def get_snapshot(self, commit_id):
        if commit_id in self.corrupt:
            raise ValueError("Snapshot checksum failed")
        return {"value": commit_id}

class ModelHistoryDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.store = FakeStore()
        self.calls = []

        def checkout(commit_id, branch=None):
            self.calls.append((commit_id, branch))
            self.store.current = commit_id
            self.store.active = branch
            if branch:
                self.store.branches[branch] = commit_id
            return True

        self.dialog = ModelHistoryDialog(self.store, checkout)

    def tearDown(self):
        self.dialog.close()

    def select(self, commit_id):
        self.dialog.graph.select_commit(commit_id)

    def test_historical_open_keeps_later_branch_heads(self):
        self.select("b")
        self.dialog.btn_open.click()
        self.assertEqual(self.calls, [("b", None)])
        self.assertEqual(self.store.branches, {"main": "c", "bracing": "e"})
        self.assertIn("Earlier saved point", self.dialog.lbl_current.text())

    def test_open_branch_head_selects_that_branch(self):
        self.select("c")
        self.dialog.btn_open.click()
        self.assertEqual(self.calls, [("c", "main")])
        self.assertIn("Branch: main", self.dialog.lbl_current.text())

    def test_cancelled_branch_prompt_never_changes_history(self):
        self.select("b")
        with patch.object(dialog_module.QInputDialog, "getText", return_value=("trial", False)):
            self.dialog.btn_branch.click()
        self.assertEqual(self.calls, [])
        self.assertEqual(self.store.current, "e")
        self.assertNotIn("trial", self.store.branches)

    def test_named_branch_checkout_is_delegated_before_any_mutation(self):
        self.select("b")
        with patch.object(dialog_module.QInputDialog, "getText", return_value=("  trial  ", True)):
            self.dialog.btn_branch.click()
        self.assertEqual(self.calls, [("b", "trial")])
        self.assertEqual(self.store.branches["main"], "c")
        self.assertEqual(self.store.branches["trial"], "b")

    def test_existing_branch_name_does_not_checkout(self):
        self.select("b")
        with patch.object(dialog_module.QInputDialog, "getText", return_value=("main", True)),\
                patch.object(dialog_module.QMessageBox, "information"):
            self.dialog.btn_branch.click()
        self.assertEqual(self.calls, [])
        self.assertEqual(self.store.branches["main"], "c")

    def test_failed_checkout_does_not_change_visible_current_point(self):
        self.dialog.open_commit_callback = lambda *_: False
        self.select("b")
        self.dialog.btn_open.click()
        self.assertIn("Branch: bracing", self.dialog.lbl_current.text())
        self.assertEqual(self.store.current, "e")

    def test_corrupt_snapshot_disables_restore_and_branch(self):
        self.store.corrupt.add("b")
        self.dialog._details_cache.clear()
        self.select("b")
        self.assertFalse(self.dialog.btn_open.isEnabled())
        self.assertFalse(self.dialog.btn_branch.isEnabled())
        self.assertIn("checksum", self.dialog.changes.toPlainText())

    def test_missing_previous_snapshot_does_not_block_valid_restore(self):
        self.store.corrupt.add("b")
        self.dialog._details_cache.clear()
        self.select("c")
        self.assertTrue(self.dialog.btn_open.isEnabled())
        self.assertTrue(self.dialog.btn_branch.isEnabled())
        self.assertIn("Changes unavailable", self.dialog.changes.toPlainText())
        self.dialog.btn_open.click()
        self.assertEqual(self.calls, [("c", "main")])

    def test_empty_history_is_safe(self):
        self.store.commits = []
        self.store.current = None
        self.store.active = None
        self.store.branches = {}
        self.dialog.refresh()
        self.assertEqual(len(self.dialog.graph.nodes), 0)
        self.assertFalse(self.dialog.btn_open.isEnabled())
        self.assertFalse(self.dialog.btn_branch.isEnabled())
        self.assertIn("No saved points", self.dialog.lbl_current.text())

    def test_metadata_error_stays_in_dialog(self):
        with patch.object(self.store, "state", side_effect=OSError("History is locked")):
            self.assertFalse(self.dialog.refresh())
        self.assertFalse(self.dialog.btn_open.isEnabled())
        self.assertIn("locked", self.dialog.lbl_selected.text())

    def test_long_linear_history_does_not_deepen_or_recurse(self):
        self.store.commits = []
        for index in range(1500):
            self.store.commits.append({"id": str(index), "parent_id": str(index - 1) if index else None,
                                       "label": f"Save {index}", "branch": "main",
                                       "created_at": "2026-10-30T12:00:00+00:00"})
        self.store.current = "1499"
        self.store.active = "main"
        self.store.branches = {"main": "1499"}
        self.dialog.refresh()
        self.assertEqual(len(self.dialog.graph.nodes), 1500)
        self.assertEqual(len(self.dialog.graph.edges), 1499)

    def test_enter_is_not_an_implicit_restore(self):
        self.assertFalse(self.dialog.btn_open.autoDefault())
        self.assertFalse(self.dialog.btn_open.isDefault())
        self.assertFalse(self.dialog.btn_branch.autoDefault())

    def test_branch_forks_remain_visible_and_details_are_plain_text(self):
        edges = {(parent, child) for parent, child, _ in self.dialog.graph.edges}
        self.assertEqual(edges, {("a", "b"), ("b", "c"), ("b", "d"), ("d", "e")})
        self.select("c")
        self.assertIn("b → c", self.dialog.changes.toPlainText())
        self.assertEqual(self.dialog.lbl_selected.textFormat(), Qt.TextFormat.PlainText)

    def test_hover_previews_without_changing_action_target(self):
        self.select("c")
        self.dialog.graph.commitHovered.emit("b")
        self.assertIn("Hover: Added loads", self.dialog.lbl_selected.text())
        self.assertIn("a → b", self.dialog.changes.toPlainText())
        self.assertEqual(self.dialog.graph.selected_commit(), "c")
        self.dialog.btn_open.click()
        self.assertEqual(self.calls, [("c", "main")])

    def test_hover_leave_restores_selected_details(self):
        self.select("c")
        self.dialog.graph.commitHovered.emit("b")
        self.dialog.graph.commitHovered.emit(None)
        self.assertIn("Selected: Larger columns", self.dialog.lbl_selected.text())
        self.assertIn("b → c", self.dialog.changes.toPlainText())

    def test_vertical_switch_preserves_selection_and_actions(self):
        self.select("b")
        self.dialog.orientation.setCurrentIndex(1)
        self.assertEqual(self.dialog.graph.orientation, "vertical")
        self.assertEqual(self.dialog.graph.selected_commit(), "b")
        self.assertTrue(self.dialog.btn_open.isEnabled())

if __name__ == "__main__":
    unittest.main()
