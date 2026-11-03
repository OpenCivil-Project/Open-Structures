"""Collect three independently authored families into 150 native .mf files."""
import json
from pathlib import Path


def build_cases():
    from .beams import build_cases as beams
    from .mass_support import build_cases as mass
    from .frames import build_cases as frames
    cases = beams() + mass() + frames()
    cases.sort(key=lambda case:case['id'])
    numbers = [int(case['id'].split('_',1)[0]) for case in cases]
    if numbers != list(range(101,251)) or len({case['id'] for case in cases})!=150:
        raise ValueError('Expected exactly 150 new unique case IDs, numbered 101 through 250')
    return cases


def generate_cases(output_root):
    root=Path(output_root).resolve()
    cases=build_cases()
    for case in cases:
        folder=root/'cases'/case['id']
        folder.mkdir(parents=True,exist_ok=True)
        path=folder/(case['id']+'.mf')
        path.write_text(json.dumps(case['model'],indent=2,allow_nan=False)+'\n',encoding='utf-8')
        case.update(directory=str(folder),mf_path=str(path))
    return cases
