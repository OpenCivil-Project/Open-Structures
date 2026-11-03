"""Headless regression checks for Graphics Options apply and transparency.

Compile the actual window methods and dialog classes without importing the app
entry point or creating an OpenGL canvas. Preference writes stay in a mock.
"""

import ast
import json
import os
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import mock_open, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6 import QtWidgets
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor

ROOT = Path(__file__).resolve().parents[1]

def _compile_nodes(path, select, namespace):
    tree = ast.parse(path.read_text(encoding="utf-8-sig"))
    module = ast.fix_missing_locations(ast.Module(
        body=select(tree), type_ignores=[]))
    exec(compile(module, str(path), "exec"), namespace)
    return namespace

class _Application:
    @classmethod
    def instance(cls):
        return cls

    @classmethod
    def setProperty(cls, *args):
        pass

def _main_methods(tree):
    owner = next(n for n in tree.body
                 if isinstance(n, ast.ClassDef) and n.name == "MainWindow")
    methods = [n for n in owner.body if isinstance(n, ast.FunctionDef)
               and n.name in {"update_graphics_settings", "_apply_crosshair_to_canvases"}]
    init = next(n for n in owner.body if isinstance(n, ast.FunctionDef) and n.name == "__init__")
    start = next(i for i, n in enumerate(init.body) if isinstance(n, ast.Assign)
                 and any(isinstance(t, ast.Attribute) and t.attr == "graphics_settings"
                         for t in n.targets))
    stop = next(i for i, n in enumerate(init.body) if isinstance(n, ast.Expr)
                and isinstance(n.value, ast.Call) and isinstance(n.value.func, ast.Attribute)
                and n.value.func.attr == "setWindowTitle")
    methods.append(ast.FunctionDef(name="_initialize_graphics_settings", args=init.args,
                                  body=init.body[start:stop], decorator_list=[]))
    return methods

_MAIN = _compile_nodes(ROOT / "app" / "main.py", _main_methods, {
    "QApplication": _Application, "QColor": QColor,
    "apply_windows_titlebar_theme": lambda window: None,
    "_VIEW_SETTING_KEYS": ("view_extruded",),
    "os": os, "CROSSHAIR_DEFAULTS": {},
})

class _Canvas:
    def __init__(self):
        self.refreshed_models = []
        self.repaint_count = 0
        self.crosshair = SimpleNamespace(apply_settings=lambda: None)

    def refresh_graphics_geometry(self, model):
        self.refreshed_models.append(model)

    def setBackgroundColor(self, color):
        self.background = color

    def update(self):
        self.repaint_count += 1

class _Window:
    update_graphics_settings = _MAIN["update_graphics_settings"]
    _apply_crosshair_to_canvases = _MAIN["_apply_crosshair_to_canvases"]
    _initialize_graphics_settings = _MAIN["_initialize_graphics_settings"]

    def __init__(self, with_second=True):
        self.graphics_settings = {
            "ui_theme": "Light", "background_color": (1., 1., 1., 1.),
            "msaa_level": 5, "antialias": True,
            "extrude_opacity": .35, "slab_opacity": .4,
            "edge_color": (0., 0., 0., 1.), "edge_opacity": .08, "show_edges": True,
            "shell_edge_color": (0., 0., 0., 1.),
            "node_size": 6, "node_color": (1., 0., 0., 1.),
            "hinge_color": (0., .47, .84, 1.), "hinge_shape": "Circle",
            "lighting_enabled": True, "light_specular": .25,
            "light_fresnel_intensity": .4, "snap_radius": 25,
            "view_extruded": True,
        }
        self._applied_graphics_settings = self.graphics_settings.copy()
        self.canvas = _Canvas()
        if with_second:
            self.canvas2 = _Canvas()
        self.model = object()
        self.status = SimpleNamespace(showMessage=lambda text: None)

class ApplyGraphicsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.application = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def apply(self, window, changes):
        sink = mock_open()
        with patch("builtins.open", sink):
            window.update_graphics_settings(changes)
        self.assertEqual(sink.call_count, 1)
        return json.loads("".join(call.args[0] for call in sink().write.call_args_list))

    def test_baked_appearance_refreshes_both_canvases(self):
        changes = {
            "extrude_opacity": .8, "slab_opacity": .7, "show_edges": False,
            "edge_color": (.2, .3, .4, 1.), "node_size": 10,
            "node_color": (0., 1., 0., 1.), "hinge_color": (1., 0., 0., 1.),
            "hinge_shape": "Diamond", "shell_edge_color": (.4, .3, .2, 1.),
        }
        for key, value in changes.items():
            with self.subTest(setting=key):
                window = _Window()
                self.apply(window, {key: value})
                for canvas in (window.canvas, window.canvas2):
                    self.assertEqual(canvas.refreshed_models, [window.model])
                    self.assertEqual(canvas.repaint_count, 1)
                    self.assertEqual(canvas.display_config[key], value)

    def test_lighting_change_repaints_without_geometry_rebuild(self):
        window = _Window()
        self.apply(window, {"light_specular": .9, "light_fresnel_intensity": .8})
        for canvas in (window.canvas, window.canvas2):
            self.assertEqual(canvas.refreshed_models, [])
            self.assertEqual(canvas.repaint_count, 1)
            self.assertEqual(canvas.display_config["light_fresnel_intensity"], .8)

    def test_load_display_preferences_persist_and_refresh_both_canvases(self):
        for key, value in (("area_load_display_mode", "every_area"),
                           ("frame_load_display_mode", "every_member"),
                           ("load_text_scale", 1.4),
                           ("area_load_arrow_spacing", 80.0)):
            with self.subTest(setting=key):
                window = _Window()
                saved = self.apply(window, {key: value})
                self.assertEqual(saved[key], value)
                for canvas in (window.canvas, window.canvas2):
                    self.assertEqual(canvas.refreshed_models, [window.model])
                    self.assertEqual(canvas.display_config[key], value)

    def test_implicit_load_defaults_do_not_trigger_geometry_refresh(self):
        window = _Window()
        self.apply(window, {"area_load_display_mode": "smart", "load_text_scale": 1.0,
                            "area_load_arrow_spacing": 55.0, "frame_load_display_mode": "smart"})
        for canvas in (window.canvas, window.canvas2):
            self.assertEqual(canvas.refreshed_models, [])

    def test_mutated_shared_settings_refresh_both_canvases(self):
        window = _Window()
        window.graphics_settings["extrude_opacity"] = .8
        self.apply(window, window.graphics_settings)
        for canvas in (window.canvas, window.canvas2):
            self.assertEqual(canvas.refreshed_models, [window.model])
            self.assertEqual(canvas.repaint_count, 1)
            self.assertEqual(canvas.display_config["extrude_opacity"], .8)
        self.assertEqual(window._applied_graphics_settings["extrude_opacity"], .8)
        self.apply(window, window.graphics_settings)
        for canvas in (window.canvas, window.canvas2):
            self.assertEqual(canvas.refreshed_models, [window.model])
            self.assertEqual(canvas.repaint_count, 2)

    def test_unchanged_shared_settings_do_not_rebuild(self):
        window = _Window()
        self.apply(window, window.graphics_settings)
        for canvas in (window.canvas, window.canvas2):
            self.assertEqual(canvas.refreshed_models, [])
            self.assertEqual(canvas.repaint_count, 1)

    def test_shared_lighting_changes_do_not_rebuild(self):
        window = _Window()
        window.graphics_settings["light_specular"] = .9
        self.apply(window, window.graphics_settings)
        for canvas in (window.canvas, window.canvas2):
            self.assertEqual(canvas.refreshed_models, [])
        self.assertEqual(window._applied_graphics_settings["light_specular"], .9)

    def test_actual_dialog_lighting_apply_ignores_default_color_round_trip(self):
        window = _Window()
        dialog = _DIALOG["GraphicsOptionsDialog"](current_settings=window.graphics_settings)
        self.addCleanup(dialog.deleteLater)
        dialog.sl_light_specular.setValue(90)
        settings = dialog.get_settings()
        self.assertNotEqual(settings["hinge_color"], window.graphics_settings["hinge_color"])
        self.apply(window, settings)
        for canvas in (window.canvas, window.canvas2):
            self.assertEqual(canvas.refreshed_models, [])
            self.assertFalse(getattr(canvas, "_needs_hinge_refresh", False))
            self.assertEqual(canvas.repaint_count, 1)
        self.assertEqual(window.graphics_settings["light_specular"], .9)

    def test_fresh_startup_lighting_apply_ignores_implicit_appearance_defaults(self):
        window = _Window()
        with patch("os.path.exists", return_value=False):
            window._initialize_graphics_settings()
        for key in ("hinge_color", "hinge_shape", "shell_edge_color"):
            self.assertNotIn(key, window._applied_graphics_settings)
        dialog = _DIALOG["GraphicsOptionsDialog"](current_settings=window.graphics_settings)
        self.addCleanup(dialog.deleteLater)
        dialog.chk_lighting.setChecked(True)
        dialog.sl_light_specular.setValue(90)
        self.apply(window, dialog.get_settings())
        for canvas in (window.canvas, window.canvas2):
            self.assertEqual(canvas.refreshed_models, [])
            self.assertFalse(getattr(canvas, "_needs_hinge_refresh", False))
            self.assertEqual(canvas.repaint_count, 1)

    def test_implicit_shell_edge_color_tracks_its_respective_edge_color(self):
        window = _Window()
        window.graphics_settings.pop("shell_edge_color")
        window.graphics_settings["edge_color"] = (.2, .3, .4, 1.)
        window._applied_graphics_settings = window.graphics_settings.copy()
        self.apply(window, {"shell_edge_color": (.2, .3, .4, 1.)})
        self.assertEqual(window.canvas.refreshed_models, [])
        window.graphics_settings.pop("shell_edge_color")
        window._applied_graphics_settings = window.graphics_settings.copy()
        self.apply(window, {"edge_color": (1., 0., 0., 1.)})
        self.assertEqual(window.canvas.refreshed_models, [window.model])

    def test_applied_snapshot_is_initialized_after_saved_preferences(self):
        window = _Window()
        saved = {"extrude_opacity": .72, "msaa_level": 0,
                 "node_color": [.4, .5, .6, 1.]}
        with patch("os.path.exists", return_value=True), patch(
                "builtins.open", mock_open(read_data=json.dumps(saved))):
            window._initialize_graphics_settings()
        self.assertEqual(window._applied_graphics_settings, window.graphics_settings)
        self.assertIsNot(window._applied_graphics_settings, window.graphics_settings)
        self.assertEqual(window._applied_graphics_settings["extrude_opacity"], .72)
        self.assertFalse(window._applied_graphics_settings["antialias"])
        self.assertEqual(window._applied_graphics_settings["node_color"], (.4, .5, .6, 1.))
        window.graphics_settings["extrude_opacity"] = .2
        self.assertEqual(window._applied_graphics_settings["extrude_opacity"], .72)

    def test_missing_applied_snapshot_uses_current_values_then_records_apply(self):
        window = _Window()
        del window._applied_graphics_settings
        self.apply(window, {"extrude_opacity": .8})
        self.assertEqual(window.canvas.refreshed_models, [window.model])
        self.assertEqual(window._applied_graphics_settings["extrude_opacity"], .8)

    def test_hidden_edge_opacity_repaints_without_geometry_rebuild(self):
        window = _Window()
        self.apply(window, {"edge_opacity": .5})
        for canvas in (window.canvas, window.canvas2):
            self.assertEqual(canvas.refreshed_models, [])
            self.assertEqual(canvas.repaint_count, 1)
            self.assertEqual(canvas.display_config["edge_opacity"], .5)

    def test_partial_lighting_apply_preserves_antialiasing_preferences(self):
        window = _Window()
        window.graphics_settings.update(msaa_level=0, antialias=False)
        saved = self.apply(window, {"light_specular": .9})
        self.assertEqual(window.graphics_settings["msaa_level"], 0)
        self.assertFalse(window.graphics_settings["antialias"])
        self.assertEqual(saved["msaa_level"], 0)
        self.assertFalse(saved["antialias"])

    def test_unchanged_colors_do_not_refresh_for_list_tuple_conversion(self):
        window = _Window()
        self.apply(window, {"edge_color": [0., 0., 0., 1.]})
        self.assertEqual(window.canvas.refreshed_models, [])

    def test_partial_apply_preserves_preferences_and_saves_adjusted_theme(self):
        window = _Window()
        saved = self.apply(window, {"ui_theme": "Dark"})
        self.assertEqual(saved["slab_opacity"], .4)
        self.assertEqual(saved["snap_radius"], 25)
        self.assertNotIn("view_extruded", saved)
        self.assertEqual(saved["background_color"], [30 / 255., 30 / 255., 30 / 255., 1.])
        self.assertEqual(window.canvas.refreshed_models, [window.model])

    def test_primary_canvas_only_and_no_model_still_repaints(self):
        window = _Window(with_second=False)
        window.model = None
        self.apply(window, {"extrude_opacity": .7})
        self.assertEqual(window.canvas.refreshed_models, [])
        self.assertEqual(window.canvas.repaint_count, 1)
        self.assertEqual(window._applied_graphics_settings["extrude_opacity"], .7)

