"""
fiber_hysteresis.py -- per-fiber cyclic (hysteresis) material law for fiber hinges.

WHAT THIS IS
    A stateful stress-strain rule for the fibers of ONE hinge, evaluated for all
    fibers at once (numpy, no per-fiber Python loop).  It replaces the plain
    "stress = backbone(strain)" lookup ONLY for fibers selected as hysteretic
    (default: concrete-like backbones).  Every other fiber, and every fiber that
    has never reversed, returns exactly what the backbone lookup returns.

DESIGN (matches the chaining / snapshot machinery already in the solver)
    * PURE evaluate():   sigma, tangent, new_state = H.evaluate(eps, state)
      It never mutates `state`.  Newton iterations call it with the COMMITTED
      state and a trial strain, as often as they like.
    * COMMIT = keep new_state.  The solver stores the new_state returned for the
      converged strain of an ACCEPTED step into hinge['mat_state'], in the same
      place it commits the snapped-fiber mask.  Rejecting a step = simply not
      storing it (and the snapshot/restore of PERSISTENT_HINGE_KEYS rolls back
      anything already stored).
    * state is a plain dict of ndarrays, so nl_chaining_and_disp_control's
      capture_hinge_state / apply_hinge_state (key 'mat_state') carry it from one
      load case to the next with no further change.

THE RULE (Takeda-type, calibrated on SAP2000 v21 Grav / Grav-1 fiber output)
    Per fiber, along the backbone ("envelope") nothing changes.  On a strain
    reversal at (eps_r, sig_r):

      1. UNLOAD line: from the reversal point with the INITIAL tangent of the
         side the stress is on (tension: k_t0, compression: k_c0, ~0.98 E in the
         SAP model) down to zero stress at the residual strain
              eps_z = eps_r - sig_r / k_u .
      2. RELOAD line: from (eps_z, 0) in a straight line to the TARGET point on
         the opposite side, then rejoin the backbone there.
         Target = the largest strain previously reached on that side (point on
         the backbone); if that side was never loaded beyond its first kink, the
         target is the FIRST KINK of that side's backbone (end of the first
         linear segment).  SAP data: the reload lines of the tension-side fibers
         all aim at (-2.0e-4, -6.27 MPa) = first compression kink, those of the
         compression fibers at (1.03e-4, 3.29 MPa) = first tension kink (crack
         peak).
      3. No crack-closure gap: a cracked fiber carries compression immediately
         (that is what SAP does, so we copy it).
      4. A reversal on a branch (reload line) is treated exactly like one on the
         backbone: if it heads back toward zero stress it first unloads along the
         initial tangent of the side its stress is on (verified: fiber 25 in
         Grav-2 leaves its Grav-1 end state at ~31 GPa up to zero stress), then
         heads in a straight line for the largest strain previously reached on
         the side it moves toward (verified: Grav-2 compression fibers reload
         toward their Grav peak, tension fibers toward their Grav peak).  A
         reversal whose stress already has the heading's sign (partial
         unload/reload before reaching zero stress) goes straight to that peak
         (classic Takeda; NOT yet checked against SAP).

    VALIDATED against SAP (Grav -> Grav-1 -> Grav-2 -> Grav-3): backbone loading,
    unload line, residual strain, reload toward a never-loaded side's first kink,
    reload toward the largest previous strain, unload from a reload branch.
    NOT YET VALIDATED: reversal before reaching zero stress (partial cycles),
    and cycles that go PAST the previous peak on the opposite side after an
    earlier larger excursion (needs a +/- amplitude-growing SAP run).

UNITS: whatever the backbone uses (the solver's backbones are SI, Pa).
"""

import numpy as np

_KINK_TOL = 0.02
                                                                              
REVERSAL_TOL = 1e-10

_STATE_KEYS = ('eps_c', 'sig_c', 'dir', 'onenv',
               'e0', 's0', 'e1', 's1', 'e2', 's2',
               'pk_pos_e', 'pk_pos_s', 'pk_neg_e', 'pk_neg_s')

