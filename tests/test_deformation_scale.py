import copy
import math
import unittest
from types import SimpleNamespace

import numpy as np

from post.deformation_scale import compute_deformation_scale
from post.deflection import get_deflected_shape

def model(length=24.0):
    node_i = SimpleNamespace(id=1, x=0.0, y=0.0, z=0.0)
    node_j = SimpleNamespace(id=2, x=length, y=0.0, z=0.0)
    return SimpleNamespace(nodes={1: node_i, 2: node_j}, elements={
        1: SimpleNamespace(node_i=node_i, node_j=node_j)})

class DeformationScaleTests(unittest.TestCase):
    def test_large_ltha_displacement_can_be_scaled_below_one(self):
        scale = compute_deformation_scale(model(), {"2": [72.44882188957307, 0, 0, 0, 0, 0]})
        self.assertAlmostEqual(scale * 72.44882188957307, 2.4)
        self.assertLess(scale, 1.0)

    def test_small_displacement_is_magnified_and_uses_resultant(self):
        scale = compute_deformation_scale(model(), {"2": [0.003, 0.004, 0, 0, 0, 0]})
        self.assertAlmostEqual(scale, 480.0)

    def test_full_history_peak_wins_over_quiet_envelope_or_current_frame(self):
        history = {"2": np.array([[0, 0, 0, 0, 0, 0], [12, 16, 0, 0, 0, 0],
                                 [0.00001, 0, 0, 0, 0, 0]])}
        before = history["2"].copy()
        scale = compute_deformation_scale(model(), {"2": [0.00001, 0, 0]}, history=history)
        self.assertAlmostEqual(scale, 0.12)
        np.testing.assert_array_equal(before, history["2"])

    def test_envelope_still_contributes_when_saved_states_are_empty(self):
        self.assertAlmostEqual(compute_deformation_scale(model(), {"2": [24, 0, 0]},
                                                        saved_states=[{}]), 0.1)

    def test_all_saved_states_contribute_not_only_final_state(self):
        states = [{"displacements": {"2": [12, 0, 0, 0, 0, 0]}},
                  {"displacements": {"2": [0, 0, 0, 0, 0, 0]}}]
        before = copy.deepcopy(states)
        self.assertAlmostEqual(compute_deformation_scale(model(), {}, saved_states=states), 0.2)
        self.assertEqual(before, states)

    def test_rotation_only_member_bending_is_bounded(self):
        structure = model(6.0)
        dofs = {"1": [0, 0, 0, 0, 0, 2], "2": [0, 0, 0, 0, 0, -2]}
        scale = compute_deformation_scale(structure, dofs)
        curve = get_deflected_shape([0, 0, 0], [6, 0, 0], dofs["1"], dofs["2"],
                                    [1, 0, 0], [0, 1, 0], [0, 0, 1],
                                    scale=scale, num_points=1001)
        positions = np.array([entry[0] for entry in curve])
        undeformed = np.column_stack([np.linspace(0, 6, 1001), np.zeros((1001, 2))])
        self.assertLessEqual(np.linalg.norm(positions - undeformed, axis=1).max(), 0.6 + 1e-12)
        self.assertLess(scale, 1.0)

    def test_general_hermite_shapes_fit_normalized_bound(self):
        rng = np.random.default_rng(2026)
        for _ in range(30):
            dofs = {"1": rng.normal(size=6), "2": rng.normal(size=6)}
            scale = compute_deformation_scale(model(8.0), dofs)
            curve = get_deflected_shape([0, 0, 0], [8, 0, 0], dofs["1"], dofs["2"],
                                        [1, 0, 0], [0, 1, 0], [0, 0, 1],
                                        scale=scale, num_points=101)
            positions = np.array([entry[0] for entry in curve])
            undeformed = np.column_stack([np.linspace(0, 8, 101), np.zeros((101, 2))])
            self.assertLessEqual(np.linalg.norm(positions - undeformed, axis=1).max(), 0.8 + 1e-12)

    def test_mixed_axial_and_transverse_translation_can_exceed_endpoint_norm(self):
                                                                         
        ui = np.array([0.8 * 0.8, 0.896 * 0.6, 0.0])
        uj = np.array([0.2 * 0.8, 0.104 * 0.6, 0.0])
        ui /= np.linalg.norm(ui)
        uj /= np.linalg.norm(uj)
        dofs = {"1": np.r_[ui, [0, 0, 0]], "2": np.r_[uj, [0, 0, 0]]}
        scale = compute_deformation_scale(model(6.0), dofs)
        curve = get_deflected_shape([0, 0, 0], [6, 0, 0], dofs["1"], dofs["2"],
                                    [1, 0, 0], [0, 1, 0], [0, 0, 1],
                                    scale=scale, num_points=101)
        positions = np.array([entry[0] for entry in curve])
        undeformed = np.column_stack([np.linspace(0, 6, 101), np.zeros((101, 2))])
        self.assertLessEqual(np.linalg.norm(positions - undeformed, axis=1).max(), 0.6 + 1e-12)

    def test_rotational_history_peak_is_included(self):
        history = {"1": [[0, 0, 0, 0, 0, 3], [0, 0, 0, 0, 0, 0]]}
        scale = compute_deformation_scale(model(6.0), {}, history=history)
        self.assertAlmostEqual(scale, 0.6 / ((4 / 27) * 6 * 3))

    def test_unit_conversion_preserves_dimensionless_scale(self):
        dofs = {"1": [0.01, 0.02, -0.03, 0.1, 0.2, 0.3],
                "2": [0.02, -0.01, 0, -0.1, 0, 0.1]}
        millimetres = {key: [value * 1000 for value in row[:3]] + row[3:]
                       for key, row in dofs.items()}
        self.assertAlmostEqual(compute_deformation_scale(model(24), dofs),
                               compute_deformation_scale(model(24000), millimetres))

    def test_bad_components_do_not_hide_finite_motion(self):
        dofs = {"2": [math.nan, 4, math.inf, 0, 0, 0]}
        self.assertAlmostEqual(compute_deformation_scale(model(), dofs), 0.6)

    def test_empty_zero_malformed_and_degenerate_inputs_are_neutral(self):
        for dofs in ({}, None, {"1": [0] * 6}, {"1": [math.nan] * 6},
                     {"1": "bad"}, {"1": [[1], [2, 3]]}):
            with self.subTest(dofs=dofs):
                self.assertEqual(compute_deformation_scale(model(), dofs), 1.0)
        self.assertEqual(compute_deformation_scale(model(0), {"1": [1] * 6}), 1.0)
        self.assertEqual(compute_deformation_scale(None, {"1": [1] * 6}), 1.0)

    def test_missing_nodes_and_elements_are_safe(self):
        structure = model()
        structure.elements[3] = SimpleNamespace()
        self.assertAlmostEqual(compute_deformation_scale(structure, {"999": [24, 0, 0]}), 0.1)

    def test_extreme_finite_values_still_give_positive_finite_scale(self):
        for amplitude in (1e-300, 1e300, np.finfo(float).max):
            with self.subTest(amplitude=amplitude):
                scale = compute_deformation_scale(model(), {"2": [amplitude] * 6})
                self.assertTrue(math.isfinite(scale))
                self.assertGreater(scale, 0.0)

    def test_invalid_target_fraction_is_neutral(self):
        for fraction in (0, -1, math.nan, math.inf, "bad"):
            self.assertEqual(compute_deformation_scale(model(), {"2": [2, 0, 0]},
                                                       target_fraction=fraction), 1.0)

if __name__ == "__main__":
    unittest.main()
