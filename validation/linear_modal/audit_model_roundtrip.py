"""Exercise GUI project deserialization/serialization without opening windows."""
import contextlib
import io
import json
import sys
from pathlib import Path
import numpy as np

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
for part in ('core/solver','core/solver/linear_static','core/solver/modal'):
    sys.path.append(str(ROOT/part))
from core.model import StructuralModel
from validation.linear_modal.models import generate_cases

HERE=Path(__file__).resolve().parent
work=HERE/'work'
work.mkdir(parents=True,exist_ok=True)
cases=generate_cases(work/'generator_smoke')
report=[]
for case in cases:
    original=case['model']
    out=Path(case['directory'])/'roundtrip.mf'
    try:
        model=StructuralModel('Roundtrip')
        with contextlib.redirect_stdout(io.StringIO()):
            model.load_from_file(case['mf_path'])
            model.save_to_file(str(out))
        saved=json.loads(out.read_text())
        for collection in ('nodes','elements','sections','materials','loads','links','link_properties'):
            assert len(saved[collection])==len(original[collection]),collection+' count'
        assert saved['info']['active_dofs']==original['info']['active_dofs']
        for collection,idkey in [('nodes','id'),('elements','id'),('sections','name'),('materials','name')]:
            a={r[idkey]:r for r in original[collection]}
            b={r[idkey]:r for r in saved[collection]}
            assert set(a)==set(b),collection+' IDs'
            for key,r in a.items():
                keys={'nodes':['x','y','z','restraints','spring_matrix'],
                      'elements':['n1_id','n2_id','sec_name','beta','rel_i','rel_j','off_i','off_j'],
                      'sections':['mat_name','properties'],
                      'materials':['E','G','rho','nu']}[collection]
                for field in keys:
                    if field not in r:
                        continue
                    av,bv=r[field],b[key][field]
                    if isinstance(av,dict):
                        for p,v in av.items():
                            assert np.isclose(v,bv[p],rtol=1e-12,atol=1e-15),(collection,key,field,p,v,bv[p])
                    elif isinstance(av,(float,int,list)):
                        assert np.allclose(av,bv,rtol=1e-12,atol=1e-15),(collection,key,field)
                    else:
                        assert av==bv,(collection,key,field)
        for collection in ('links','link_properties','mass_sources','load_patterns'):
            for a,b in zip(original[collection],saved[collection]):
                for field,av in a.items():
                    if isinstance(av,(float,int,list)):
                        if field in ('load_patterns',):
                            assert av==b[field]
                        else:
                            assert np.allclose(av,b[field],rtol=1e-12,atol=1e-15),(collection,field)
                    else:
                        assert av==b[field],(collection,field)
        for a,b in zip(original['loads'],saved['loads']):
            for field,av in a.items():
                if isinstance(av,(float,int,list)):
                    assert np.allclose(av,b[field],rtol=1e-12,atol=1e-15),('loads',field)
                else:
                    assert av==b[field],('loads',field)
        saved_cases={c['name']:c for c in saved['load_cases']}
        for a in original['load_cases']:
            b=saved_cases[a['name']]
            for field in ('name','type','loads','mass_source','num_modes'):
                if field in a:
                    assert a[field]==b[field],('load_cases',field)
        extra_cases=sorted(set(saved_cases)-{c['name'] for c in original['load_cases']})
        report.append({'id':case['id'],'status':'PASS','nodes':len(model.nodes),'elements':len(model.elements),
                       'extra_cases_created_by_loader':extra_cases})
    except Exception as exc:
        report.append({'id':case['id'],'status':'FAIL','error':str(exc)})
(HERE/'schema_roundtrip.json').write_text(json.dumps(report,indent=2)+'\n')
failed=[r for r in report if r['status']=='FAIL']
print(json.dumps({'total':len(report),'passed':len(report)-len(failed),'failed':failed},indent=2))
