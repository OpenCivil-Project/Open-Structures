"""Reuse the identical report/comparison conventions for the second batch."""
import json
from pathlib import Path
from validation.linear_modal.reports import write_reports as shared_reports


def write_reports(output, results, elapsed):
    shared_reports(output,results,elapsed)
    path=Path(output)
    page=path/'report.html'
    text=page.read_text(encoding='utf-8')
    text=text.replace('100 structural models,','150 new structural models (batch 2, IDs 101–250),')
    text=text.replace('<h1>OpenCivil linear static and modal verification</h1>',
                      '<h1>OpenCivil verification — 150 new models</h1>')
    page.write_text(text,encoding='utf-8')
    summary=json.loads((path/'summary.json').read_text(encoding='utf-8'))
    summary.update(batch='second_150',case_number_range=[101,250],
                   static_success_rate=summary['static_pass']/len(results),
                   modal_success_rate=summary['modal_pass']/len(results),
                   both_pass=sum(r['static']['passed'] and r['modal']['passed'] for r in results))
    (path/'summary.json').write_text(json.dumps(summary,indent=2,allow_nan=False)+'\n',encoding='utf-8')
