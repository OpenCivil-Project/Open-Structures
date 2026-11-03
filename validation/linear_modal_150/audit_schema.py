"""Load/save every new native project through the GUI model class, without UI."""
import contextlib
import io
import json
from pathlib import Path
import sys

import numpy as np

ROOT=Path(__file__).resolve().parents[2]
for relative in ('','core/solver','core/solver/linear_static','core/solver/modal'):
    sys.path.append(str(ROOT/relative))
from core.model import StructuralModel
from .models import generate_cases
from validation.linear_modal.runner import save_json

HERE=Path(__file__).resolve().parent


def main():
    cases=generate_cases(HERE/'work'/'schema')
    results=[]
    for case in cases:
        raw=case['model']
        path=Path(case['directory'])/'roundtrip.mf'
        try:
            model=StructuralModel('Roundtrip')
            with contextlib.redirect_stdout(io.StringIO()):
                model.load_from_file(case['mf_path'])
                model.save_to_file(str(path))
            saved=json.loads(path.read_text(encoding='utf-8'))
            for collection,key,fields in (
                ('nodes','id',('x','y','z','restraints','spring_matrix')),
                ('elements','id',('n1_id','n2_id','sec_name','beta','rel_i','rel_j','off_i','off_j','end_off_i','end_off_j','rz_factor')),
                ('materials','name',('E','G','rho','nu')),
                ('sections','name',('mat_name','properties','modifiers')),
                ('links','id',('prop_name','nodes','beta')),
                ('link_properties','name',('mass','weight','r1','r2','r3','stiffness')),
            ):
                before={r[key]:r for r in raw.get(collection,[])}
                after={r[key]:r for r in saved.get(collection,[])}
                assert set(before)==set(after),collection+' IDs'
                for identity,record in before.items():
                    for field in fields:
                        if field not in record:
                            continue
                        a,b=record[field],after[identity].get(field)
                        if isinstance(a,dict):
                            for subkey,value in a.items():
                                np.testing.assert_allclose(b[subkey],value,rtol=1e-10,atol=1e-10)
                        elif isinstance(a,str):
                            assert a==b,(collection,identity,field)
                        else:
                            np.testing.assert_allclose(b,a,rtol=1e-10,atol=1e-10)
            assert saved['info']['active_dofs']==raw['info']['active_dofs']
            assert len(saved['loads'])==len(raw['loads'])
            # The GUI may normalize default fields, but each explicit load value
            # and mode/source setting must survive the native project roundtrip.
            for before,after in zip(raw['loads'],saved['loads']):
                for key,value in before.items():
                    if key in ('projected','is_rel','is_relative') and key not in after:
                        continue
                    if isinstance(value,str):
                        assert after.get(key)==value,(key,value,after.get(key))
                    else:
                        np.testing.assert_allclose(after.get(key),value,rtol=1e-10,atol=1e-10)
            cases_after={c['name']:c for c in saved['load_cases']}
            for c in raw['load_cases']:
                for key,value in c.items():
                    assert cases_after[c['name']].get(key)==value,(c['name'],key)
            results.append({'id':case['id'],'status':'PASS'})
        except Exception as error:
            results.append({'id':case['id'],'status':'FAIL','error':str(error)})
    save_json(HERE/'schema_roundtrip.json',results)
    passed=sum(r['status']=='PASS' for r in results)
    print(f'GUI model schema roundtrip: {passed}/150 PASS')
    for result in results:
        if result['status']!='PASS':
            print(result['id'],result['error'])
    return int(passed!=150)


if __name__=='__main__':
    raise SystemExit(main())
