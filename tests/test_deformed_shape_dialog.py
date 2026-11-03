"""Exercise scale controls with real Qt widgets, without opening an application."""
import os
import json
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt6.QtWidgets import QApplication, QWidget, QPushButton

from app.dialogs.deformed_shape_dialog import DeformedShapeDialog

class Parent(QWidget):
    def __init__(self):
        super().__init__()
        self.calls = []
        self.refreshes = 0
        self.speeds = []
        self.ranges = []
        self.playback = []
        self.active_canvas = SimpleNamespace(auto_deflection_scale=0.0247291990219501,
                                              refresh_deformed_playback=self.refresh)
        self.canvas = SimpleNamespace(refresh_deformed_playback=lambda: None)

    def refresh(self):
        self.refreshes += 1

    def apply_deformed_shape(self, *args):
        self.calls.append(args)

    def set_animation_speed(self, speed):
        self.speeds.append(speed)

    def set_ltha_playback_range(self, start, end):
        self.ranges.append((start, end))
        return True

    def toggle_animation(self, start, sound):
        self.playback.append(start)

class DeformedShapeDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.application = QApplication.instance() or QApplication([])

    def setUp(self):
        self.parent = Parent()
        with patch.object(DeformedShapeDialog, "_load_prefs"):
            self.dialog = DeformedShapeDialog(
                parent=self.parent, current_scale=0.0247291990219501,
                auto_scale=0.0247291990219501, is_active=True,
            )

    def tearDown(self):
        self.dialog.close()
        self.dialog.deleteLater()
        self.parent.deleteLater()
        self.application.processEvents()

    def test_fractional_current_scale_is_preserved(self):
        self.assertAlmostEqual(self.dialog.spin_scale.value(), 0.0247291990219501, places=8)

    def test_playback_speed_defaults_to_one(self):
        self.assertEqual(self.dialog.spin_speed.value(), 1.0)

    def test_entering_custom_speed_applies_it_live(self):
        self.dialog.spin_speed.lineEdit().setText("100x")
        self.dialog.spin_speed.interpretText()
        self.assertEqual(self.dialog.spin_speed.value(), 100.0)
        self.assertEqual(self.dialog.anim_speed, 100.0)
        self.assertEqual(self.parent.speeds[-1], 100.0)

    def test_custom_fractional_speed_is_supported(self):
        self.dialog.spin_speed.setValue(0.125)
        self.assertEqual(self.parent.speeds[-1], 0.125)

    def test_old_saved_speed_does_not_override_the_current_manager(self):
        with tempfile.TemporaryDirectory() as folder:
            self.dialog.prefs_path = os.path.join(folder, "prefs.json")
            with open(self.dialog.prefs_path, "w") as stream:
                json.dump({"anim_speed": 100.0}, stream)
            self.dialog._load_prefs()
        self.assertEqual(self.dialog.anim_speed, 1.0)
        self.assertEqual(self.dialog.spin_speed.value(), 1.0)

    def test_reopened_dialog_displays_the_current_custom_speed(self):
        with patch.object(DeformedShapeDialog, "_load_prefs"):
            reopened = DeformedShapeDialog(parent=self.parent, current_speed=100.0)
        try:
            self.assertEqual(reopened.spin_speed.value(), 100.0)
        finally:
            reopened.close()
            reopened.deleteLater()

    def test_small_scale_is_not_rounded_to_zero(self):
        self.dialog.spin_scale.setValue(0.000001)
        self.dialog._do_apply()
        self.assertEqual(self.parent.calls[-1][1], 0.000001)

    def test_large_manual_scale_is_applied_as_entered(self):
        self.dialog.spin_scale.setValue(2000000.0)
        self.dialog._do_apply()
        self.assertEqual(self.parent.calls[-1][1], 2000000.0)

    def test_normalize_uses_active_canvas_and_cancels_pending_apply(self):
        self.dialog.spin_scale.setValue(100.0)
        self.assertTrue(self.dialog._apply_timer.isActive())
        self.dialog.on_normalize()
        self.assertFalse(self.dialog._apply_timer.isActive())
        self.assertEqual(self.parent.calls[-1][1], self.dialog.spin_scale.value())
        self.assertAlmostEqual(self.parent.calls[-1][1], 0.0247291990219501, places=8)
        self.assertEqual(self.parent.refreshes, 1)

    def make_history_dialog(self, **kwargs):
        self.dialog.close()
        self.dialog.deleteLater()
        with patch.object(DeformedShapeDialog, '_load_prefs'):
            self.dialog = DeformedShapeDialog(parent=self.parent, is_active=True,
                                               ltha_mode=True, ltha_n_steps=101,
                                               ltha_dt=0.01, **kwargs)

    def test_start_end_set_the_loop_without_frame_preparation(self):
        self.make_history_dialog()
        self.dialog.spin_start.setValue(0.2)
        self.dialog.spin_end.setValue(0.7)
        self.assertEqual(self.parent.ranges[-1], (0.2, 0.7))
        self.dialog.btn_animate.click()
        self.assertEqual(self.parent.ranges[-1], (0.2, 0.7))
        self.assertEqual(self.parent.playback[-1], True)
        self.assertFalse(any('Pre-Animate' in button.text()
                             for button in self.dialog.findChildren(QPushButton)))

    def test_reopened_dialog_preserves_selected_range(self):
        self.parent.canvas.animation_manager = SimpleNamespace(ltha_playback_start=20,
                                                               ltha_playback_end=70)
        self.make_history_dialog()
        self.assertEqual(self.dialog.spin_start.value(), 0.2)
        self.assertEqual(self.dialog.spin_end.value(), 0.7)

    def test_invalid_range_keeps_pause_available(self):
        self.make_history_dialog()
        self.dialog.btn_animate.click()
        self.dialog.spin_end.setValue(0.3)
        self.dialog.spin_start.setValue(0.8)
        self.assertTrue(self.dialog.btn_animate.isEnabled())
        self.dialog.btn_animate.click()
        self.assertEqual(self.parent.playback[-1], False)
        self.assertFalse(self.dialog.btn_animate.isEnabled())
        self.dialog.spin_end.setValue(0.9)
        self.assertTrue(self.dialog.btn_animate.isEnabled())

if __name__ == "__main__":
    unittest.main()
