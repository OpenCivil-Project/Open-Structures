"""Distributed frame display groups continuous loads without hiding changed spans."""
import copy
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    'frame_load_display', ROOT / 'app/graphic/frame_load_display.py')
display = importlib.util.module_from_spec(spec)
spec.loader.exec_module(display)

def load(value=5., **changes):
    values = dict(pattern_name='Dead', coord_system='Global', projected=False,
                  load_type='Force', load_direction='Z', is_relative=True,
                  wx=0., wy=0., wz=value, distances=[0., 1.], magnitudes=[0., 0.])
    values.update(changes)
    return SimpleNamespace(**values)

def record(index, start, end, node_ids, assignment=None, axes=None):
    points = np.asarray([start, end], dtype=float)
    length = float(np.linalg.norm(points[1] - points[0]))
    assignment = assignment or load()
    axes = np.eye(3) if axes is None else axes
    return dict(element_id=index, node_ids=tuple(node_ids), points=points,
                length=length, section_key=('beam', 0.), selected=True,
                visibility=2, offsets=np.zeros((2, 3)),
                profiles=display.frame_load_components(assignment, length, axes))

def chain(n=8):
    return [record(i + 1, [i * 8. / n, 0., 0.], [(i + 1) * 8. / n, 0., 0.],
                   [i, i + 1]) for i in range(n)]

def sizes(records):
    return sorted(len(group) for group in display.build_frame_load_chains(records))

def sample_point(item):
    member, t = item
    return member['points'][0] + float(t) * (member['points'][1] - member['points'][0])

class FrameComponentsTests(unittest.TestCase):
    def test_uniform_components_retain_signed_values_and_global_directions(self):
        source = load(value=-5., wx=2., wy=3., load_direction='Gravity')
        before = copy.deepcopy(vars(source))
        profiles = display.frame_load_components(source, 8., np.eye(3))
        self.assertEqual(len(profiles), 3)
        for profile, axis, value in zip(profiles, np.eye(3), (2., 3., -5.)):
            np.testing.assert_array_equal(profile['direction'], axis)
            np.testing.assert_array_equal(profile['values'], [value, value])
            np.testing.assert_array_equal(profile['positions'], [0., 1.])
            self.assertTrue(profile['uniform'])
        self.assertEqual(vars(source), before)

    def test_local_components_use_the_supplied_global_basis(self):
        axes = np.array([[0., 1., 0.], [-1., 0., 0.], [0., 0., 1.]])
        profile = display.frame_load_components(
            load(value=0., wy=-3., coord_system='Local', load_direction='2'),
            2., axes)[0]
        np.testing.assert_array_equal(profile['direction'], axes[1])
        np.testing.assert_array_equal(profile['values'], [-3., -3.])

    def test_relative_and_absolute_affine_profiles_keep_the_actual_values(self):
        for distances, relative in (([0., .25, 1.], True), ([0., 2., 8.], False)):
            profile = display.frame_load_components(
                load(value=8., distances=distances, magnitudes=[0., 2., 8.],
                     is_relative=relative), 8., np.eye(3))[0]
            np.testing.assert_allclose(profile['positions'], [0., .25, 1.])
            np.testing.assert_array_equal(profile['values'], [0., 2., 8.])
            self.assertFalse(profile['uniform'])
            self.assertTrue(profile['affine'])

    def test_partial_and_non_affine_profiles_are_not_chain_eligible(self):
        for distances, magnitudes in (([.2, .8], [2., 8.]),
                                      ([0., .5, 1.], [0., 5., 2.])):
            profiles = display.frame_load_components(
                load(value=8., distances=distances, magnitudes=magnitudes),
                8., np.eye(3))
            self.assertEqual(len(profiles), 1)
            self.assertFalse(profiles[0]['affine'])

    def test_zero_components_do_not_create_annotations(self):
        self.assertEqual(display.frame_load_components(load(0.), 8., np.eye(3)), [])