def first_kinks(points, tol=_KINK_TOL):
    """
    For one backbone [(strain, stress), ...] sorted ascending, returns
        (e_t, s_t, k_t, e_c, s_c, k_c)
    = first kink (end of the first linear segment) and initial tangent on the
    tension side (+) and on the compression side (-).  A side with no points
    returns zeros for its kink and the other side's tangent as tangent.
    """
    pts = sorted((float(a), float(b)) for a, b in points)
    s = np.array([p[0] for p in pts]); f = np.array([p[1] for p in pts])
                                        
    f0 = float(np.interp(0.0, s, f))

    def side(sign):
        if sign > 0:
            idx = [i for i in range(len(s)) if s[i] > 0.0]
            seq = [(0.0, f0)] + [(s[i], f[i]) for i in idx]
        else:
            idx = [i for i in range(len(s)) if s[i] < 0.0][::-1]
            seq = [(0.0, f0)] + [(s[i], f[i]) for i in idx]
        if len(seq) < 2:
            return None
        e_prev, f_prev = seq[0]
        e1, f1 = seq[1]
        k0 = (f1 - f_prev) / (e1 - e_prev)
        ek, fk = e1, f1
        for j in range(2, len(seq)):
            ej, fj = seq[j]
            kj = (fj - fk) / (ej - ek) if ej != ek else np.inf
            if abs(kj - k0) > tol * max(abs(k0), 1e-30):
                break
            ek, fk = ej, fj
        return ek, fk, k0

    t = side(+1)
    c = side(-1)
    if t is None and c is None:
        return (0.0, 0.0, 1.0, 0.0, 0.0, 1.0)
    if t is None:
        t = (0.0, 0.0, c[2])
    if c is None:
        c = (0.0, 0.0, t[2])
    return (t[0], t[1], t[2], c[0], c[1], c[2])

def _looks_like_concrete(points):
    """Default selector: unsymmetric backbone whose tension strength is small
    compared with its compression strength (rebar / steel are ~symmetric)."""
    f = np.array([p[1] for p in points], dtype=float)
    fmax, fmin = f.max(), f.min()
    return fmin < 0.0 and fmax >= 0.0 and fmax < 0.3 * abs(fmin)

def _make_envelope(backbones):
    """Vectorized backbone lookup, same semantics as
    fiber_section.backbone_lookup (clamp beyond both table ends with ZERO
    tangent, exact hit on a point -> segment after it)."""
    n_f = len(backbones)
    groups = {}
    for i, bb in enumerate(backbones):
        groups.setdefault(id(bb), (bb, []))[1].append(i)
    tables = []
    for bb, idx in groups.values():
        s = np.array([p[0] for p in bb], dtype=float)
        f = np.array([p[1] for p in bb], dtype=float)
        ds = np.diff(s)
        nz = ds != 0.0
        tan = np.where(nz, np.diff(f) / np.where(nz, ds, 1.0), 0.0)
        tables.append((np.array(idx), s, f, tan))

    def env(eps):
        sig = np.zeros(n_f); tg = np.zeros(n_f)
        for idx, s, f, tan in tables:
            e = eps[idx]
            n = len(s)
            if n == 1:
                sig[idx] = f[0]; continue
            i = np.searchsorted(s, e, side='left')
            ic = np.minimum(i, n - 1)
            j = np.where(s[ic] == e, ic, i - 1)
            j = np.clip(j, 0, n - 2)
            t = tan[j]
            sg = f[j] + t * (e - s[j])
            hi = e >= s[-1]; sg[hi] = f[-1]; t = np.where(hi, 0.0, t)
            lo = e <= s[0]; sg[lo] = f[0]; t = np.where(lo, 0.0, t)
            sig[idx] = sg; tg[idx] = t
        return sig, tg

    return env

