"""Applying frame loads draws the final selection once and preserves undo data."""
import ast
import os
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PyQt6.QtGui import QUndoStack
from PyQt6.QtWidgets import QApplication, QWidget
from app.commands import CmdAssignFrameLoad
from app.dialogs.assign_member_load_dialog import AssignFrameLoadDialog
from core.model import StructuralModel
from core.units import unit_registry

tree = ast.parse((ROOT / 'app/main.py').read_text(encoding='utf-8-sig'))
owner = next(node for node in tree.body if isinstance(node, ast.ClassDef)
             and node.name == 'MainWindow')
methods = [node for node in owner.body if isinstance(node, ast.FunctionDef)
           and node.name in ('add_command', 'draw_both_canvases')]
namespace = {}
exec(compile(ast.fix_missing_locations(ast.Module(body=methods, type_ignores=[])),
             'actual frame apply redraw routing', 'exec'), namespace)

class Window(QWidget):
    add_command = namespace['add_command']
    draw_both_canvases = namespace['draw_both_canvases']

    def __init__(self):
        super().__init__()
        self.model = StructuralModel('Frame load apply regression')
        section = SimpleNamespace(name='Beam')
        for index in range(3):
            first = self.model.add_node(index * 2., 0., 0.)
            last = self.model.add_node(index * 2. + 1., 0., 0.)
            self.model.add_element(first, last, section)
        self.selected_ids = [1, 2]
        self.selected_node_ids = []
        self.undo_stack = QUndoStack(self)
        self.canvas = SimpleNamespace(draw_model=Mock())
        self.canvas2 = SimpleNamespace(draw_model=Mock())
        self.canvas2_visible = True
        self.model_tree = SimpleNamespace(sync_selection=Mock())
        self.status = SimpleNamespace(showMessage=Mock())

def snapshot(model):
    return sorted((repr(vars(load)) for load in model.loads))

class FrameLoadApplyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.application = QApplication.instance() or QApplication([])

    def test_apply_draws_each_canvas_once_with_final_selection_and_undo_redo(self):
        for mode in ('replace', 'add', 'delete'):
            with self.subTest(mode=mode):
                window = Window()
                window.model.assign_member_load(1, 'DEAD', wz=-1000.)
                window.model.assign_member_load(3, 'DEAD', wz=-9000.)
                window.model.assign_member_load(1, 'OTHER', wy=2000.)
                before = snapshot(window.model)
                dialog = AssignFrameLoadDialog(window)
                dialog.in_uniform.setText('5')
                getattr(dialog, 'rb_' + mode).setChecked(True)
                self.assertTrue(dialog.apply_loads())
                self.assertEqual(window.selected_ids, [])
                self.assertEqual(window.undo_stack.count(), 1)
                for canvas in (window.canvas, window.canvas2):
                    canvas.draw_model.assert_called_once()
                    self.assertEqual(canvas.draw_model.call_args.args[1], [])
                after = snapshot(window.model)
                self.assertNotEqual(after, before)
                unaffected = [load for load in window.model.loads
                              if load.element_id == 3 or load.pattern_name == 'OTHER']
                self.assertEqual(len(unaffected), 2)
                if mode != 'delete':
                    scale = unit_registry.force_scale / unit_registry.length_scale
                    assigned = [load for load in window.model.loads
                                if load.element_id == 2 and load.pattern_name == 'DEAD']
                    self.assertEqual(len(assigned), 1)
                    self.assertEqual(assigned[0].wz, -5. / scale)
                    self.assertEqual(assigned[0].magnitudes, [-5. / scale] * 4)
                window.undo_stack.undo()
                self.assertEqual(snapshot(window.model), before)
                window.undo_stack.redo()
                self.assertEqual(snapshot(window.model), after)
                for canvas in (window.canvas, window.canvas2):
                    self.assertEqual(canvas.draw_model.call_count, 3)
                dialog.close()

    def test_push_error_restores_the_frame_selection(self):
        window = Window()
        dialog = AssignFrameLoadDialog(window)
        dialog.in_uniform.setText('5')
        window.add_command = Mock(side_effect=RuntimeError('push failed'))
        with self.assertRaisesRegex(RuntimeError, 'push failed'):
            dialog.apply_loads()
        self.assertEqual(window.selected_ids, [1, 2])
        self.assertEqual(window.model.loads, [])
        window.canvas.draw_model.assert_not_called()
        window.canvas2.draw_model.assert_not_called()
        dialog.close()

    def test_invalid_input_keeps_selection_without_pushing_or_drawing(self):
        window = Window()
        dialog = AssignFrameLoadDialog(window)
        dialog.in_uniform.setText('invalid')
        with patch('app.dialogs.assign_member_load_dialog.QMessageBox.warning'):
            self.assertFalse(dialog.apply_loads())
        self.assertEqual(window.selected_ids, [1, 2])
        self.assertEqual(window.undo_stack.count(), 0)
        window.canvas.draw_model.assert_not_called()
        dialog.close()

    def test_command_owns_selection_snapshot_for_later_undo_and_redo(self):
        window = Window()
        window.model.assign_member_load(1, 'DEAD', wz=-1000.)
        before = snapshot(window.model)
        selected = [1, 2]
        command = CmdAssignFrameLoad(window.model, window, selected, 'DEAD',
                                    0., 0., -5000., False, 'Global')
        selected.clear()
        command.redo()
        after = snapshot(window.model)
        self.assertEqual({load.element_id for load in window.model.loads}, {1, 2})
        command.undo()
        self.assertEqual(snapshot(window.model), before)
        command.redo()
        self.assertEqual(snapshot(window.model), after)

if __name__ == '__main__':
    unittest.main()
