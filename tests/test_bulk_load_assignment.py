"""Bulk assignment keeps scalar load semantics while bounding load-list scans."""
import copy
import os
from pathlib import Path
import random
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

import numpy as np

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.commands import CmdAssignFrameLoad
from core.model import StructuralModel, MemberLoad, NodalLoad
from core.loads import AreaGravityLoad, AreaUniformLoad, MemberPointLoad

class CountingLoads(list):
    def __init__(self, values=()):
        super().__init__(values)
        self.scanned = 0

    def __iter__(self):
        self.scanned += len(self)
        return super().__iter__()

def records():
    return [MemberLoad(1, 'P', wz=-7., coord_system='Local', magnitudes=[1., 2.]),
            MemberPointLoad(1, 'P', 19., .25, True, 'Global', 'Z', 'Force'),
            MemberLoad(2, 'OTHER', wx=3.), MemberLoad(1, 'P', wy=4.),
            AreaUniformLoad(1, 'P', 'Local', 'Global X', 11.),
            AreaUniformLoad(1, 'P', 'GLOBAL', 'Gravity', 13.),
            AreaUniformLoad(1, 'P', 'Local', 'Gravity', 17.),
            AreaUniformLoad(2, 'OTHER', uniform_load=23.),
            AreaGravityLoad(1, 'P', gz=-1.), NodalLoad(1, 'P', fz=29.)]

def model(loads=None, count=4):
    result = StructuralModel('Bulk load semantics')
    result.elements = {i: SimpleNamespace() for i in range(1, count+1)}
    result.area_elements = {i: SimpleNamespace() for i in range(1, count+1)}
    result.loads = copy.deepcopy(records() if loads is None else loads)
    return result

def canonical(value):
    if isinstance(value, np.ndarray):
        return ('array', value.tolist())
    if isinstance(value, list):
        return ('list', [canonical(item) for item in value])
    if isinstance(value, tuple):
        return ('tuple', [canonical(item) for item in value])
    if hasattr(value, '__dict__'):
        return (type(value).__name__, {key: canonical(item) for key, item in vars(value).items()})
    return value

