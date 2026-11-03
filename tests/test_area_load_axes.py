"""Drawn area-load directions must agree with native shell load conversion."""

from pathlib import Path
import sys
from types import SimpleNamespace
import unittest

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.graphic.area_load_axes import area_load_axes, area_load_components
from core.loads import AreaGravityLoad, AreaUniformLoad

solver_path = str(ROOT / "core" / "solver" / "linear_static")
original_path = sys.path[:]
try:
    sys.path.insert(0, solver_path)
    from core.solver.linear_static.shell_element import (
        ShellElement, area_load_nodal_forces, local_axes)
finally:
    sys.path[:] = original_path

def geometries():
    horizontal = np.array([[0., 0., 0.], [2., 0., 0.],
                           [2., 1., 0.], [0., 1., 0.]])
    vertical = np.array([[0., 0., 0.], [2., 0., 0.],
                         [2., 0., 1.], [0., 0., 1.]])
    inclined = horizontal.copy()
    inclined[:, 2] = inclined[:, 0] * .4 + inclined[:, 1] * .7
    for name, points in (("horizontal", horizontal), ("vertical", vertical),
                         ("inclined", inclined)):
        yield name, points
        yield name + " reversed", points[::-1]

def shell(points, angle):
    return ShellElement(1, [0, 1, 2, 3], points, 30.e9, .2, 25.e3,
                        {"shell_type": "Membrane", "tm": .2, "tb": .2,
                         "angle": angle, "mods": {}})

def arrow_vector(components):
    return sum((direction * magnitude for direction, magnitude in components),
               start=np.zeros(3))

class AreaLoadAxesTests(unittest.TestCase):
    def test_quad_axes_equal_native_solver_for_all_orientations_and_angles(self):
        for name, points in geometries():
            for angle in (0., 37., -90.):
                with self.subTest(plane=name, angle=angle):
                    expected = local_axes(points, angle)
                    actual = area_load_axes(points, SimpleNamespace(material_angle=angle))
                    np.testing.assert_array_equal(actual, expected)
                    np.testing.assert_array_equal(
                        area_load_axes(points, {"material_angle": angle}), expected)
                    np.testing.assert_array_equal(
                        area_load_axes(points, {"angle": angle}), expected)

    def test_uniform_arrows_match_actual_native_nodal_force_sums(self):
        for name, points in geometries():
            for angle in (0., 37.):
                element = shell(points, angle)
                section = SimpleNamespace(material_angle=angle)
                for direction in ("Gravity", "Global X", "Global Y", "Global Z",
                                  "Local 1", "Local 2", "Local 3"):
                    for pressure in (-7.25, 7.25):
                        with self.subTest(plane=name, angle=angle, direction=direction,
                                          pressure=pressure):
                            load = AreaUniformLoad(1, "Dead", "GLOBAL", direction, pressure)
                            drawn = area_load_components(load, points, section)
                            native = area_load_nodal_forces(element, {
                                "type": "area_uniform", "direction": direction,
                                "load": pressure})
                            self.assertEqual(len(drawn), 1)
                            self.assertEqual(drawn[0][1], abs(pressure))
                            self.assertAlmostEqual(np.linalg.norm(drawn[0][0]), 1.)
                            np.testing.assert_allclose(arrow_vector(drawn) * element.area,
                                                       native.sum(axis=0), rtol=2.e-13,
                                                       atol=5.e-11)

    def test_global_and_local_gravity_components_match_native_force_sums(self):
        for name, points in geometries():
            for angle in (0., 37.):
                element = shell(points, angle)
                section = SimpleNamespace(material_angle=angle)
                for coord in ("GLOBAL", "Local"):
                    for values in ((-.2, .5, -1.), (0., 0., 1.), (1., -2., 0.)):
                        with self.subTest(plane=name, angle=angle, coord=coord, values=values):
                            load = AreaGravityLoad(1, "Dead", coord, *values)
                            drawn = area_load_components(load, points, section)
                            record = {"type": "area_gravity", "coord": coord,
                                      **dict(zip(("gx", "gy", "gz"), values))}
                            native = area_load_nodal_forces(element, record)
                            self.assertEqual(len(drawn), sum(value != 0. for value in values))
                            np.testing.assert_allclose(arrow_vector(drawn) * element.weight,
                                                       native.sum(axis=0), rtol=2.e-13,
                                                       atol=5.e-11)
                            np.testing.assert_allclose(
                                arrow_vector(area_load_components(record, points, section)),
                                arrow_vector(drawn), rtol=0., atol=0.)

    def test_triangle_and_polygon_fallback_respects_winding_and_material_angle(self):
        triangle = np.array([[0., 0., 0.], [2., 0., 0.], [0., 1., 0.]])
        np.testing.assert_array_equal(area_load_axes(triangle), np.eye(3))
        np.testing.assert_array_equal(area_load_axes(triangle[::-1])[2], [0., 0., -1.])
        polygon = np.array([[0., 0., 0.], [1., 0., 0.], [2., 0., 0.],
                            [2., 1., 0.], [0., 1., 0.]])
        np.testing.assert_array_equal(area_load_axes(polygon), np.eye(3))
        np.testing.assert_allclose(area_load_axes(triangle, {"material_angle": 90.})[0],
                                   [0., 1., 0.], atol=1.e-15)

    def test_zero_invalid_and_nonfinite_inputs(self):
        points = next(geometries())[1]
        self.assertEqual(area_load_components(AreaUniformLoad(1, "Dead"), points), [])
        self.assertEqual(area_load_components(AreaGravityLoad(1, "Dead"), points), [])
        for invalid in (np.zeros((4, 3)), [[0., 0.]], np.full((4, 3), np.nan)):
            with self.subTest(points=invalid), self.assertRaises(ValueError):
                area_load_axes(invalid)
        with self.assertRaises(ValueError):
            area_load_axes(points, {"material_angle": np.inf})
        with self.assertRaises(ValueError):
            area_load_components(AreaUniformLoad(1, "Dead", load_direction="Local 4",
                                                uniform_load=1.), points)
        with self.assertRaises(ValueError):
            area_load_components(AreaGravityLoad(1, "Dead", gx=np.nan), points)

if __name__ == "__main__":
    unittest.main()