class FrameChainTests(unittest.TestCase):
    def test_divided_uniform_member_keeps_one_chain_and_original_records(self):
        records = chain()
        before = copy.deepcopy(records)
        groups = display.build_frame_load_chains(records)
        self.assertEqual([len(group) for group in groups], [8])
        self.assertEqual({id(member) for member in groups[0]}, {id(member) for member in records})
        for member, original in zip(records, before):
            np.testing.assert_array_equal(member['points'], original['points'])
            np.testing.assert_array_equal(member['profiles'][0]['values'],
                                          original['profiles'][0]['values'])
            self.assertEqual(member['profiles'][0]['metadata'], original['profiles'][0]['metadata'])

    def test_edited_and_tiny_changed_child_split_then_restore(self):
        for value in (8., 5.000000000001):
            records = chain()
            records[3]['profiles'] = display.frame_load_components(load(value), 1., np.eye(3))
            self.assertEqual(sizes(records), [1, 3, 4])
            records[3]['profiles'] = display.frame_load_components(load(), 1., np.eye(3))
            self.assertEqual(sizes(records), [8])

    def test_different_pattern_type_projection_or_extra_stack_remains_separate(self):
        for changes in ({'pattern_name': 'Live'}, {'load_type': 'Moment'},
                        {'projected': True}, {'coord_system': 'Local'}):
            records = chain()
            records[3]['profiles'] = display.frame_load_components(load(**changes), 1., np.eye(3))
            self.assertEqual(sizes(records), [1, 3, 4])
        records = chain()
        records[3]['profiles'].extend(display.frame_load_components(
            load(0., wx=2., load_direction='X'), 1., np.eye(3)))
        self.assertEqual(sizes(records), [1, 3, 4])

    def test_selection_visibility_and_section_changes_form_boundaries(self):
        for name, value in (('selected', False), ('visibility', 1),
                            ('section_key', ('other beam', 0.))):
            records = chain()
            records[3][name] = value
            self.assertEqual(sizes(records), [1, 3, 4])

    def test_reversed_global_segments_keep_one_chain(self):
        records = chain()
        records[3]['points'] = records[3]['points'][::-1].copy()
        records[3]['node_ids'] = records[3]['node_ids'][::-1]
        self.assertEqual(sizes(records), [8])

    def test_different_actual_local_directions_do_not_merge(self):
        records = chain()
        for member in records:
            member['profiles'] = display.frame_load_components(
                load(0., wy=5., coord_system='Local', load_direction='2'), 1., np.eye(3))
        records[3]['profiles'] = display.frame_load_components(
            load(0., wy=5., coord_system='Local', load_direction='2'), 1.,
            np.diag([-1., -1., 1.]))
        self.assertEqual(sizes(records), [1, 3, 4])

    def test_continuous_physical_ramp_groups_but_changed_profile_does_not(self):
        records = chain()
        for i, member in enumerate(records):
            member['profiles'] = display.frame_load_components(
                load(26., magnitudes=[2. + 3. * i, 2. + 3. * (i + 1)]),
                1., np.eye(3))
        self.assertEqual(sizes(records), [8])
        records[3]['profiles'] = display.frame_load_components(
            load(26., distances=[0., .5, 1.], magnitudes=[11., 15., 14.]),
            1., np.eye(3))
        self.assertEqual(sizes(records), [1, 3, 4])

    def test_reversed_ramp_positions_preserve_the_same_global_slope(self):
        first = record(1, [0., 0., 0.], [1., 0., 0.], [0, 1],
                       load(8., magnitudes=[2., 5.]))
        second = record(2, [2., 0., 0.], [1., 0., 0.], [2, 1],
                        load(8., magnitudes=[8., 5.]))
        self.assertEqual(sizes([first, second]), [2])

    def test_partial_profile_is_not_joined_to_another_partial_profile(self):
        records = chain(2)
        for member in records:
            member['profiles'] = display.frame_load_components(
                load(5., distances=[.25, .75], magnitudes=[5., 5.]),
                4., np.eye(3))
        self.assertEqual(sizes(records), [1, 1])

    def test_bends_gaps_and_ambiguous_collinear_branches_do_not_merge(self):
        a = record(1, [0., 0., 0.], [1., 0., 0.], [0, 1])
        bend = record(2, [1., 0., 0.], [1., 1., 0.], [1, 2])
        self.assertEqual(sizes([a, bend]), [1, 1])
        gap = record(2, [1., 0., 0.], [2., 0., 0.], [10, 11])
        self.assertEqual(sizes([a, gap]), [1, 1])
        b = record(2, [1., 0., 0.], [2., 0., 0.], [1, 2])
        overlap = record(3, [1., 0., 0.], [3., 0., 0.], [1, 3])
        self.assertEqual(sizes([a, b, overlap]), [1, 1, 1])

    def test_incompatible_offset_at_shared_joint_separates_members(self):
        records = chain(2)
        records[1]['offsets'][0, 1] = .2
        self.assertEqual(sizes(records), [1, 1])

