"""Arrow preparation stays bounded as chains and model sizes grow."""
from pathlib import Path
import sys
import unittest

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tests'))
from test_frame_load_display import display, chain, record, load, sample_point

class FramePreparationScalingTests(unittest.TestCase):
    def test_single_and_thousand_segment_chains_have_bounded_candidates(self):
        for count in (1, 8, 64, 1000):
            with self.subTest(count=count):
                prepared = display.prepare_frame_load_chain(chain(count))
                self.assertLessEqual(len(prepared['candidate_points']), 17)
                self.assertEqual(len(prepared['records']), count)
                self.assertEqual(len(prepared['spans']), count)
                self.assertEqual(len(display.sample_frame_load_arrows(
                    prepared['records'], None, prepared=prepared)), 5)

    def test_static_arrow_positions_do_not_change_when_members_are_divided(self):
        expected = None
        for count in (1, 8, 64, 1000):
            members = chain(count)
            prepared = display.prepare_frame_load_chain(members)
            samples = display.sample_frame_load_arrows(members, None, prepared=prepared)
            points = np.array(sorted(tuple(sample_point(item)) for item in samples))
            if expected is None:
                expected = points
            else:
                np.testing.assert_allclose(points, expected, rtol=0., atol=1e-12)
            for member, t in samples:
                self.assertTrue(any(member is original for original in members))
                self.assertGreaterEqual(t, 0.)
                self.assertLessEqual(t, 1.)

    def test_reversed_members_preserve_world_samples_and_ownership(self):
        members = chain(64)
        original = display.prepare_frame_load_chain(members)
        expected = np.array(sorted(tuple(sample_point(item)) for item in
            display.sample_frame_load_arrows(members, None, prepared=original)))
        for index, member in enumerate(members):
            if index % 2:
                member['points'] = member['points'][::-1].copy()
                member['node_ids'] = member['node_ids'][::-1]
        prepared = display.prepare_frame_load_chain(members)
        actual = np.array(sorted(tuple(sample_point(item)) for item in
            display.sample_frame_load_arrows(members, None, prepared=prepared)))
        np.testing.assert_allclose(actual, expected, rtol=0., atol=1e-12)

    def test_many_profile_knots_keep_peak_and_budget_without_changing_profile(self):
        positions = np.linspace(0., 1., 501)
        values = np.ones(501)
        values[137] = 12.
        member = record(1, [0., 0., 0.], [8., 0., 0.], [0, 1],
            load(12., distances=positions.tolist(), magnitudes=values.tolist()))
        before = member['profiles'][0]['positions'].copy()
        prepared = display.prepare_frame_load_chain([member])
        self.assertLessEqual(len(prepared['candidate_points']), 17)
        candidates = [t for _, t in prepared['candidates']]
        self.assertTrue(any(abs(t - positions[137]) < 1e-12 for t in candidates))
        np.testing.assert_array_equal(member['profiles'][0]['positions'], before)
        self.assertEqual(len(member['profiles'][0]['values']), 501)

    def test_thousand_independent_members_do_not_create_dense_per_member_lattices(self):
        total = 0
        for index in range(1000):
            member = record(index + 1, [index * 2., 0., 0.],
                            [index * 2. + 1., 0., 0.], [index * 2, index * 2 + 1])
            total += len(display.prepare_frame_load_chain([member])['candidate_points'])
        self.assertLessEqual(total, 17000)

if __name__ == '__main__':
    unittest.main()