class FiberHysteresis:
    """Hysteresis law for the N fibers of one hinge."""

    def __init__(self, backbones, hysteretic=None, envelope=None, rev_tol=REVERSAL_TOL):
        """
        backbones  : list (len N) of [(strain, stress), ...] sorted ascending
        hysteretic : bool mask (len N) of fibers that get the Takeda rule.
                     None -> concrete-like backbones (see _looks_like_concrete).
        envelope   : optional callable eps(N,) -> (stress(N,), tangent(N,)); pass
                     FiberSection._lookup_all so the backbone is bit-identical to
                     the solver's own lookup.  None -> built here.
        """
        self.n = len(backbones)
        self._env = envelope if envelope is not None else _make_envelope(backbones)
        if hysteretic is None:
            hysteretic = [_looks_like_concrete(b) for b in backbones]
        self.active = np.asarray(hysteretic, dtype=bool)
        self.rev_tol = float(rev_tol)

        kc = {}
        et = np.zeros(self.n); st_ = np.zeros(self.n); kt = np.ones(self.n)
        ec = np.zeros(self.n); sc = np.zeros(self.n); kcn = np.ones(self.n)
        for i, bb in enumerate(backbones):
            key = id(bb)
            if key not in kc:
                kc[key] = first_kinks(bb)
            et[i], st_[i], kt[i], ec[i], sc[i], kcn[i] = kc[key]
        self.k1_e_t, self.k1_s_t, self.k0_t = et, st_, kt                                        
        self.k1_e_c, self.k1_s_c, self.k0_c = ec, sc, kcn                                            

    @classmethod
    def from_fiber_section(cls, fs, hysteretic=None, **kw):
        """Build from a fiber_section.FiberSection (uses its own envelope lookup)."""
        return cls(fs._backbones, hysteretic=hysteretic, envelope=fs._lookup_all, **kw)

    def init_state(self):
        z = np.zeros(self.n)
        return {
            'eps_c': z.copy(), 'sig_c': z.copy(), 'dir': z.copy(),
            'onenv': np.ones(self.n, dtype=bool),
            'e0': z.copy(), 's0': z.copy(), 'e1': z.copy(), 's1': z.copy(),
            'e2': z.copy(), 's2': z.copy(),
            'pk_pos_e': self.k1_e_t.copy(), 'pk_pos_s': self.k1_s_t.copy(),
            'pk_neg_e': self.k1_e_c.copy(), 'pk_neg_s': self.k1_s_c.copy(),
        }

    def evaluate(self, eps, state):
        """
        eps   : (N,) trial fiber strains
        state : COMMITTED state (never modified)
        Returns (sigma (N,), tangent (N,), new_state).  new_state is what to
        store if (and only if) this strain belongs to an accepted step.
        """
        eps = np.asarray(eps, dtype=float)
        sig_env, tan_env = self._env(eps)
        sig = sig_env.copy(); tan = tan_env.copy()

        S = {k: state[k].copy() for k in _STATE_KEYS}
        d = eps - S['eps_c']
        sgn = np.where(np.abs(d) > self.rev_tol, np.sign(d), 0.0)
        dirc = S['dir']
        hd = np.where(sgn != 0.0, sgn, dirc)                             
        rev = self.active & (dirc != 0.0) & (sgn != 0.0) & (sgn != dirc)

        if np.any(rev):
            ir = np.nonzero(rev)[0]
            ec, sc, h = S['eps_c'][ir], S['sig_c'][ir], hd[ir]
            from_env = S['onenv'][ir]
            te = np.where(h > 0, S['pk_pos_e'][ir], S['pk_neg_e'][ir])
            ts = np.where(h > 0, S['pk_pos_s'][ir], S['pk_neg_s'][ir])
            ku = np.where(sc > 0, self.k0_t[ir], self.k0_c[ir])
            toward_zero = ((sc > 0) & (h < 0)) | ((sc < 0) & (h > 0))
            unl = toward_zero                                                                       
                                                                                                           
            ez = ec - sc / ku
            e1 = np.where(unl, ez, ec)
            s1 = np.where(unl, 0.0, sc)
                                                                        
            ok = h * (te - e1) > 0.0
            e2 = np.where(ok, te, e1)
            s2 = np.where(ok, ts, s1)
            S['e0'][ir], S['s0'][ir] = ec, sc
            S['e1'][ir], S['s1'][ir] = e1, s1
            S['e2'][ir], S['s2'][ir] = e2, s2
            S['onenv'][ir] = False

        S['dir'] = hd.copy()                                                                      

        on = self.active & ~S['onenv']
        if np.any(on):
            io = np.nonzero(on)[0]
            h = np.where(S['dir'][io] != 0.0, S['dir'][io], 1.0)
            e0, s0 = S['e0'][io], S['s0'][io]
            e1, s1 = S['e1'][io], S['s1'][io]
            e2, s2 = S['e2'][io], S['s2'][io]
            x = eps[io]
            prog = h * (x - e0)
            b1 = h * (e1 - e0)
            b2 = h * (e2 - e0)
            with np.errstate(divide='ignore', invalid='ignore'):
                k01 = np.where(b1 > 0.0, (s1 - s0) / (e1 - e0), 0.0)
                k12 = np.where(b2 > b1, (s2 - s1) / (e2 - e1), 0.0)
            seg1 = (prog <= b1) & (b1 > 0.0)
            seg2 = ~seg1 & (prog <= b2)
            beyond = ~seg1 & ~seg2
            sg = np.where(seg1, s0 + k01 * (x - e0),
                          np.where(seg2, s1 + k12 * (x - e1), sig_env[io]))
            tg = np.where(seg1, k01, np.where(seg2, k12, tan_env[io]))
            sig[io] = sg
            tan[io] = tg
            S['onenv'][io[beyond]] = True                                                  

        up = self.active & (eps > S['pk_pos_e'])
        S['pk_pos_e'] = np.where(up, eps, S['pk_pos_e'])
        S['pk_pos_s'] = np.where(up, sig, S['pk_pos_s'])
        dn = self.active & (eps < S['pk_neg_e'])
        S['pk_neg_e'] = np.where(dn, eps, S['pk_neg_e'])
        S['pk_neg_s'] = np.where(dn, sig, S['pk_neg_s'])

        S['eps_c'] = eps.copy()
        S['sig_c'] = sig.copy()
        return sig, tan, S
