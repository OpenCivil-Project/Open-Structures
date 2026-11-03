"""Offscreen user-behavior and graph-layout checks."""

import importlib.util
import os
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt6.QtCore import QPointF, Qt
from PyQt6.QtGui import QWheelEvent
from PyQt6.QtTest import QSignalSpy, QTest
from PyQt6.QtWidgets import QApplication

def _load_graph():
    theme = types.ModuleType("app.ui.theme")
    theme.COLORS = {"accent": "#0078D7"}
    path = Path(__file__).resolve().parents[1] / "app/dialogs/model_history_graph.py"
    spec = importlib.util.spec_from_file_location("history_graph_under_test", path)
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, {"app.ui.theme": theme}):
        spec.loader.exec_module(module)
    return module.HistoryGraph

HistoryGraph = _load_graph()

def commits():
    return [
        {"id": "a", "parent_id": None, "branch": "main", "label": "Initial model"},
        {"id": "b", "parent_id": "a", "branch": "main", "label": "Added loads"},
        {"id": "c", "parent_id": "b", "branch": "main", "label": "Larger columns"},
        {"id": "d", "parent_id": "b", "branch": "bracing", "label": "Added bracing"},
        {"id": "e", "parent_id": "d", "branch": "bracing", "label": "Adjusted braces"},
    ]

class HistoryGraphTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.graph = HistoryGraph()
        self.graph.resize(630, 250)
        self.state = {"current_commit": "e", "active_branch": "bracing",
                      "branches": {"main": "c", "bracing": "e"}}
        self.graph.set_history(commits(), self.state)
        self.graph.show()
        self.app.processEvents()

    def tearDown(self):
        self.graph.close()

    def test_horizontal_graph_has_connected_colored_branch_lanes(self):
        self.assertEqual(self.graph.orientation, "horizontal")
        self.assertEqual(len(self.graph.edges), 4)
        for parent, child, edge in self.graph.edges:
            self.assertGreater(self.graph.positions[child][0], self.graph.positions[parent][0])
            self.assertFalse(edge.path().isEmpty())
        self.assertEqual(self.graph.positions["b"][1], self.graph.positions["c"][1])
        self.assertGreater(self.graph.positions["d"][1], self.graph.positions["b"][1])
        self.assertEqual(self.graph.positions["d"][1], self.graph.positions["e"][1])
        self.assertNotEqual(self.graph.nodes["c"].color, self.graph.nodes["d"].color)

    def test_vertical_option_preserves_forward_edges_and_selection(self):
        self.graph.select_commit("b")
        self.graph.set_orientation("vertical")
        self.assertEqual(self.graph.selected_commit(), "b")
        for parent, child, _ in self.graph.edges:
            self.assertGreater(self.graph.positions[child][1], self.graph.positions[parent][1])
        self.assertGreater(self.graph.positions["d"][0], self.graph.positions["b"][0])

    def test_selected_and_current_markers_are_independent(self):
        self.graph.select_commit("b")
        self.assertTrue(self.graph.nodes["b"].isSelected())
        self.assertFalse(self.graph.nodes["b"].current)
        self.assertTrue(self.graph.nodes["e"].current)
        self.assertFalse(self.graph.nodes["e"].isSelected())

    def test_node_click_emits_selection_without_changing_model_current(self):
        self.graph.select_commit("a")
        self.app.processEvents()
        spy = QSignalSpy(self.graph.commitSelected)
        self.graph.select_commit("b")
        self.assertEqual(list(spy), [["b"]])
        self.assertEqual(self.graph._state["current_commit"], "e")
        self.assertEqual(self.graph._state["branches"]["main"], "c")

    def test_actual_click_and_doubleclick_only_select(self):
        self.graph.select_commit("b")
        self.app.processEvents()
        position = self.graph.mapFromScene(QPointF(*self.graph.positions["b"]))
        QTest.mouseClick(self.graph.viewport(), Qt.MouseButton.LeftButton, pos=position)
        QTest.mouseDClick(self.graph.viewport(), Qt.MouseButton.LeftButton, pos=position)
        self.assertEqual(self.graph.selected_commit(), "b")
        self.assertEqual(self.graph._state["current_commit"], "e")

    def test_keyboard_navigation_and_enter_do_not_checkout(self):
        self.graph.select_commit("b")
        QTest.keyClick(self.graph, Qt.Key.Key_Right)
        self.assertEqual(self.graph.selected_commit(), "c")
        QTest.keyClick(self.graph, Qt.Key.Key_Left)
        self.assertEqual(self.graph.selected_commit(), "b")
        QTest.keyClick(self.graph, Qt.Key.Key_Return)
        self.assertEqual(self.graph.selected_commit(), "b")
        self.assertEqual(self.graph._state["current_commit"], "e")

    def test_tooltip_escapes_values_and_contains_full_details(self):
        data = commits()
        data[1]["label"] = "<img src=secret> A complete label"
        data[1]["summary"] = "<script>do not execute</script>"
        data[1]["created_at"] = "2026-10-30T12:00:00+00:00"
        self.graph.set_history(data, self.state, "b")
        tooltip = self.graph.nodes["b"].toolTip()
        self.assertIn("&lt;img", tooltip)
        self.assertNotIn("<img", tooltip)
        self.assertIn("&lt;script&gt;", tooltip)
        self.assertIn("2026-10-30", tooltip)

    def test_empty_and_corrupt_metadata_stays_browsable(self):
        self.graph.set_history([], {})
        self.assertIsNone(self.graph.selected_commit())
        self.assertEqual(self.graph.nodes, {})
        data = [None, {"id": []}, {"id": "a", "parent_id": "b"},
                {"id": "b", "parent_id": "a"}, {"id": "c", "parent_id": "missing"}]
        self.graph.set_history(data, {"current_commit": [], "branches": []}, selected_id=[])
        self.assertEqual(set(self.graph.nodes), {"a", "b", "c"})
        self.assertIsNotNone(self.graph.selected_commit())
        self.assertEqual(self.graph.edges, [])

    def test_long_history_keeps_labels_readable_and_selected_visible(self):
        data = [{"id": str(index), "parent_id": str(index - 1) if index else None,
                 "branch": "main", "label": f"Save {index}"} for index in range(1500)]
        self.graph.set_history(data, {"current_commit": "1499", "branches": {"main": "1499"}})
        self.app.processEvents()
        self.assertEqual(len(self.graph.nodes), 1500)
        self.assertEqual(len(self.graph.edges), 1499)
        self.assertGreaterEqual(self.graph.transform().m11(), 0.78)
        self.assertGreater(self.graph.horizontalScrollBar().maximum(), 0)
        selected = self.graph.mapFromScene(QPointF(*self.graph.positions["1499"]))
        self.assertTrue(self.graph.viewport().rect().contains(selected))

    def test_out_of_order_commits_still_flow_forward(self):
        self.graph.set_history(list(reversed(commits())), self.state)
        for parent, child, _ in self.graph.edges:
            self.assertGreater(self.graph.positions[child][0], self.graph.positions[parent][0])

if __name__ == "__main__":
    unittest.main()
