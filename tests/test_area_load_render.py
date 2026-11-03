"""Area load rendering preserves assignments, distinct values and other overlays."""

import ast
import copy
from dataclasses import asdict
import os
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

import numpy as np

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt6.QtCore import QObject, QEventLoop, QTimer
from PyQt6.QtWidgets import QApplication

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.graphic.area_load_render import AreaLoadDisplayMixin
from app.graphic.load_label_layout import label_screen_bounds, layout_load_labels
from core.loads import AreaUniformLoad

original_path = sys.path[:]
try:
    sys.path.insert(0, str(ROOT / "core" / "solver" / "linear_static"))
    from core.solver.linear_static.shell_element import ShellElement, area_load_nodal_forces
finally:
    sys.path[:] = original_path

def label(value=3., owner_type="node", height=.2, position=(0., 0., 0.)):
    return dict(owner_id=99, owner_type=owner_type, pos_3d=list(position),
                text=f"{value:.2f}", val=value, color=[.1, .2, .3, 1.],
                v_right=[1., 0., 0.], v_up=[0., 0., 1.], align="center",
                text_height=height)

def mesh(n=8):
    section = SimpleNamespace(material_angle=0., membrane_thickness=.2)
    nodes = {}
    for row in range(n + 1):
        for col in range(n + 1):
            nid = row * (n + 1) + col + 1
            nodes[nid] = SimpleNamespace(id=nid, x=-4. + col * 8. / n,
                                         y=-4. + row * 8. / n, z=0.)
    areas = {}
    loads = []
    for row in range(n):
        for col in range(n):
            aid = row * n + col + 1
            first = row * (n + 1) + col + 1
            ids = (first, first + 1, first + n + 2, first + n + 1)
            areas[aid] = SimpleNamespace(id=aid, nodes=[nodes[k] for k in ids],
                                         section=section, insertion_offset=0.)
            loads.append(AreaUniformLoad(aid, "Dead", uniform_load=5.))
    return SimpleNamespace(area_elements=areas, loads=loads, has_results=False)

def snapshot(model):
    return ([asdict(load) for load in model.loads],
            [(area.id, [(n.id, n.x, n.y, n.z) for n in area.nodes],
              area.section.material_angle, area.insertion_offset)
             for area in model.area_elements.values()])

def native_force_sum(model):
    result = np.zeros(3)
    elements = {}
    for aid, area in model.area_elements.items():
        points = np.array([[n.x, n.y, n.z] for n in area.nodes])
        elements[aid] = ShellElement(aid, [0, 1, 2, 3], points, 30.e9, .2, 25.e3,
                                    {"shell_type": "Membrane", "tm": .2, "tb": .2,
                                     "angle": area.section.material_angle, "mods": {}})
    for load in model.loads:
        result += area_load_nodal_forces(elements[load.area_id], {
            "type": "area_uniform", "direction": load.load_direction,
            "load": load.uniform_load}).sum(axis=0)
    return result

class Matrix:
    def __init__(self, values):
        self.values = np.asarray(values)

    def __mul__(self, other):
        return Matrix(self.values @ other.values)

    def data(self):
        return self.values.ravel(order="F").tolist()

ORTHOGRAPHIC = np.array([[.18, 0., 0., 0.], [0., .12, .2, 0.],
                         [0., 0., .05, 0.], [0., 0., 0., 1.]])

def perspective(width=800, height=600):
    eye = np.array([9., -11., 9.])
    forward = -eye / np.linalg.norm(eye)
    side = np.cross(forward, [0., 0., 1.]); side /= np.linalg.norm(side)
    up = np.cross(side, forward)
    view = np.eye(4)
    view[:3, :3] = np.array([side, up, -forward])
    view[:3, 3] = -view[:3, :3] @ eye
    near, far = .1, 100.
    factor = 1. / np.tan(np.radians(45.) / 2.)
    projection = np.array([[factor * height / width, 0., 0., 0.],
                           [0., factor, 0., 0.],
                           [0., 0., (far + near) / (near - far),
                            2. * far * near / (near - far)],
                           [0., 0., -1., 0.]])
    return projection @ view

tree = ast.parse((ROOT / "app/canvas.py").read_text(encoding="utf-8-sig"))
owner = next(node for node in tree.body if isinstance(node, ast.ClassDef)
             and node.name == "MCanvas3D")