class FrameSamplingTests(unittest.TestCase):
    def test_sampling_depends_on_view_spacing_instead_of_division_count(self):
        project = lambda point: (point[0] * 80., 100.)
        counts = []
        for n in (8, 64):
            records = chain(n)
            prepared = display.prepare_frame_load_chain(records)
            samples = display.sample_frame_load_arrows(records, project, 55., prepared=prepared)
            counts.append(len(samples))
            self.assertGreater(len(samples), 4)
            self.assertLess(len(samples), 20)
            xs = sorted(sample_point(item)[0] * 80 for item in samples)
            self.assertTrue(all(b - a >= 55. - 1e-8 for a, b in zip(xs, xs[1:])))
            self.assertTrue(all(any(item[0] is original for original in records) for item in samples))
        self.assertLessEqual(abs(counts[0] - counts[1]), 3)

    def test_invisible_projection_yields_no_arrows_and_singleton_stays_visible(self):
        records = chain(1)
        self.assertEqual(display.sample_frame_load_arrows(records, lambda point: None), [])
        samples = display.sample_frame_load_arrows(records, lambda point: (100., 100.), 55.)
        self.assertEqual(len(samples), 1)
        self.assertIs(samples[0][0], records[0])

    def test_prepared_common_scale_covers_the_complete_ramp(self):
        records = chain()
        for i, member in enumerate(records):
            member['profiles'] = display.frame_load_components(
                load(10., magnitudes=[2. + i, 3. + i]), 1., np.eye(3))
        prepared = display.prepare_frame_load_chain(records)
        self.assertEqual(float(prepared['max_abs'][0]), 10.)
        representative, t = prepared['representative']
        self.assertTrue(any(representative is original for original in records))
        self.assertGreaterEqual(t, 0.)
        self.assertLessEqual(t, 1.)

    def test_partial_profile_representative_is_inside_its_loaded_interval(self):
        member = record(1, [0., 0., 0.], [8., 0., 0.], [0, 1],
                        load(6., distances=[.1, .2], magnitudes=[2., 6.]))
        prepared = display.prepare_frame_load_chain([member])
        representative, t = prepared['representative']
        self.assertIs(representative, member)
        self.assertGreaterEqual(t, .1)
        self.assertLessEqual(t, .2)

    def test_profile_breakpoints_are_retained_as_sampling_candidates(self):
        member = record(1, [0., 0., 0.], [8., 0., 0.], [0, 1],
                        load(10., distances=[0., .137, .863, 1.],
                             magnitudes=[0., 10., 10., 0.]))
        prepared = display.prepare_frame_load_chain([member])
        positions = [float(t) for original, t in prepared['candidates'] if original is member]
        for breakpoint in (.137, .863):
            self.assertTrue(any(abs(position - breakpoint) < 1e-12 for position in positions))

    def test_batch_projection_is_used_for_cached_candidates(self):
        records = chain(64)
        calls = []

        def project(point):
            return (point[0] * 80., 100.)

        def batch(points):
            calls.append(len(points))
            return np.c_[points[:, 0] * 80., np.full(len(points), 100.)]

        project.batch = batch
        prepared = display.prepare_frame_load_chain(records)
        samples = display.sample_frame_load_arrows(records, project, 55., prepared=prepared)
        self.assertTrue(calls)
        self.assertGreater(len(samples), 4)

if __name__ == '__main__':
    unittest.main()
