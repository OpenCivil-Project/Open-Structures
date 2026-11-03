"""Node record order must not change structural coordinates or response."""
import contextlib
import copy
import io
import itertools
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np

# The production entry point sets up the legacy solver import paths.
from core.solver.linear_static.main_engine import run_linear_static_analysis
from core.solver.linear_static.data_manager import DataManager
from core.solver.linear_static.assembler import GlobalAssembler
from core.solver.linear_static.solver_kernel import LinearSolver
from core.solver.modal.mass_assembler import GlobalMassAssembler
from core.solver.modal.modal_engine import run_modal_analysis


IDS = (7, 19, 42)


def frame_model(order=IDS, mass_link=False):
    """An asymmetric 3D L-frame with sparse IDs, nodal/member loads and a spring."""
    spring = np.zeros((6, 6))
    spring[1, 1] = 2e5
    nodes = {
        7: dict(id=7, x=0., y=0., z=0., restraints=[True]*6),
        19: dict(id=19, x=3., y=.4, z=1., restraints=[False]*6,
                 spring_matrix=spring.tolist()),
        42: dict(id=42, x=3.6, y=2.5, z=2.1, restraints=[False]*6),
    }
    elements = [dict(id=eid, n1_id=ni, n2_id=nj, sec_name='Beam', beta=23.,
                     rel_i=[False]*6, rel_j=[False]*6, off_i=[0.]*3, off_j=[0.]*3)
                for eid, ni, nj in ((11, 7, 19), (37, 19, 42))]
    raw = {
        'info': {'active_dofs':[True]*6, 'analysis_engine':'native'},
        'nodes': [copy.deepcopy(nodes[nid]) for nid in order], 'elements':elements,
        'materials':[dict(name='Elastic', E=200e9, G=200e9/2.6, nu=.3,
                          rho=7850.*9.80665)],
        'sections':[dict(name='Beam', mat_name='Elastic',
                         properties=dict(A=.05, J=1.4e-4, I22=6e-5, I33=1.1e-4,
                                         As2=.04, As3=.04))],
        'load_patterns':[dict(name='TEST', sw_mult=0.)],
        'load_cases':[dict(name='STATIC', type='Linear Static', loads=[['TEST',1.]]),
                      dict(name='MODAL', type='Modal', loads=[], mass_source='Default', num_modes=3)],
        'loads':[dict(type='nodal', pattern='TEST', node_id=42, fx=1000., fy=-800.,
                      fz=-500., mx=10., my=-15., mz=20.),
                 dict(type='member_dist', pattern='TEST', element_id=37,
                      wx=0., wy=0., wz=-150., coord='Global', projected=False)],
        'mass_sources':[dict(name='Default', include_self_mass=True, include_patterns=False,
                             load_patterns=[])],
        'constraints':[], 'area_elements':[], 'cables':[], 'links':[], 'link_properties':[],
    }
    if mass_link:
        raw['link_properties'] = [dict(name='AddedMass', mass=25., weight=0., r1=.15,
                                      r2=.2, r3=.25, stiffness=np.zeros((6,6)).tolist(),
                                      damping=np.zeros((6,6)).tolist(), is_fixed=[False]*6)]
        raw['links'] = [dict(id=81, prop_name='AddedMass', nodes=[42], beta=0.)]
    return raw


def mapped(raw, folder):
    path = Path(folder)/'frame.mf'
    path.write_text(json.dumps(raw), encoding='utf-8')
    manager = DataManager(str(path))
    manager.process_all(case_name='STATIC')
    return manager, path


def static_state(raw):
    with tempfile.TemporaryDirectory() as folder, contextlib.redirect_stdout(io.StringIO()):
        manager, _ = mapped(raw, folder)
        stiffness, load = GlobalAssembler(manager).assemble_system()
        solver = LinearSolver(stiffness, load, manager)
        displacement, residual = solver.solve()
        reactions = solver.get_results_dict()['reactions']
        mass = GlobalMassAssembler(manager).build_mass_matrix('Default')
        return stiffness.toarray(), load, displacement, residual, reactions, mass.toarray()


def modal_state(raw):
    with tempfile.TemporaryDirectory() as folder, contextlib.redirect_stdout(io.StringIO()):
        _, path = mapped(raw, folder)
        output = Path(folder)/'frame_MODAL_results.json'
        run_modal_analysis(str(path),str(output),target_case_name='MODAL',
                           progress_callback=lambda *args: None)
        return json.loads(output.read_text(encoding='utf-8'))


