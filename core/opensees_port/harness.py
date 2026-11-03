                                                                                    
import sys, copy, io, contextlib
sys.path.insert(0, '/home/claude/proj')
import numpy as np
from core.opensees_port import OS_OP
from core.opensees_port.OS_OP import OpenCivilToOpenSees, load_oc_model

def run_case(mf='/mnt/user-data/uploads/Peer.mf', case='Cyclic', opensees_over=None, mat_over=None,
             nl_over=None, builder_over=None, shear_over=None):
    oc = copy.deepcopy(load_oc_model(mf))
    lcs = {l['name']: l for l in oc['load_cases']}
    if opensees_over: lcs[case].setdefault('opensees', {}).update(opensees_over)
    if shear_over and lcs[case]['opensees'].get('shear_spring'):
        lcs[case]['opensees']['shear_spring'].update(shear_over)
    if nl_over: lcs[case].setdefault('nl_params', {}).update(nl_over)
    if mat_over: mat_over(oc)
    chain, cur = [], case
    while cur:
        chain.insert(0, cur)
        lc = lcs[cur]
        cur = (lc.get('nl_params') or {}).get('continue_from_case') or lc.get('continue_from_case')
    rank = {"None": 0, "P-Delta": 1, "Large Displacements": 2}
    kinds = ["Linear", "PDelta", "Corotational"]
    worst = max(rank.get(lcs[c].get('geom_nonlin', 'None'), 0) for c in chain)
    blk = dict(OpenCivilToOpenSees.NL_DEFAULT_BLOCK); blk.update(lcs[case].get('opensees') or {})
    radau = str(blk.get('integration', 'Lobatto')).lower().startswith('hinge')
    lp = float(blk.get('hinge_length') or 0.0)
    conv = OpenCivilToOpenSees(oc)
    conv.enable_nonlinear(kinds[worst], blk['fiber_size_ratio'], blk['n_int_pts'],
        hinge="radau" if radau else "lobatto", hinge_lp=lp if (radau and lp > 0) else None,
        bar_slip=bool(blk.get('bar_slip', False)),
        shear_spring=blk.get('shear_spring') or None,
        slip_concrete=blk.get('slip_concrete', 'stiff'),
        slip_R=float(blk.get('slip_R', 0.5)), slip_b=float(blk.get('slip_b', 0.3)),
        slip_sy_mult=float(blk.get('slip_sy_mult', 1.0)), slip_su_mult=float(blk.get('slip_su_mult', 35.0)))
    for k, v in (builder_over or {}).items(): setattr(conv._nl_builder, k, v)
    with contextlib.redirect_stdout(io.StringIO()):
        conv.build_model()
        info = conv.run_nonlinear_static_chain(chain, lambda m, p: None, want_states=False)
    h = info['history']; dof = info['control_dof']
    u = np.array(h['u']) * 1e3
    V = np.array([-b[dof - 1] for b in h['base']]) / 1e3
    return u, V, info, conv, oc
