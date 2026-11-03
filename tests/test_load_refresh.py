"""Load edits reuse existing structural buffers and preserve visible selections."""
import ast
import copy
import os
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PyQt6.QtGui import QUndoCommand, QUndoStack
from PyQt6.QtWidgets import QApplication, QWidget
from app.dialogs.assign_member_load_dialog import AssignFrameLoadDialog
from app.dialogs.dlg_area_uniform_load import AreaUniformLoadDialog
from app.dialogs.dlg_area_gravity_load import AreaGravityLoadDialog
from core.model import StructuralModel
from core.units import unit_registry

source = ast.parse((ROOT / 'app/main.py').read_text(encoding='utf-8-sig'))
owner = next(node for node in source.body if isinstance(node, ast.ClassDef)
             and node.name == 'MainWindow')
methods = [node for node in owner.body if isinstance(node, ast.FunctionDef)
           and node.name in ('add_command', 'request_load_refresh', 'refresh_load_display',
                            '_on_model_changed', '_on_tributary_update_received')]
namespace = {}
exec(compile(ast.fix_missing_locations(ast.Module(body=methods, type_ignores=[])),
             'actual load edit refresh routing', 'exec'), namespace)

def canvas(model, ready=True):
    result = SimpleNamespace(current_model=model,
        vbo_manager=SimpleNamespace(is_initialized=ready),
        selected_area_ids=[], selected_link_ids=[], selected_tendon_ids=[],
        selected_cable_ids=[], draw_model=Mock(), invalidate_area_vbo=Mock())

    def overlay(elements, nodes, areas, links, tendons):
        result.selected_element_ids = list(elements)
        result.selected_node_ids = list(nodes)
        result.selected_area_ids = list(areas)
        result.selected_link_ids = list(links)
        result.selected_tendon_ids = list(tendons)

    result.update_selection_overlay = Mock(side_effect=overlay)
    return result

class Window(QWidget):
    add_command = namespace['add_command']
    request_load_refresh = namespace['request_load_refresh']
    refresh_load_display = namespace['refresh_load_display']
    _on_model_changed = namespace['_on_model_changed']
    _on_tributary_update_received = namespace['_on_tributary_update_received']

    def __init__(self):
        super().__init__()
        self.model = StructuralModel('Load edit refresh regression')
        section = SimpleNamespace(name='Beam')
        for index in range(3):
            first = self.model.add_node(index * 2., 0., 0.)
            last = self.model.add_node(index * 2. + 1., 0., 0.)
            self.model.add_element(first, last, section)
        self.model.area_elements = {
            1: SimpleNamespace(id=1, section=SimpleNamespace(modeling_type='Shell')),
            2: SimpleNamespace(id=2, section=SimpleNamespace(modeling_type='Tributary Area')),
            3: SimpleNamespace(id=3, section=SimpleNamespace(modeling_type='Shell'))}
        self.selected_ids = [1, 2]
        self.selected_node_ids = [5]
        self.selected_area_ids = [1, 2]
        self.selected_link_ids = [4]
        self.selected_tendon_ids = [6]
        self.selected_cable_ids = [7]
        self.undo_stack = QUndoStack(self)
        self.undo_stack.indexChanged.connect(self._on_model_changed)
        self.canvas = canvas(self.model)
        self.canvas2 = canvas(self.model)
        self.canvas2_visible = True
        self.canvas_2d = SimpleNamespace(isVisible=Mock(return_value=True), draw_model=Mock())
        self.model_tree = SimpleNamespace(sync_selection=Mock(), refresh=Mock())
        self.status = SimpleNamespace(showMessage=Mock())
        self.update_yield_lines = Mock()
        self.draw_both_canvases = Mock(side_effect=AssertionError('rebuild structural model'))
        self._refresh_selection_overlay = Mock(side_effect=AssertionError('duplicate load rebuild'))

class AddNodeCommand(QUndoCommand):
    """A structural edit whose rendering comes from the production observer."""
    def __init__(self, model):
        super().__init__('Add node')
        self.model = model
        self.node_id = None

    def redo(self):
        self.node_id = self.model.add_node(100., 200., 300.).id

    def undo(self):
        del self.model.nodes[self.node_id]

def snapshot(model):
    return sorted(repr(vars(load)) for load in model.loads)

class LoadRefreshTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.application = QApplication.instance() or QApplication([])

    def test_existing_visible_canvases_use_only_overlay_and_keep_all_selections(self):
        window = Window()
        window.refresh_load_display()
        for cv in (window.canvas, window.canvas2):
            cv.draw_model.assert_not_called()
            cv.update_selection_overlay.assert_called_once_with([1, 2], [5], [1, 2], [4], [6])
            self.assertEqual(cv.selected_cable_ids, [7])
        window.canvas_2d.draw_model.assert_called_once_with(window.model)
        window.model_tree.sync_selection.assert_called_once_with(
            sel_nodes=[5], sel_elems=[1, 2], sel_areas=[1, 2],
            sel_links=[4], sel_tendons=[6], sel_cables=[7])
        self.assertFalse(window._supports_only_refresh)

    def test_hidden_secondary_and_2d_canvases_do_no_render_work(self):
        window = Window()
        window.canvas2_visible = False
        window.canvas_2d.isVisible.return_value = False
        window.refresh_load_display()
        window.canvas.update_selection_overlay.assert_called_once()
        window.canvas2.update_selection_overlay.assert_not_called()
        window.canvas2.draw_model.assert_not_called()
        window.canvas_2d.draw_model.assert_not_called()

    def test_not_initialized_canvas_fallback_preserves_non_frame_selections(self):
        window = Window()
        window.canvas.vbo_manager.is_initialized = False
        window.refresh_load_display()
        window.canvas.update_selection_overlay.assert_not_called()
        window.canvas.draw_model.assert_called_once_with(window.model, [1, 2], [5])
        self.assertEqual(window.canvas.selected_area_ids, [1, 2])
        self.assertEqual(window.canvas.selected_link_ids, [4])
        self.assertEqual(window.canvas.selected_tendon_ids, [6])
        self.assertEqual(window.canvas.selected_cable_ids, [7])

    def test_stale_canvas_model_gets_initialized_for_current_model(self):
        window = Window()
        window.canvas2.current_model = object()
        window.refresh_load_display()
        window.canvas.update_selection_overlay.assert_called_once()
        window.canvas2.update_selection_overlay.assert_not_called()
        window.canvas2.draw_model.assert_called_once_with(window.model, [1, 2], [5])

    def test_no_model_does_no_render_or_tree_work(self):
        window = Window()
        window.model = None
        window.refresh_load_display()
        window.model_tree.sync_selection.assert_not_called()
        window.canvas.update_selection_overlay.assert_not_called()
        window.canvas.draw_model.assert_not_called()

    def test_async_tributary_update_invalidates_heatmap_then_refreshes_overlays(self):
        window = Window()
        calls = Mock()
        calls.attach_mock(window.canvas.invalidate_area_vbo, 'primary_heatmap')
        calls.attach_mock(window.canvas2.invalidate_area_vbo, 'secondary_heatmap')
        calls.attach_mock(window.canvas.update_selection_overlay, 'primary_overlay')
        calls.attach_mock(window.canvas2.update_selection_overlay, 'secondary_overlay')
        window._on_tributary_update_received()
        self.assertEqual([call[0] for call in calls.mock_calls],
            ['primary_heatmap', 'secondary_heatmap', 'primary_overlay', 'secondary_overlay'])
        for cv in (window.canvas, window.canvas2):
            cv.draw_model.assert_not_called()
        window.draw_both_canvases.assert_not_called()

    def test_frame_apply_and_undo_redo_each_refresh_final_loads_once(self):
        for mode in ('replace', 'add', 'delete'):
            with self.subTest(mode=mode):
                window = Window()
                window.model.assign_member_load(1, 'DEAD', wz=-1000.)
                window.model.assign_member_load(3, 'OTHER', wy=2000.)
                before = snapshot(window.model)
                dialog = AssignFrameLoadDialog(window)
                dialog.in_uniform.setText('5')
                getattr(dialog, 'rb_' + mode).setChecked(True)
                self.assertTrue(dialog.apply_loads())
                after = snapshot(window.model)
                self.assertNotEqual(after, before)
                for cv in (window.canvas, window.canvas2):
                    cv.update_selection_overlay.assert_called_once_with([], [5], [1, 2], [4], [6])
                    cv.draw_model.assert_not_called()
                window.undo_stack.undo()
                self.assertEqual(snapshot(window.model), before)
                window.undo_stack.redo()
                self.assertEqual(snapshot(window.model), after)
                for cv in (window.canvas, window.canvas2):
                    self.assertEqual(cv.update_selection_overlay.call_count, 3)
                    cv.draw_model.assert_not_called()
                self.assertEqual(window.update_yield_lines.call_count, 3)
                self.assertEqual(window.model_tree.refresh.call_count, 3)
                self.assertFalse(window._loads_only_refresh)
                window.draw_both_canvases.assert_not_called()
                dialog.close()

    def test_load_request_waits_for_undo_stack_observer_before_rendering(self):
        window = Window()
        window.request_load_refresh()
        self.assertTrue(window._loads_only_refresh)
        window.canvas.update_selection_overlay.assert_not_called()
        window.update_yield_lines.assert_not_called()
        window._on_model_changed(window.undo_stack.index())
        self.assertFalse(window._loads_only_refresh)
        window.canvas.update_selection_overlay.assert_called_once()
        window.update_yield_lines.assert_called_once()
        window.model_tree.refresh.assert_called_once()
        window.draw_both_canvases.assert_not_called()

    def test_structural_edit_after_load_edit_uses_normal_model_redraw(self):
        window = Window()
        dialog = AssignFrameLoadDialog(window)
        dialog.in_uniform.setText('5')
        self.assertTrue(dialog.apply_loads())
        self.assertFalse(window._loads_only_refresh)
        window.canvas.update_selection_overlay.assert_called_once()
        window.draw_both_canvases = Mock()
        previous_nodes = set(window.model.nodes)
        command = AddNodeCommand(window.model)
        window.undo_stack.push(command)
        self.assertEqual(set(window.model.nodes), previous_nodes | {command.node_id})
        window.draw_both_canvases.assert_called_once()
        self.assertEqual(window.canvas.update_selection_overlay.call_count, 1)
        self.assertEqual(window.update_yield_lines.call_count, 2)
        self.assertEqual(window.model_tree.refresh.call_count, 2)
        window.undo_stack.undo()
        self.assertEqual(set(window.model.nodes), previous_nodes)
        self.assertEqual(window.draw_both_canvases.call_count, 2)
        self.assertEqual(window.canvas.update_selection_overlay.call_count, 1)
        self.assertEqual(window.update_yield_lines.call_count, 3)
        self.assertEqual(window.model_tree.refresh.call_count, 3)
        dialog.close()

    def test_uniform_area_modes_bulk_assign_once_then_refresh_final_selection(self):
        for mode in ('replace', 'add', 'delete'):
            with self.subTest(mode=mode):
                window = Window()
                window.model.assign_area_uniform_load(1, 'DEAD', uniform_load=1000.)
                window.model.assign_area_uniform_load(3, 'OTHER', uniform_load=2000.)
                prior_other = copy.deepcopy(vars(window.model.loads[-1]))
                actual_batch = window.model.assign_area_uniform_loads
                window.model.assign_area_uniform_loads = Mock(wraps=actual_batch)
                window.model.assign_area_uniform_load = Mock(side_effect=AssertionError('per-area load scans'))
                dialog = AreaUniformLoadDialog(window.model, window)
                dialog.edit_load.setText('5')
                getattr(dialog, 'rb_' + mode).setChecked(True)
                dialog._apply()
                window.model.assign_area_uniform_loads.assert_called_once_with(
                    [1, 2], 'DEAD', unit_registry.from_display_pressure(5.), 'Gravity', 'GLOBAL', mode)
                self.assertEqual(window.selected_area_ids, [])
                window.update_yield_lines.assert_called_once()
                for cv in (window.canvas, window.canvas2):
                    cv.update_selection_overlay.assert_called_once_with([1, 2], [5], [], [4], [6])
                    cv.draw_model.assert_not_called()
                unchanged = next(load for load in window.model.loads if load.pattern_name == 'OTHER')
                self.assertEqual(vars(unchanged), prior_other)
                dialog.close()

    def test_uniform_in_plane_load_skips_tributary_areas_before_batch(self):
        window = Window()
        window.model.assign_area_uniform_loads = Mock()
        dialog = AreaUniformLoadDialog(window.model, window)
        dialog.combo_direction.setCurrentText('Global X')
        dialog.edit_load.setText('5')
        with patch('app.dialogs.dlg_area_uniform_load.QMessageBox.warning') as warning:
            dialog._apply()
        window.model.assign_area_uniform_loads.assert_called_once_with(
            [1], 'DEAD', unit_registry.from_display_pressure(5.), 'Global X', 'GLOBAL', 'replace')
        warning.assert_called_once()
        window.canvas.update_selection_overlay.assert_called_once()
        dialog.close()

    def test_area_gravity_refreshes_once_and_keeps_other_pattern(self):
        window = Window()
        window.model.assign_area_gravity_load(3, 'OTHER', gz=-2.)
        actual_batch = window.model.assign_area_gravity_loads
        window.model.assign_area_gravity_loads = Mock(wraps=actual_batch)
        window.model.assign_area_gravity_load = Mock(side_effect=AssertionError('per-area load scans'))
        dialog = AreaGravityLoadDialog(window.model, window)
        dialog.edit_gz.setText('-1')
        dialog._apply()
        window.model.assign_area_gravity_loads.assert_called_once_with(
            [1, 2], 'DEAD', 0., 0., -1., 'GLOBAL', 'replace')
        self.assertEqual(window.selected_area_ids, [])
        assigned = [(load.area_id, load.gz) for load in window.model.loads if load.pattern_name == 'DEAD']
        self.assertEqual(assigned, [(1, -1.), (2, -1.)])
        self.assertEqual(next(load.gz for load in window.model.loads if load.pattern_name == 'OTHER'), -2.)
        window.update_yield_lines.assert_called_once()
        for cv in (window.canvas, window.canvas2):
            cv.update_selection_overlay.assert_called_once()
            cv.draw_model.assert_not_called()
        dialog.close()

    def test_in_plane_gravity_skips_tributary_before_single_batch(self):
        window = Window()
        window.model.assign_area_gravity_loads = Mock()
        window.model.assign_area_gravity_load = Mock(side_effect=AssertionError('per-area load scans'))
        dialog = AreaGravityLoadDialog(window.model, window)
        dialog.edit_gx.setText('0.25')
        with patch('app.dialogs.dlg_area_gravity_load.QMessageBox.warning') as warning:
            dialog._apply()
        window.model.assign_area_gravity_loads.assert_called_once_with(
            [1], 'DEAD', 0.25, 0., 0., 'GLOBAL', 'replace')
        warning.assert_called_once()
        window.canvas.update_selection_overlay.assert_called_once()
        dialog.close()

if __name__ == '__main__':
    unittest.main()