class _CrosshairWidget(QtWidgets.QWidget):
    def __init__(self, settings, color_button, parent):
        super().__init__(parent)

    def get_settings(self):
        return {}

def _dialog_classes(tree):
    return [n for n in tree.body if isinstance(n, ast.ClassDef)
            and n.name in {"ColorButton", "GraphicsOptionsDialog"}]

_DIALOG = _compile_nodes(ROOT / "app" / "dialogs" / "graphics_dialog.py",
                        _dialog_classes, {
    **vars(QtWidgets), "Qt": Qt, "QColor": QColor,
    "apply_dialog_style": lambda dialog: None,
    "COLORS": {"text_secondary": "#666666"},
    "current_theme": lambda: "Light", "set_theme": lambda theme: None,
    "glass_strength": lambda: 50, "set_glass_strength": lambda value: None,
    "glass_transparency": lambda: 0, "set_glass_transparency": lambda value: None,
    "GLASS_MAX_TRANSPARENCY": 80, "blur_supported": lambda: False,
    "CrosshairSettingsWidget": _CrosshairWidget,
})

class GraphicsDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.application = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def setUp(self):
        self.dialog = _DIALOG["GraphicsOptionsDialog"](current_settings={
            "extrude_opacity": .35, "edge_opacity": .08,
            "lighting_enabled": True, "light_ambient": .29,
            "light_fresnel_intensity": .57,
        })
        self.addCleanup(self.dialog.deleteLater)

    def test_saved_opacity_displays_as_transparency_and_round_trips(self):
        self.assertEqual(self.dialog.sl_ext_op.value(), 65)
        self.assertEqual(self.dialog.sl_edge_op.value(), 92)
        settings = self.dialog.get_settings()
        self.assertAlmostEqual(settings["extrude_opacity"], .35)
        self.assertAlmostEqual(settings["edge_opacity"], .08)

    def test_load_defaults_and_modes(self):
        settings = self.dialog.get_settings()
        self.assertEqual(settings["area_load_display_mode"], "smart")
        self.assertEqual(settings["frame_load_display_mode"], "smart")
        self.assertEqual(settings["load_text_scale"], 1.0)
        self.assertEqual(settings["area_load_arrow_spacing"], 55.0)
        self.assertTrue(self.dialog.spin_area_load_arrow_spacing.isEnabled())
        for mode in ("every_area", "hidden", "smart"):
            self.dialog.combo_area_load_mode.setCurrentIndex(
                self.dialog.combo_area_load_mode.findData(mode))
            self.assertEqual(self.dialog.get_settings()["area_load_display_mode"], mode)
            self.assertTrue(self.dialog.spin_area_load_arrow_spacing.isEnabled())

    def test_frame_modes_and_shared_arrow_spacing(self):
        for area_mode in ("smart", "every_area", "hidden"):
            self.dialog.combo_area_load_mode.setCurrentIndex(
                self.dialog.combo_area_load_mode.findData(area_mode))
            for frame_mode in ("smart", "every_member", "hidden"):
                with self.subTest(area=area_mode, frame=frame_mode):
                    self.dialog.combo_frame_load_mode.setCurrentIndex(
                        self.dialog.combo_frame_load_mode.findData(frame_mode))
                    settings = self.dialog.get_settings()
                    self.assertEqual(settings["frame_load_display_mode"], frame_mode)
                    self.assertEqual(settings["area_load_display_mode"], area_mode)
                    self.assertEqual(self.dialog.spin_area_load_arrow_spacing.isEnabled(),
                                     area_mode != "every_area" or frame_mode != "every_member")

    def test_saved_load_size_and_spacing_round_trip(self):
        dialog = _DIALOG["GraphicsOptionsDialog"](current_settings={
            "area_load_display_mode": "every_area", "load_text_scale": 1.37,
            "area_load_arrow_spacing": 73.0, "frame_load_display_mode": "every_member"})
        self.addCleanup(dialog.deleteLater)
        self.assertEqual(dialog.spin_load_text_size.value(), 137)
        self.assertEqual(dialog.spin_area_load_arrow_spacing.value(), 73)
        self.assertEqual(dialog.get_settings()["area_load_display_mode"], "every_area")
        self.assertEqual(dialog.get_settings()["frame_load_display_mode"], "every_member")
        self.assertFalse(dialog.spin_area_load_arrow_spacing.isEnabled())
        self.assertAlmostEqual(dialog.get_settings()["load_text_scale"], 1.37)
        self.assertEqual(dialog.get_settings()["area_load_arrow_spacing"], 73.0)

    def test_transparency_endpoints_and_live_readouts(self):
        for slider, label, key in (
            (self.dialog.sl_ext_op, self.dialog.lbl_ext_op, "extrude_opacity"),
            (self.dialog.sl_edge_op, self.dialog.lbl_edge_op, "edge_opacity"),
        ):
            for transparency, opacity in ((0, 1.), (100, 0.), (40, .6)):
                with self.subTest(key=key, transparency=transparency):
                    slider.setValue(transparency)
                    self.assertEqual(label.text(), f"{transparency}%")
                    self.assertAlmostEqual(self.dialog.get_settings()[key], opacity)

    def test_saved_lighting_percentages_do_not_truncate_on_reopen(self):
        self.assertEqual(self.dialog.sl_light_ambient.value(), 29)
        self.assertEqual(self.dialog.sl_light_fresnel.value(), 57)
        settings = self.dialog.get_settings()
        self.assertAlmostEqual(settings["light_ambient"], .29)
        self.assertAlmostEqual(settings["light_fresnel_intensity"], .57)

    def test_lighting_values_and_readouts_reach_settings(self):
        self.dialog.sl_light_az.setValue(210)
        self.dialog.sl_light_el.setValue(15)
        self.dialog.sl_light_ambient.setValue(17)
        self.dialog.sl_light_diffuse.setValue(63)
        self.dialog.sl_light_specular.setValue(91)
        self.dialog.spin_light_shininess.setValue(128)
        self.dialog.sl_light_fresnel.setValue(72)
        self.dialog.spin_light_fresnel_power.setValue(5.5)
        settings = self.dialog.get_settings()
        expected = {"light_azimuth": 210., "light_elevation": 15.,
                    "light_ambient": .17, "light_diffuse": .63,
                    "light_specular": .91, "light_shininess": 128.,
                    "light_fresnel_intensity": .72, "light_fresnel_power": 5.5}
        for key, value in expected.items():
            self.assertAlmostEqual(settings[key], value)
        self.assertEqual(self.dialog.lbl_light_specular.text(), "91%")
        self.assertEqual(self.dialog.lbl_light_fresnel.text(), "72%")
        self.assertEqual(self.dialog.lbl_light_az.text(), "210°")
        self.dialog.chk_lighting.setChecked(False)
        self.assertFalse(self.dialog.sl_light_fresnel.isEnabled())
        self.dialog.chk_lighting.setChecked(True)
        self.assertTrue(self.dialog.sl_light_fresnel.isEnabled())

if __name__ == "__main__":
    unittest.main()
