"""Generate and verify 100 shared models through the production file pipelines.

Run from the repository: python -m validation.linear_modal.runner
No GUI is required. Failures remain visible and give a nonzero exit status.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import contextlib
from functools import lru_cache
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import traceback

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
DOFS = ('UX', 'UY', 'UZ', 'RX', 'RY', 'RZ')


def file_digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


@lru_cache(maxsize=1)
def solver_digest():
    digest = hashlib.sha256()
    paths = sorted((ROOT/'core'/'solver').rglob('*.py'))
    paths += [ROOT/'core'/'units.py', ROOT/'core'/'compact_json.py']
    for path in paths:
        digest.update(str(path.relative_to(ROOT)).replace('\\','/').encode('utf-8'))
        digest.update(path.read_bytes())
    return digest.hexdigest()


def save_json(path, data):
    def convert(value):
        if isinstance(value, np.ndarray):
            return value.tolist()
        if isinstance(value, np.generic):
            return value.item()
        if isinstance(value, Path):
            return str(value)
        raise TypeError(type(value).__name__)
    Path(path).write_text(json.dumps(data, indent=2, default=convert, allow_nan=False) + '\n', encoding='utf-8')


def solve_file(model_path):
    """Fresh subprocess imports the same entry points used by the application."""
    from core.solver.linear_static.main_engine import run_linear_static_analysis
    from core.solver.modal.modal_engine import run_modal_analysis
    path = Path(model_path)
    for label, entry, case in (
        ('STATIC', run_linear_static_analysis, 'STATIC'),
        ('MODAL', run_modal_analysis, 'MODAL'),
    ):
        out = path.with_name(path.stem + '_' + label + '_results.json')
        log = path.with_name(path.stem + '_' + label + '.log')
        # Remove only stale result files for this exact generated case.
        if out.exists():
            out.unlink()
        with log.open('w', encoding='utf-8') as stream, contextlib.redirect_stdout(stream), contextlib.redirect_stderr(stream):
            try:
                entry(str(path), str(out), target_case_name=case, progress_callback=lambda *args: None)
            except Exception:
                traceback.print_exc()
                save_json(out, {'status': 'FAILED', 'error': traceback.format_exc()})
        if not out.exists():
            save_json(out, {'status': 'FAILED', 'error': 'Solver returned without writing results; see log.'})


def vector(table, ids):
    return np.array([table[str(nid)] for nid in ids], dtype=float).reshape(-1)


def component_check(name, actual, expected, ids, rtol, floors):
    """Component tolerances preserve small nonzero values and separate units."""
    actual, expected = np.asarray(actual), np.asarray(expected)
    if actual.shape != expected.shape or not np.all(np.isfinite(actual)):
        return {'name': name, 'passed': False, 'reason': 'Wrong shape or nonfinite values'}
    floor = np.tile(np.asarray(floors), len(ids))
    errors = np.abs(actual - expected)
    limits = floor + rtol * np.abs(expected)
    ratios = errors / limits
    bad = np.argsort(ratios)[::-1][:8]
    return {
        'name': name, 'passed': bool(np.all(ratios <= 1)),
        'max_tolerance_ratio': float(ratios.max(initial=0)),
        'relative_tolerance': rtol, 'absolute_tolerances_per_dof': list(floors),
        'worst_components': [
            {'node': ids[int(i)//6], 'dof': DOFS[int(i)%6], 'actual': float(actual[i]),
             'expected': float(expected[i]), 'absolute_error': float(errors[i]), 'tolerance': float(limits[i])}
            for i in bad if ratios[i] > 1
        ],
    }


def scalar_check(name, value, limit):
    return {'name': name, 'passed': bool(np.isfinite(value) and value <= limit), 'value': float(value), 'limit': limit}


def analytical_checks(data, spec, kind):
    checks = []
    records = (spec or {}).get('analytical_' + kind, [])
    for record in records:
        if kind == 'static':
            actual = data[record.get('result','displacements')][str(record['node_id'])][record['dof']]
            expected = record['value']
            floor = 1e-4 if record.get('result')=='reactions' else 1e-10
            tolerance = floor + 2e-6 * abs(expected)
        else:
            actual = data['tables']['periods'][record['mode']-1]['f']
            expected = record['frequency_hz']
            tolerance = 1e-9 + record.get('tolerance',.02)*abs(expected)
        error = abs(actual-expected)
        checks.append({'name':'analytical: '+record['label'], 'passed':bool(np.isfinite(actual) and error<=tolerance),
                       'actual':actual,'expected':expected,'absolute_error':error,'tolerance':tolerance,
                       'formula':record['formula'], 'reference_kind':'continuum or exact discrete formula as labelled'})
    return checks


def compare(case, reference):
    path = Path(case['mf_path'])
    ids = reference['node_ids']
    k = reference.get('K_regularized', reference['K'])
    free = np.asarray(reference['free'], dtype=int)
    mass = reference['mass_regularized'][free]
    result = {'id': case['id'], 'family': case['family'], 'variant': case['variant'],
              'model_file': path.name, 'static': {}, 'modal': {}, 'analytical': [], 'reference_error': None}
    execution_path = path.parent / 'execution.json'
    if execution_path.exists():
        execution = json.loads(execution_path.read_text(encoding='utf-8'))
        result['execution'] = execution
        if execution.get('model_sha256') and execution['model_sha256']!=file_digest(path):
            execution = {'error':'Model changed since analysis; rerun the suite.'}
        if execution.get('solver_source_sha256') and execution['solver_source_sha256']!=solver_digest():
            execution = {'error':'Solver source changed since analysis; rerun the suite.'}
        if execution.get('error') or execution.get('returncode',0)!=0:
            for kind in ('static','modal'):
                result[kind] = {'passed':False,'error':str(execution)}
            return result
    for kind in ('STATIC', 'MODAL'):
        try:
            data = json.loads(path.with_name(path.stem + '_' + kind + '_results.json').read_text(encoding='utf-8'))
            if data.get('status') != 'SUCCESS':
                raise ValueError(str(data.get('error', data)))
            checks = []
            if kind == 'STATIC':
                u = vector(data['displacements'], ids)
                reactions = vector(data['reactions'], ids)
                checks.append(component_check('nodal displacement and rotation', u, reference['U'], ids, 2e-6, (1e-10,)*6))
                # Force and moment floors are in N and N*m, respectively.
                checks.append(component_check('support force and moment', reactions, reference['R'], ids, 2e-6, (1e-4,)*6))
                internal = (k @ u)[free]
                applied = reference['P'][free]
                checks.append(scalar_check('independent free-DOF equilibrium residual',
                    np.linalg.norm(internal-applied) / max(np.linalg.norm(internal)+np.linalg.norm(applied), 1e-20), 2e-6))
            else:
                rows = data['tables']['periods']
                actual_f = np.array([r['f'] for r in rows], dtype=float)
                expected_f = np.asarray(reference['frequencies_regularized'])
                requested = next(c['num_modes'] for c in case['model']['load_cases'] if c['name']=='MODAL')
                expected_count = min(requested, max(1, len(free)-2))
                checks.append({'name':'mode count', 'passed': len(rows)==expected_count,
                               'actual':len(rows), 'expected':expected_count})
                valid = len(actual_f)==expected_count and np.all(np.isfinite(actual_f)) and np.all(actual_f>0) and np.all(np.diff(actual_f)>=-1e-9)
                checks.append({'name':'finite positive sorted frequencies', 'passed':bool(valid)})
                if valid:
                    ef = expected_f[:expected_count]
                    checks.append(scalar_check('maximum relative frequency error', np.max(np.abs(actual_f-ef)/ef), 2e-5))
                    periods = np.array([r['T'] for r in rows])
                    omegas = np.array([r['omega'] for r in rows])
                    eigenvalues = np.array([r['eigen'] for r in rows])
                    identity_error = max(float(np.max(np.abs(periods*actual_f-1))),
                                         float(np.max(np.abs(omegas/(2*np.pi*actual_f)-1))),
                                         float(np.max(np.abs(eigenvalues/(omegas**2)-1))))
                    checks.append(scalar_check('period/frequency/omega/eigenvalue consistency',identity_error,1e-9))
                    phi = np.column_stack([vector(data['mode_shapes'][f'Mode {i+1}'], ids) for i in range(len(rows))])[free]
                    eigen = np.array([r['eigen'] for r in rows])
                    kphi = k[np.ix_(free,free)] @ phi
                    mphi = mass[:,None] * phi
                    residual = np.linalg.norm(kphi-mphi*eigen, axis=0) / np.maximum(np.linalg.norm(kphi,axis=0)+np.linalg.norm(mphi*eigen,axis=0),1e-20)
                    checks.append(scalar_check('maximum independent eigen residual', residual.max(), 2e-5))
                    gram = phi.T @ mphi
                    checks.append(scalar_check('mass normalization and orthogonality', np.max(np.abs(gram-np.eye(len(rows)))), 2e-5))
                    rp = np.asarray(reference['phi'])[free]
                    # Evaluate each eigenvector against its entire repeated eigenvalue
                    # subspace, so signs and arbitrary bases cannot cause false failures.
                    reig = np.asarray(reference['eigenvalues'])
                    projections = []
                    for j, ev in enumerate(reig[:expected_count]):
                        cluster = np.flatnonzero(np.abs(reig-ev) <= max(abs(ev)*2e-5,1e-8))
                        q = rp[:,cluster]
                        gram_q = q.T @ (mass[:,None]*q)
                        cross = q.T @ (mass*phi[:,j])
                        score = float(cross.T @ np.linalg.pinv(gram_q) @ cross / gram[j,j])
                        projections.append(min(1., max(0., score)))
                    checks.append(scalar_check('worst modal subspace mismatch (1-MAC)', 1-min(projections), 2e-4))
                assembled = vector(data['assembled_mass'], ids)
                checks.append(component_check('assembled physical nodal mass', assembled, reference['mass'], ids, 1e-8, (1e-10,)*6))
            formula_checks = analytical_checks(data,case.get('spec'),kind.lower())
            checks.extend(formula_checks)
            result['analytical'].extend(formula_checks)
            result[kind.lower()] = {'passed':all(c['passed'] for c in checks), 'checks':checks}
        except Exception as error:
            result[kind.lower()] = {'passed':False, 'error':str(error)}
    # Reference records analytical formula comparisons separately from mesh-specific
    # checks; these are never silently relabelled as exact continuum agreement.
    return result


def run_one(case, timeout):
    path = Path(case['mf_path'])
    proc_log = path.with_name(path.stem + '_process.log')
    provenance = {'model_sha256':file_digest(path),'solver_source_sha256':solver_digest()}
    # Both analyses must start clean even if STATIC crashes before MODAL starts.
    for kind in ('STATIC','MODAL'):
        stale = path.with_name(path.stem + '_' + kind + '_results.json')
        if stale.exists():
            stale.unlink()
    with proc_log.open('w', encoding='utf-8') as log:
        try:
            p = subprocess.run([sys.executable, '-m', 'validation.linear_modal.runner', '--solve-file', str(path)],
                               cwd=ROOT, stdout=log, stderr=log, timeout=timeout,
                               env={**os.environ, 'OPENBLAS_NUM_THREADS':'1', 'OMP_NUM_THREADS':'1', 'PYTHONIOENCODING':'utf-8'})
            return {'returncode':p.returncode, **provenance}
        except subprocess.TimeoutExpired:
            return {'error':f'Solver subprocess exceeded {timeout} seconds', **provenance}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=HERE)
    parser.add_argument('--jobs', type=int, default=4)
    parser.add_argument('--timeout', type=int, default=90)
    parser.add_argument('--generate-only', action='store_true')
    parser.add_argument('--case', help='Run one case ID (all 100 files are generated)')
    parser.add_argument('--solve-file', type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.solve_file:
        solve_file(args.solve_file)
        return 0
    from .models import generate_cases
    from .reference import analyze
    from .reports import write_reports
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    cases = generate_cases(output)
    if len(cases)!=100 or len({c['id'] for c in cases})!=100:
        raise ValueError('Suite must contain exactly 100 unique shared models')
    save_json(output/'manifest.json', [{'id':c['id'],'family':c['family'],'variant':c['variant'],
              'mf_file':str(Path(c['mf_path']).relative_to(output)), 'spec':c.get('spec',{})} for c in cases])
    selected = [c for c in cases if not args.case or c['id']==args.case]
    if not selected:
        parser.error('Unknown case ID')
    references = {}
    failures = {}
    started = time.time()
    for case in selected:
        try:
            ref = analyze(case['model'], spec=case.get('spec'))
            references[case['id']] = ref
            expected_data = ref['expected']
            expected_data['analytical_reference_checks'] = (
                analytical_checks(expected_data['static'],case.get('spec'),'static') +
                analytical_checks({'tables':{'periods':[{'f':float(f)} for f in ref['frequencies_regularized']]}},case.get('spec'),'modal'))
            save_json(Path(case['directory'])/'expected.json', ref['expected'])
        except Exception:
            failures[case['id']] = traceback.format_exc()
            save_json(Path(case['directory'])/'expected.json', {'status':'REFERENCE_ERROR','error':failures[case['id']]})
    if args.generate_only:
        print(f'Generated {len(cases)} models and {len(references)} independent solutions; {len(failures)} reference errors.')
        return int(bool(failures))
    progress = 0
    with ThreadPoolExecutor(max_workers=max(1,args.jobs)) as pool:
        pending = {pool.submit(run_one,c,args.timeout):c for c in selected}
        for future in as_completed(pending):
            case = pending[future]
            outcome = future.result()
            save_json(Path(case['directory'])/'execution.json', outcome)
            progress += 1
            print(f'[{progress}/{len(selected)}] {case["id"]} solver finished', flush=True)
    results = []
    for case in selected:
        if case['id'] in failures:
            result = {'id':case['id'],'family':case['family'],'variant':case['variant'],
                      'static':{'passed':False},'modal':{'passed':False},'reference_error':failures[case['id']]}
        else:
            result = compare(case,references[case['id']])
        save_json(Path(case['directory'])/'comparison.json', result)
        results.append(result)
    write_reports(output,results,time.time()-started)
    sp = sum(r['static']['passed'] for r in results)
    mp = sum(r['modal']['passed'] for r in results)
    print(f'Static: {sp}/{len(results)} PASS; modal: {mp}/{len(results)} PASS. Report: {output / "report.html"}')
    return int(sp<len(results) or mp<len(results))


if __name__=='__main__':
    raise SystemExit(main())
