"""Plain JSON/CSV and a searchable, local HTML validation report."""
from collections import defaultdict
import csv
import html
import json
from pathlib import Path
import platform
import subprocess

import numpy
import scipy


def write_reports(output, results, elapsed):
    output = Path(output)
    static = sum(r['static']['passed'] for r in results)
    modal = sum(r['modal']['passed'] for r in results)
    try:
        commit = subprocess.check_output(['git','rev-parse','HEAD'],cwd=Path(__file__).resolve().parents[2],text=True).strip()
    except Exception:
        commit = 'unknown'
    summary = {'model_count':len(results),'static_pass':static,'static_fail':len(results)-static,
               'modal_pass':modal,'modal_fail':len(results)-modal,'elapsed_seconds':round(elapsed,2),
               'environment':{'python':platform.python_version(),'numpy':numpy.__version__,
                              'scipy':scipy.__version__,'git_commit':commit},'cases':results}
    warnings = [{'id':r['id'],'previous_attempts':r['execution']['previous_attempts']}
                for r in results if r.get('execution',{}).get('previous_attempts')]
    summary['execution_warnings'] = warnings
    (output/'summary.json').write_text(json.dumps(summary,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    def frequency_error(result):
        return next((c.get('value') for c in result['modal'].get('checks',[]) if c['name']=='maximum relative frequency error'),None)
    with (output/'summary.csv').open('w',newline='',encoding='utf-8') as stream:
        writer = csv.writer(stream)
        writer.writerow(['case','family','static','modal','maximum_relative_frequency_error','reference_error'])
        for r in results:
            writer.writerow([r['id'],r['family'],'PASS' if r['static']['passed'] else 'FAIL',
                             'PASS' if r['modal']['passed'] else 'FAIL',frequency_error(r),r.get('reference_error') or ''])
    families = defaultdict(lambda:[0,0,0])
    for r in results:
        f = families[r['family']]
        f[0]+=1; f[1]+=r['static']['passed']; f[2]+=r['modal']['passed']
    lines = ['# Linear static and modal verification', '',
             f'{len(results)} shared models; {static}/{len(results)} static PASS; {modal}/{len(results)} modal PASS.', '',
             'The reference is independent force-flexibility finite-element assembly. Continuum analytical comparisons are recorded separately in each expected.json. A numerical reference match alone does not establish convergence to continuum mechanics.', '',
             '| Family | Models | Static pass | Modal pass |','|---|---:|---:|---:|']
    for name,counts in families.items():
        lines.append(f'| {name} | {counts[0]} | {counts[1]} | {counts[2]} |')
    lines += ['','Failing cases:','']
    for r in results:
        if not r['static']['passed'] or not r['modal']['passed']:
            failures = []
            for kind in ('static','modal'):
                if not r[kind]['passed']:
                    checks = ', '.join(c['name'] for c in r[kind].get('checks',[]) if not c['passed'])
                    failures.append(f'{kind}: {r[kind].get("error",checks or "reference error")}')
            lines.append(f'- [{r["id"]}](cases/{r["id"]}/comparison.json): '+ '; '.join(failures))
    lines += ['',f'Runtime: {elapsed:.1f} seconds. Python {platform.python_version()}, NumPy {numpy.__version__}, SciPy {scipy.__version__}.',
              f'Git commit: {commit}. See summary.json for exact checks and tolerances.','']
    if warnings:
        lines += ['Prior execution failures preserved:','']
        for warning in warnings:
            lines.append(f'- {warning["id"]}: {warning["previous_attempts"]}; subsequent targeted rerun completed. See execution.json and run_history.json.')
        lines.append('')
    (output/'report.md').write_text('\n'.join(lines),encoding='utf-8')
    esc = html.escape
    rows = []
    for r in results:
        cid = r['id']
        sp = 'PASS' if r['static']['passed'] else 'FAIL'
        mp = 'PASS' if r['modal']['passed'] else 'FAIL'
        error = frequency_error(r)
        details = esc(json.dumps(r,indent=2,allow_nan=False))
        rows.append(f'<tr data-status="{"pass" if sp==mp=="PASS" else "fail"}" data-family="{esc(r["family"])}"><td><details><summary>{esc(cid)}</summary><pre>{details}</pre></details></td><td>{esc(r["family"])}</td><td class="{sp.lower()}">{sp}</td><td class="{mp.lower()}">{mp}</td><td>{"—" if error is None else f"{error:.3g}"}</td><td><a href="cases/{cid}/{cid}.mf">Model</a> · <a href="cases/{cid}/expected.json">Reference</a> · <a href="cases/{cid}/comparison.json">Checks</a> · <a href="cases/{cid}/{cid}_STATIC_results.json">Static</a> · <a href="cases/{cid}/{cid}_MODAL_results.json">Modal</a></td></tr>')
    family_rows = ''.join(f'<tr><td>{esc(name)}</td><td>{c[0]}</td><td>{c[1]}/{c[0]}</td><td>{c[2]}/{c[0]}</td></tr>' for name,c in families.items())
    document = '''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>OpenCivil validation</title>
<style>body{font:15px system-ui,sans-serif;color:#173044;background:#f4f7f9;margin:0}main{max-width:1400px;margin:auto;padding:32px}h1{font-size:30px;margin:0 0 12px}p{max-width:900px;line-height:1.5}.stats{display:flex;gap:16px;margin:24px 0}.stats div{background:white;border:1px solid #dae2e8;border-radius:8px;padding:18px;min-width:170px}.stats strong{font-size:26px;display:block}table{border-collapse:collapse;background:white;width:100%;margin:18px 0}th,td{text-align:left;padding:12px;border-bottom:1px solid #dde4e8;vertical-align:top}th{background:#173044;color:white;position:sticky;top:0}.pass{color:#0d7148;font-weight:700}.fail{color:#b52c30;font-weight:700}a{color:#075b8e}input,select{font:inherit;padding:9px;border:1px solid #bacbd7;border-radius:5px;margin-right:10px}pre{max-width:560px;max-height:460px;overflow:auto;font-size:12px;background:#eef3f7;padding:12px;white-space:pre-wrap}summary{cursor:pointer}details summary:hover{color:#075b8e}.muted{color:#627987;font-size:13px}#family{max-width:650px}</style>
<main><h1>OpenCivil linear static and modal verification</h1><p>100 structural models, each solved for linear static response and natural modes. Every model has its own .mf input, independent known solution, solver output, logs and numerical comparison.</p>
<div class="stats"><div><strong>__COUNT__</strong>shared models</div><div><strong>__STATIC__ / __COUNT__</strong>static pass</div><div><strong>__MODAL__ / __COUNT__</strong>modal pass</div></div>
<p>The reference uses independent force-flexibility assembly and a dense symmetric eigenproblem. Textbook continuum solutions are recorded separately; modal comparisons account for the application's lumped translational mass, artificial rotational mass and release regularization. Expand a case for exact errors and tolerances.</p>
<p><a href="README.md">Method and sources</a> · <a href="report.md">Text report</a> · <a href="summary.csv">CSV</a> · <a href="summary.json">Full JSON</a></p>
__WARNINGS__
<details id="family"><summary>Results by model family</summary><table><tr><th>Family</th><th>Count</th><th>Static</th><th>Modal</th></tr>__FAMILY__</table></details>
<p><input id="query" placeholder="Search case or family" aria-label="Search"><select id="status" aria-label="Filter"><option value="all">All cases</option><option value="fail">Any failure</option><option value="pass">Both pass</option></select><span id="visible"></span></p>
<table id="cases"><thead><tr><th>Case / details</th><th>Family</th><th>Static</th><th>Modal</th><th>Frequency relative error</th><th>Files</th></tr></thead><tbody>__ROWS__</tbody></table>
<p class="muted">Runtime __SECONDS__ seconds. No commercial-solver agreement is asserted. Saved reference values can be regenerated from the documented model parameters.</p></main>
<script>const query=document.getElementById('query'),status=document.getElementById('status'),rows=[...document.querySelectorAll('#cases tbody tr')];function filter(){let n=0;for(const r of rows){let show=(status.value==='all'||r.dataset.status===status.value)&&r.innerText.toLowerCase().includes(query.value.toLowerCase());r.hidden=!show;if(show)n++}document.getElementById('visible').textContent=n+' cases shown'}query.addEventListener('input',filter);status.addEventListener('change',filter);filter();</script></html>'''
    warning_html = ''.join(f'<p class="fail">Execution note: {esc(w["id"])} had a prior process failure {esc(str(w["previous_attempts"]))}; its targeted rerun completed. The earlier failure is preserved in execution.json and run_history.json.</p>' for w in warnings)
    for key,value in {'COUNT':len(results),'STATIC':static,'MODAL':modal,'FAMILY':family_rows,'ROWS':''.join(rows),'SECONDS':f'{elapsed:.1f}','WARNINGS':warning_html}.items():
        document = document.replace('__'+key+'__',str(value))
    (output/'report.html').write_text(document,encoding='utf-8')
