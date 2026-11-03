"""300 named assertions replaying the second batch's saved production results.

Run python -m validation.linear_modal_150.runner first, then
python -m unittest validation.linear_modal_150.test_verification.
"""
import json
from pathlib import Path
import unittest

from validation.linear_modal.runner import compare,file_digest,solver_digest
from .reference import analyze

HERE=Path(__file__).resolve().parent


class NumericalVerification150(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        manifest=json.loads((HERE/'manifest.json').read_text(encoding='utf-8'))
        if len(manifest)!=150:
            raise AssertionError('Expected 150 new models; run validation.linear_modal_150.runner')
        cls.results={}
        for record in manifest:
            path=HERE/record['mf_file']
            execution=json.loads((path.parent/'execution.json').read_text(encoding='utf-8'))
            if execution.get('model_sha256')!=file_digest(path) or execution.get('solver_source_sha256')!=solver_digest():
                raise AssertionError('Stale analysis for '+record['id']+'; rerun validation.linear_modal_150.runner')
            case={**record,'mf_path':path,'directory':path.parent,'model':json.loads(path.read_text(encoding='utf-8'))}
            cls.results[record['id']]=compare(case,analyze(case['model'],spec=record.get('spec')))


def load_tests(loader,standard_tests,pattern):
    if not (HERE/'manifest.json').exists():
        raise RuntimeError('Generate/solve the new models with python -m validation.linear_modal_150.runner first')
    manifest=json.loads((HERE/'manifest.json').read_text(encoding='utf-8'))
    suite=unittest.TestSuite()
    for record in manifest:
        for kind in ('static','modal'):
            name='test_'+kind+'_'+record['id']
            def test(self,cid=record['id'],analysis=kind):
                result=self.results[cid][analysis]
                self.assertTrue(result['passed'],json.dumps(result,indent=2))
            setattr(NumericalVerification150,name,test)
            suite.addTest(NumericalVerification150(name))
    return suite
