"""200 named numerical regression assertions for the saved solver run.

First run ``python -m validation.linear_modal.runner`` to generate fresh results.
Then ``python -m unittest validation.linear_modal.test_verification`` replays the
100 static and 100 modal comparisons against freshly calculated independent
references. Changed model/solver hashes invalidate the saved results.
"""
import json
from pathlib import Path
import unittest

from .reference import analyze
from .runner import compare, file_digest, solver_digest

HERE = Path(__file__).resolve().parent


class NumericalVerification(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        manifest = json.loads((HERE/'manifest.json').read_text(encoding='utf-8'))
        if len(manifest)!=100:
            raise AssertionError('Expected exactly 100 models; run validation.linear_modal.runner')
        cls.results = {}
        for record in manifest:
            path = HERE / record['mf_file']
            execution = json.loads((path.parent/'execution.json').read_text(encoding='utf-8'))
            if execution.get('model_sha256')!=file_digest(path) or execution.get('solver_source_sha256')!=solver_digest():
                raise AssertionError('Saved analysis is stale: '+record['id']+'; rerun validation.linear_modal.runner')
            case = {**record,'mf_path':path,'directory':path.parent,
                    'model':json.loads(path.read_text(encoding='utf-8'))}
            cls.results[record['id']] = compare(case,analyze(case['model'],spec=record.get('spec')))


def load_tests(loader, standard_tests, pattern):
    suite = unittest.TestSuite()
    if not (HERE/'manifest.json').exists():
        raise RuntimeError('Generate and solve the models with python -m validation.linear_modal.runner first')
    manifest = json.loads((HERE/'manifest.json').read_text(encoding='utf-8'))
    for record in manifest:
        for kind in ('static','modal'):
            name = 'test_' + kind + '_' + record['id']
            def test(self, cid=record['id'], analysis=kind):
                data = self.results[cid][analysis]
                self.assertTrue(data['passed'],json.dumps(data,indent=2))
            setattr(NumericalVerification,name,test)
            suite.addTest(NumericalVerification(name))
    return suite
