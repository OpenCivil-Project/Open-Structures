"""Generate and verify the next 150 shared static/modal models without a GUI.

From the repository: python -m validation.linear_modal_150.runner
The original 100-model inputs/results are kept in their existing suite folder.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
from pathlib import Path
import time
import traceback

import numpy as np

from validation.linear_modal.runner import (analytical_checks, compare, run_one,
                                          save_json, file_digest, solver_digest)
from .models import generate_cases
from .reference import analyze
from .reports import write_reports

HERE=Path(__file__).resolve().parent


def calculate_reference(case):
    ref=analyze(case['model'],spec=case.get('spec'))
    expected=ref['expected']
    formula_checks=(analytical_checks(expected['static'],case.get('spec'),'static')+
                    analytical_checks({'tables':{'periods':[{'f':float(f)} for f in ref['frequencies_regularized']]}},case.get('spec'),'modal'))
    expected['analytical_reference_checks']=formula_checks
    expected['metadata']['batch']='second_150'
    expected['metadata']['case_id']=case['id']
    expected['metadata']['model_sha256']=file_digest(case['mf_path'])
    expected['metadata']['reference_source_sha256']=file_digest(HERE.parent/'linear_modal'/'reference.py')
    expected['metadata']['reference_wrapper_sha256']=file_digest(HERE/'reference.py')
    save_json(Path(case['directory'])/'expected.json',expected)
    if any(not c['passed'] for c in formula_checks):
        raise ValueError('Analytical formula disagrees with independent reference: '+
                         str([c for c in formula_checks if not c['passed']]))
    if np.any(ref['frequencies_regularized'][:3]<=0) or not np.all(np.isfinite(ref['frequencies_regularized'][:3])):
        raise ValueError('Reference has nonpositive/nonfinite modes; model must be corrected before measuring production')
    return ref


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,default=HERE)
    parser.add_argument('--jobs',type=int,default=2)
    parser.add_argument('--timeout',type=int,default=90)
    parser.add_argument('--generate-only',action='store_true')
    parser.add_argument('--case',help='Run one new case ID, while generating all 150 model files')
    parser.add_argument('--compare-only',action='store_true',help='Recalculate comparisons from the saved production run')
    args=parser.parse_args(argv)
    output=args.output.resolve()
    output.mkdir(parents=True,exist_ok=True)
    cases=generate_cases(output)
    manifest=[{'id':c['id'],'family':c['family'],'variant':c['variant'],
               'mf_file':str(Path(c['mf_path']).relative_to(output)),'spec':c.get('spec',{})} for c in cases]
    save_json(output/'manifest.json',manifest)
    selected=[c for c in cases if not args.case or c['id']==args.case]
    if not selected:
        parser.error('Unknown case ID')
    started=time.time()
    refs,errors={},{}
    for case in selected:
        try:
            refs[case['id']]=calculate_reference(case)
        except Exception:
            errors[case['id']]=traceback.format_exc()
            save_json(Path(case['directory'])/'reference_error.json',{'error':errors[case['id']]})
    save_json(output/'reference_integrity.json',{
        'case_count':len(selected),'valid':len(refs),'errors':errors,
        'scalar_analytical_static_checks':sum(len(c.get('spec',{}).get('analytical_static',[])) for c in selected),
        'scalar_analytical_modal_checks':sum(len(c.get('spec',{}).get('analytical_modal',[])) for c in selected)})
    if errors:
        print(f'Reference preparation failed for {len(errors)} models; correct the models/reference before measuring solver success.')
        for cid,error in errors.items():
            print(cid,error.splitlines()[-1],flush=True)
        return 2
    if args.generate_only:
        print(f'Generated 150 new models and {len(refs)} verified independent reference solutions.')
        return 0
    if not args.compare_only:
        with ThreadPoolExecutor(max_workers=max(1,args.jobs)) as pool:
            pending={pool.submit(run_one,c,args.timeout):c for c in selected}
            for count,future in enumerate(as_completed(pending),1):
                case=pending[future]
                save_json(Path(case['directory'])/'execution.json',future.result())
                print(f'[{count}/{len(selected)}] {case["id"]} solver finished',flush=True)
    results=[]
    for case in selected:
        result=compare(case,refs[case['id']])
        save_json(Path(case['directory'])/'comparison.json',result)
        results.append(result)
    write_reports(output,results,time.time()-started)
    sp=sum(r['static']['passed'] for r in results)
    mp=sum(r['modal']['passed'] for r in results)
    both=sum(r['static']['passed'] and r['modal']['passed'] for r in results)
    print(f'NEW BATCH: static {sp}/{len(results)} ({sp/len(results):.2%}); modal {mp}/{len(results)} ({mp/len(results):.2%}); both {both}/{len(results)}.')
    return int(sp<len(results) or mp<len(results))


if __name__=='__main__':
    raise SystemExit(main())