upload = next(node for node in owner.body if isinstance(node, ast.FunctionDef)
              and node.name == "_upload_load_labels_to_gpu")
namespace = {"np": np}
exec(compile(ast.fix_missing_locations(ast.Module(body=[upload], type_ignores=[])),
             "actual load label upload", "exec"), namespace)

class FakeCanvas(AreaLoadDisplayMixin, QObject):
    _upload_load_labels_to_gpu = namespace["_upload_load_labels_to_gpu"]

    def __init__(self, model, mvp=ORTHOGRAPHIC, mode="smart"):
        QObject.__init__(self)
        self.current_model = model
        self.selected_area_ids = list(model.area_elements)
        self.display_config = {"area_load_display_mode": mode,
                               "area_load_arrow_spacing": 55., "load_text_scale": 1.}
        self.show_loads = True
        self.load_type_filter = "both"
        self.visible_load_patterns = []
        self.view_extruded = False
        self.reaction_diagram_active = False
        self.mvp = np.asarray(mvp).copy()
        self.load_labels = []
        self.force_labels = []
        self.grid_labels = []
        for name in ("_pending_load_fill_verts", "_pending_load_fill_colors",
                     "_pending_load_fill_faces", "_pending_load_line_pos",
                     "_pending_load_line_colors"):
            setattr(self, name, [])
        self._upload_loads_to_vbo = Mock()
        self.update = Mock()
        self.makeCurrent = Mock()
        self.text_builder = SimpleNamespace(build_text_geometry=self.capture_text)
        self.vbo_manager = SimpleNamespace(upload_text_geometry=Mock())
        self.uploaded_labels = []

    def capture_text(self, labels, default_text_height):
        self.uploaded_labels = copy.deepcopy(labels)
        return (np.zeros((0, 3)), np.zeros((0, 2)), np.zeros((0, 4)), np.zeros(0))

    def width(self): return 800
    def height(self): return 600
    def viewMatrix(self): return Matrix(np.eye(4))
    def projectionMatrix(self, **kwargs): return Matrix(self.mvp)
    def _theme_ink_rgb(self): return (.1, .2, .3)
    def _get_visibility_state(self, *args): return 2
    def _vo_state(self, *args): return 2

    def _fan_triangulate(self, points):
        return [(points[0], points[i], points[i + 1]) for i in range(1, len(points) - 1)]

    def _area_load_sample_points(self, points, centroid, n):
        return [centroid] + [(points[i] + points[(i + 1) % 4] + 2 * centroid) / 4.
                             for i in range(n - 1)]

def boxes_overlap(a, b):
    return bool((np.minimum(a[2:], b[2:]) - np.maximum(a[:2], b[:2]) > 1.e-7).all())

class AreaLoadRenderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.application = QApplication.instance() or QApplication([])

    def test_divided_load_groups_and_tiny_child_edit_then_restoration(self):
        model = mesh()
        canvas = FakeCanvas(model)
        canvas._draw_area_loads(model)
        self.assertEqual(len(canvas.load_labels), 1)
        self.assertEqual(canvas.load_labels[0]["group_count"], 64)
        self.assertEqual(set(canvas.load_labels[0]["owner_ids"]), set(model.area_elements))
        model.loads[27].uniform_load = 5.000001
        canvas.load_labels.clear()
        canvas._draw_area_loads(model)
        self.assertEqual(len(canvas.load_labels), 2)
        self.assertEqual({item["val"] for item in canvas.load_labels}, {5., 5.000001})
        self.assertEqual(sorted(item["group_count"] for item in canvas.load_labels), [1, 63])
        model.loads[27].uniform_load = 5.
        canvas.load_labels.clear()
        canvas._draw_area_loads(model)
        self.assertEqual(len(canvas.load_labels), 1)

    def test_extra_load_on_one_child_preserves_the_complete_stack(self):
        model = mesh()
        model.loads.append(AreaUniformLoad(28, "Dead", load_direction="Global X", uniform_load=2.))
        canvas = FakeCanvas(model)
        canvas._draw_area_loads(model)
        self.assertEqual(len(canvas.load_labels), 3)
        self.assertEqual(sorted(item["group_count"] for item in canvas.load_labels), [1, 1, 63])
        self.assertEqual(sorted(item["val"] for item in canvas.load_labels), [2., 5., 5.])

    def test_every_area_and_hidden_modes(self):
        model = mesh()
        for mode, count in (("every_area", 64), ("hidden", 0)):
            with self.subTest(mode=mode):
                canvas = FakeCanvas(model, mode=mode)
                canvas._draw_area_loads(model)
                self.assertEqual(len(canvas.load_labels), count)
                self.assertGreater(len(canvas._pending_load_line_pos), 0)

    def test_rendering_does_not_modify_model_or_native_force_resultant(self):
        model = mesh()
        model.loads[27].uniform_load = 7.
        before = snapshot(model)
        forces = native_force_sum(model)
        canvas = FakeCanvas(model)
        canvas._draw_area_loads(model)
        canvas._area_load_view_time = 0.
        changed = canvas.mvp.copy(); changed[0, 3] += .02
        canvas._refresh_area_load_view(changed, 800, 600)
        self.assertEqual(snapshot(model), before)
        np.testing.assert_array_equal(native_force_sum(model), forces)

    def test_local_uniform_arrow_shafts_follow_solver_axes(self):
        model = mesh(1)
        area = model.area_elements[1]
        area.section.material_angle = 37.
        points = np.array([[n.x, n.y, n.z] for n in area.nodes])
        native = ShellElement(1, [0, 1, 2, 3], points, 30.e9, .2, 25.e3,
                              {"shell_type": "Membrane", "tm": .2, "tb": .2,
                               "angle": 37., "mods": {}})
        for direction, index in (("Local 1", 0), ("Local 3", 2)):
            with self.subTest(direction=direction):
                model.loads[0].load_direction = direction
                model.loads[0].uniform_load = -7.
                canvas = FakeCanvas(model, mode="every_area")
                canvas._draw_area_loads(model)
                tail, tip = np.array(canvas._pending_load_line_pos[:2])
                shaft = (tip - tail) / np.linalg.norm(tip - tail)
                np.testing.assert_allclose(shaft, -native.R[index], atol=1.e-14)

    def test_input_text_scaling_keeps_force_grid_and_reaction_sizes(self):
        canvas = FakeCanvas(mesh(1))
        canvas.load_labels = [label(height=.2), label(owner_type="area", height=.22)]
        canvas.force_labels = [label(owner_type="force", height=1.5)]
        canvas.grid_labels = [label(owner_type="grid", height=.4)]
        originals = copy.deepcopy((canvas.load_labels, canvas.force_labels, canvas.grid_labels))
        canvas.display_config["load_text_scale"] = 1.5
        canvas._upload_load_labels_to_gpu()
        np.testing.assert_allclose([item["text_height"] for item in canvas.uploaded_labels],
                                   [.3, .33, 1.5, .4])
        self.assertEqual((canvas.load_labels, canvas.force_labels, canvas.grid_labels), originals)
        canvas.reaction_diagram_active = True
        canvas._upload_load_labels_to_gpu()
        self.assertEqual([item["text_height"] for item in canvas.uploaded_labels], [.2, .22, 1.5, .4])

    def test_exception_labels_do_not_overlap_in_orthographic_or_perspective_view(self):
        model = mesh()
        model.loads[27].uniform_load = 7.
        model.loads[28].uniform_load = 9.
        for matrix in (ORTHOGRAPHIC, perspective()):
            with self.subTest(projection=matrix):
                canvas = FakeCanvas(model, matrix)
                canvas._draw_area_loads(model)
                self.assertEqual(len(canvas.load_labels), 3)
                boxes = [label_screen_bounds(item, matrix, 800, 600) for item in canvas.load_labels]
                self.assertTrue(all(box is not None for box in boxes))
                for i, box in enumerate(boxes):
                    self.assertTrue((box[:2] >= 4).all())
                    self.assertTrue((box[2:] <= [796, 596]).all())
                    for other in boxes[i + 1:]:
                        self.assertFalse(boxes_overlap(box, other))

    def test_camera_and_selection_refresh_preserve_nonarea_prefixes(self):
        model = mesh()
        canvas = FakeCanvas(model)
        canvas.load_labels = [label()]
        canvas._pending_load_fill_verts = [[9., 9., 9.], [10., 9., 9.], [9., 10., 9.]]
        canvas._pending_load_fill_colors = [[1., 0., 0., 1.]] * 3
        canvas._pending_load_fill_faces = [[0, 1, 2]]
        canvas._pending_load_line_pos = [[9., 9., 9.], [10., 10., 10.]]
        canvas._pending_load_line_colors = [[1., 0., 0., 1.]] * 2
        names = ("_pending_load_fill_verts", "_pending_load_fill_colors",
                 "_pending_load_fill_faces", "_pending_load_line_pos", "_pending_load_line_colors")
        originals = {name: copy.deepcopy(getattr(canvas, name)) for name in names}
        original_label = copy.deepcopy(canvas.load_labels[0])
        canvas._draw_area_loads(model)
        changed = canvas.mvp.copy(); changed[0, 3] += .05
        canvas._area_load_view_time = 0.
        canvas._refresh_area_load_view(changed, 800, 600)
        for selected, count in (([28], 2), ([], 1), (list(model.area_elements), 2)):
            canvas.selected_area_ids = selected
            canvas._refresh_area_load_view(changed, 800, 600)
            self.assertEqual(len(canvas.load_labels), count)
            self.assertEqual(canvas.load_labels[0], original_label)
            for name, values in originals.items():
                np.testing.assert_array_equal(getattr(canvas, name)[:len(values)], values)
        self.assertEqual(canvas._upload_loads_to_vbo.call_count, 4)

    def test_rapid_camera_change_keeps_layout_without_scheduling_a_rebuild(self):
        canvas = FakeCanvas(mesh())
        canvas._draw_area_loads(canvas.current_model)
        changed = canvas.mvp.copy(); changed[0, 3] += .01
        canvas._refresh_area_load_view(changed, 800, 600)
        cache = canvas._load_view_geometry
        canvas._refresh_area_load_view(changed, 800, 600)
        self.assertFalse(hasattr(canvas, '_area_load_view_timer'))
        self.assertIs(canvas._load_view_geometry, cache)
        canvas._upload_loads_to_vbo.assert_called_once()
        canvas.vbo_manager.upload_text_geometry.assert_not_called()