class SolverNodeOrderTests(unittest.TestCase):
    def test_sparse_ids_preserve_node_fields_and_input_order(self):
        raw = frame_model((42, 7, 19))
        with tempfile.TemporaryDirectory() as folder, contextlib.redirect_stdout(io.StringIO()):
            manager, _ = mapped(raw, folder)
        self.assertEqual([node['id'] for node in manager.raw['nodes']], [42, 7, 19])
        self.assertEqual([node['id'] for node in manager.nodes], list(IDS))
        by_id = {node['id']:node for node in raw['nodes']}
        for position,node in enumerate(manager.nodes):
            original = by_id[node['id']]
            self.assertEqual(node['idx'],position)
            self.assertEqual(manager.node_id_to_idx[node['id']],position)
            np.testing.assert_array_equal(node['coords'],[original[key] for key in ('x','y','z')])
            self.assertEqual(node['restraints'],original['restraints'])
            if 'spring_matrix' in original:
                np.testing.assert_array_equal(node['spring_matrix'],original['spring_matrix'])

    def test_static_stiffness_load_response_and_mass_are_order_invariant(self):
        baseline = static_state(frame_model())
        for order in itertools.permutations(IDS):
            with self.subTest(order=order):
                actual = static_state(frame_model(order))
                for expected,value in zip(baseline[:4],actual[:4]):
                    np.testing.assert_allclose(value,expected,rtol=1e-10,atol=1e-8)
                self.assertEqual(set(actual[4]),set(baseline[4]))
                for nid in actual[4]:
                    np.testing.assert_allclose(actual[4][nid],baseline[4][nid],rtol=1e-10,atol=1e-8)
                np.testing.assert_array_equal(actual[5],baseline[5])

    def test_modal_frequencies_shapes_and_mass_are_order_invariant(self):
        baseline = modal_state(frame_model())
        self.assertEqual(baseline['status'],'SUCCESS',baseline)
        frequencies = np.array([row['f'] for row in baseline['tables']['periods']])
        self.assertEqual(len(frequencies),3)
        self.assertTrue(np.all(np.isfinite(frequencies)) and np.all(frequencies>0))
        mass = np.array([baseline['assembled_mass'][str(nid)] for nid in IDS]).reshape(-1)
        for order in itertools.permutations(IDS):
            with self.subTest(order=order):
                actual = modal_state(frame_model(order))
                self.assertEqual(actual['status'],'SUCCESS',actual)
                np.testing.assert_allclose([row['f'] for row in actual['tables']['periods']],
                                           frequencies,rtol=1e-9,atol=1e-9)
                self.assertEqual(actual['assembled_mass'],baseline['assembled_mass'])
                for mode in baseline['mode_shapes']:
                    expected = np.array([baseline['mode_shapes'][mode][str(nid)] for nid in IDS]).reshape(-1)
                    value = np.array([actual['mode_shapes'][mode][str(nid)] for nid in IDS]).reshape(-1)
                    # Eigenvector signs are arbitrary; compare physical-mass MAC.
                    mac = (expected @ (mass*value))**2 / ((expected @ (mass*expected))*(value @ (mass*value)))
                    self.assertGreater(mac,1.-1e-9)

    def test_mass_link_phantom_keeps_index_alignment_after_sparse_nodes(self):
        raw = frame_model((19, 42, 7),mass_link=True)
        with tempfile.TemporaryDirectory() as folder, contextlib.redirect_stdout(io.StringIO()):
            manager, _ = mapped(raw, folder)
        self.assertEqual([node['id'] for node in manager.nodes[:3]],list(IDS))
        self.assertEqual(len(manager.nodes),4)
        for position,node in enumerate(manager.nodes):
            self.assertEqual(node['idx'],position)
            self.assertEqual(manager.node_id_to_idx[node['id']],position)
        phantom = manager.nodes[-1]
        self.assertEqual(phantom['id'],'42~Link')
        self.assertEqual(phantom['restraints'],[True]*6)
        np.testing.assert_array_equal(phantom['coords'],manager.nodes[2]['coords'])
        self.assertEqual(manager.total_dofs,24)
        baseline = static_state(frame_model(mass_link=True))
        actual = static_state(raw)
        for expected,value in zip(baseline[:4],actual[:4]):
            np.testing.assert_allclose(value,expected,rtol=1e-10,atol=1e-8)
        np.testing.assert_array_equal(actual[5],baseline[5])


if __name__=='__main__':
    unittest.main()