class BulkLoadAssignmentTests(unittest.TestCase):
    def compare(self, kind, ids, params, initial=None):
        scalar = model(initial)
        batched = model(initial)
        original_list = batched.loads
        scalar_call = getattr(scalar, 'assign_' + kind + '_load')
        batch_call = getattr(batched, 'assign_' + kind + '_loads')
        error = None
        try:
            for target in ids:
                scalar_call(target, **params)
        except (KeyError, TypeError, ValueError) as exc:
            error = (type(exc), str(exc))
        batch_error = None
        try:
            batch_call(ids, **params)
        except (KeyError, TypeError, ValueError) as exc:
            batch_error = (type(exc), str(exc))
        self.assertEqual(batch_error, error)
        self.assertEqual(canonical(batched.loads), canonical(scalar.loads))
        self.assertIs(batched.loads, original_list)
        return batched

    def test_frame_modes_keep_companions_patterns_metadata_and_order(self):
        for mode in ('add', 'replace', 'delete', 'unknown'):
            for intensity in (0., -31.):
                with self.subTest(mode=mode, intensity=intensity):
                    result = self.compare('member', [2, 1, 3], dict(pattern_name='P',
                        wx=intensity, wy=0., wz=0., mode=mode, projected=True,
                        coord_system='Local', distances=(0., .2, .8, 1.),
                        magnitudes=[0., intensity, intensity, 0.], is_relative=False,
                        load_direction='2', load_type='Moment'))
                    points = [load for load in result.loads if isinstance(load, MemberPointLoad)]
                    self.assertEqual(len(points), 0 if mode in ('replace', 'delete') else 1)

    def test_area_modes_keep_other_directions_and_first_matching_add_record(self):
        for mode in ('add', 'replace', 'delete', 'unknown'):
            for pressure in (0., -13., 41.):
                with self.subTest(mode=mode, pressure=pressure):
                    self.compare('area_uniform', [2, 1, 3], dict(pattern_name='P',
                        uniform_load=pressure, load_direction='Gravity', coord_system='Local', mode=mode))
        result = self.compare('area_uniform', [1], dict(pattern_name='P', uniform_load=-13.,
                                                       load_direction='Gravity', mode='add'))
        matching = [load for load in result.loads if hasattr(load, 'uniform_load')
                    and load.area_id == 1 and load.load_direction == 'Gravity']
        self.assertEqual([(load.coord_system, load.uniform_load) for load in matching],
                         [('GLOBAL', 0.), ('Local', 17.)])

    def test_repeated_invalid_and_unhashable_ids_follow_scalar_partial_errors(self):
        for ids in ([1, 2, 1], [1, 999, 2], [999, 1], [1, [], 2], []):
            for mode in ('add', 'replace', 'delete', 'unknown'):
                with self.subTest(ids=ids, mode=mode):
                    self.compare('member', ids, dict(pattern_name='P', wz=-3., mode=mode))
                    self.compare('area_uniform', ids, dict(pattern_name='P', uniform_load=3., mode=mode))
                    self.compare('area_gravity', ids, dict(pattern_name='P', gz=-3., mode=mode))

    def test_area_gravity_modes_preserve_other_loads_and_first_matching_add(self):
        initial = records() + [AreaGravityLoad(1, 'P', 'Local', gx=3., gy=5., gz=7.),
                               AreaGravityLoad(2, 'OTHER', 'Local', gz=-11.)]
        for mode in ('add', 'replace', 'delete', 'unknown'):
            for multipliers in ((0., 0., 0.), (2., -3., 1.), (0., 0., -4.)):
                with self.subTest(mode=mode, multipliers=multipliers):
                    self.compare('area_gravity', [2, 1, 3], dict(pattern_name='P',
                        gx=multipliers[0], gy=multipliers[1], gz=multipliers[2],
                        coord_system='Local', mode=mode), initial=initial)
        result = self.compare('area_gravity', [1], dict(pattern_name='P', gz=1.,
                              coord_system='Local', mode='add'), initial=initial)
        matching = [load for load in result.loads if isinstance(load, AreaGravityLoad)
                    and load.area_id == 1 and load.pattern_name == 'P']
        self.assertEqual([(load.coord_system, load.gx, load.gy, load.gz) for load in matching],
                         [('GLOBAL', 0., 0., 0.), ('Local', 3., 5., 7.)])

    def test_invalid_parameters_preserve_first_target_error_mutation(self):
        self.compare('member', [1, 2], dict(pattern_name='P', wx='invalid', mode='replace'))
        self.compare('member', [1, 2], dict(pattern_name='P', wx=1.,
                                          projected=np.array([True, False]), mode='replace'))
        self.compare('area_uniform', [1, 2], dict(pattern_name='P',
                     uniform_load=np.array([1., 2.]), mode='replace'))
        self.compare('area_gravity', [1, 2], dict(pattern_name='P',
                     gx=np.array([1., 2.]), mode='replace'))
        self.compare('area_gravity', [1, 2], dict(pattern_name='P',
                     gx=3., gy='invalid', gz=-1., mode='add'))

    def test_default_lists_are_independent_and_explicit_lists_remain_shared(self):
        result = model([])
        result.assign_member_loads([1, 2], 'P', wz=1.)
        self.assertIsNot(result.loads[0].distances, result.loads[1].distances)
        self.assertIsNot(result.loads[0].magnitudes, result.loads[1].magnitudes)
        distances, magnitudes = [0., 1.], [-1., -2.]
        result.assign_member_loads([3, 4], 'P', magnitudes=magnitudes, distances=distances)
        self.assertIs(result.loads[-1].distances, distances)
        self.assertIs(result.loads[-2].magnitudes, magnitudes)

    def test_unrelated_records_keep_object_identity(self):
        result = model()
        unrelated = [load for load in result.loads if not (
            hasattr(load, 'element_id') and load.element_id == 1 and getattr(load, 'pattern_name', None) == 'P')]
        result.assign_member_loads([1], 'P', wz=-1.)
        for previous, current in zip(unrelated, result.loads):
            self.assertIs(previous, current)

    def test_randomized_mixed_load_sequences_match_single_assignment(self):
        generator = random.Random(619)
        for _ in range(70):
            ids = [generator.randint(1, 4) for _ in range(generator.randint(0, 6))]
            mode = generator.choice(['add', 'replace', 'delete'])
            pressure = generator.choice([0., -5., 7.])
            self.compare('member', ids, dict(pattern_name=generator.choice(['P', 'OTHER']),
                wx=pressure, wz=-pressure, magnitudes=[0., pressure], distances=[.2, .7],
                mode=mode, coord_system=generator.choice(['Local', 'Global']),
                load_direction=generator.choice(['Gravity', '1', 'Global Z'])))
            self.compare('area_uniform', ids, dict(pattern_name=generator.choice(['P', 'OTHER']),
                uniform_load=pressure, mode=mode, coord_system=generator.choice(['GLOBAL', 'Local']),
                load_direction=generator.choice(['Gravity', 'Global X', 'gravity'])))
            self.compare('area_gravity', ids, dict(pattern_name=generator.choice(['P', 'OTHER']),
                gx=pressure, gy=-pressure, gz=generator.choice([0., -1., 1.]),
                mode=mode, coord_system=generator.choice(['GLOBAL', 'Local'])))

    def test_unique_batches_have_linear_load_scan_budget(self):
        count = 10000
        for kind in ('member', 'area_uniform'):
            with self.subTest(kind=kind):
                result = model([], count=count)
                if kind == 'member':
                    existing = [MemberLoad(i, 'P', wz=-1.) for i in range(1, count+1)]
                    params = dict(pattern_name='P', wz=-2., mode='replace')
                else:
                    existing = [AreaUniformLoad(i, 'P', uniform_load=1.) for i in range(1, count+1)]
                    params = dict(pattern_name='P', uniform_load=2., mode='add')
                result.loads = CountingLoads(existing)
                original = result.loads
                getattr(result, 'assign_' + kind + '_loads')(range(1, count+1), **params)
                self.assertIs(result.loads, original)
                self.assertLessEqual(result.loads.scanned, count)
                self.assertEqual(len(result.loads), count)

    def test_area_gravity_unique_batches_have_linear_load_scan_budget(self):
        count = 10000
        for mode in ('replace', 'add', 'delete'):
            with self.subTest(mode=mode):
                result = model([], count=count)
                result.loads = CountingLoads(AreaGravityLoad(i, 'P', gz=-1.)
                                             for i in range(1, count+1))
                original = result.loads
                result.assign_area_gravity_loads(range(1, count+1), 'P', gz=-2., mode=mode)
                self.assertIs(result.loads, original)
                self.assertLessEqual(result.loads.scanned, count)
                self.assertEqual(len(result.loads), 0 if mode == 'delete' else count)
                if mode != 'delete':
                    self.assertEqual(result.loads[-1].gz, -3. if mode == 'add' else -2.)

    def test_command_uses_bulk_assignment_and_load_only_refresh_for_redo_undo(self):
        result = model([])
        result.assign_member_load(1, 'P', wz=-5.)
        previous = canonical(result.loads)
        actual_many = result.assign_member_loads
        result.assign_member_loads = Mock(wraps=actual_many)
        result.assign_member_load = Mock(side_effect=AssertionError('single calls are quadratic'))
        window = SimpleNamespace(refresh_load_display=Mock(), draw_both_canvases=Mock())
        command = CmdAssignFrameLoad(result, window, [1, 2], 'P', 0., 0., -7., False, 'Global')
        command.redo()
        result.assign_member_loads.assert_called_once()
        command.undo()
        self.assertEqual(canonical(result.loads), previous)
        self.assertEqual(window.refresh_load_display.call_count, 2)
        window.draw_both_canvases.assert_not_called()

    def test_command_falls_back_for_legacy_model_and_window(self):
        result = SimpleNamespace(loads=[], assign_member_load=Mock())
        window = SimpleNamespace(draw_both_canvases=Mock())
        command = CmdAssignFrameLoad(result, window, [1, 2], 'P', 0., 0., -7., False, 'Global')
        command.redo()
        self.assertEqual(result.assign_member_load.call_count, 2)
        window.draw_both_canvases.assert_called_once()

    def test_command_undo_restores_same_pattern_point_companions_for_all_modes(self):
        for mode in ('add', 'replace', 'delete'):
            with self.subTest(mode=mode):
                result = model()
                companion = MemberPointLoad(2, 'P', -37., .8, False, 'Local', '2', 'Moment')
                companion.is_tributary_generated = True
                result.loads.append(companion)
                unrelated = MemberPointLoad(3, 'P', 41., .3, True, 'Global', 'Y', 'Force')
                result.loads.append(unrelated)
                original_list = result.loads

                def data():
                    return sorted(repr(canonical(load)) for load in result.loads)

                before = data()
                window = SimpleNamespace(refresh_load_display=Mock(), draw_both_canvases=Mock())
                command = CmdAssignFrameLoad(result, window, [1, 2], 'P', 0., 0., -43.,
                                            False, 'Global', mode=mode)
                command.redo()
                after = data()
                selected_points = [load for load in result.loads
                    if isinstance(load, MemberPointLoad) and load.element_id in (1, 2)
                    and load.pattern_name == 'P']
                self.assertEqual(len(selected_points), 2 if mode == 'add' else 0)
                self.assertIs(next(load for load in result.loads if load is unrelated), unrelated)
                for _ in range(2):
                    command.undo()
                    self.assertEqual(data(), before)
                    self.assertIs(result.loads, original_list)
                    command.redo()
                    self.assertEqual(data(), after)
                    self.assertIs(result.loads, original_list)
                self.assertEqual(window.refresh_load_display.call_count, 5)
                window.draw_both_canvases.assert_not_called()

if __name__ == '__main__':
    unittest.main()