class LoadLabelLayoutTests(unittest.TestCase):
    def test_layout_keeps_values_and_sizes_while_avoiding_an_existing_label(self):
        annotations = [dict(label(value=7.), group_count=1),
                       dict(label(value=5.), group_count=63)]
        before = copy.deepcopy(annotations)
        obstacle = label(value=3.)
        placed, leaders = layout_load_labels(annotations, [obstacle], ORTHOGRAPHIC, 800, 600)
        self.assertEqual(annotations, before)
        self.assertEqual([item["val"] for item in placed], [7., 5.])
        self.assertEqual([item["text_height"] for item in placed], [.2, .2])
        self.assertGreater(len(leaders), 0)
        boxes = [label_screen_bounds(item, ORTHOGRAPHIC, 800, 600)
                 for item in [obstacle, *placed]]
        self.assertTrue(all(box is not None for box in boxes))
        for i, box in enumerate(boxes):
            for other in boxes[i + 1:]:
                self.assertFalse(boxes_overlap(box, other))

    def test_insufficient_room_retains_every_value_at_the_requested_size(self):
        annotations = [dict(label(value=float(i), height=2.), owner_id=i,
                            text=f"Distinct load value {i}: 12345.00 kN/m²")
                       for i in range(36)]
        before = copy.deepcopy(annotations)
        placed, _ = layout_load_labels(annotations, [], ORTHOGRAPHIC, 100, 60, 1.5)
        self.assertEqual(annotations, before)
        self.assertEqual(len(placed), 36)
        self.assertEqual([item["val"] for item in placed], list(map(float, range(36))))
        self.assertTrue(all(item["text_height"] == 2. for item in placed))

    def test_singular_projection_keeps_annotations(self):
        annotations = [label()]
        placed, leaders = layout_load_labels(annotations, [], np.zeros((4, 4)), 800, 600)
        self.assertEqual(placed, annotations)
        self.assertEqual(leaders, [])

if __name__ == "__main__":
    unittest.main()
