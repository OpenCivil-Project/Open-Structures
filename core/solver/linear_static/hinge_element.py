"""
hinge_element.py -- force-based (flexibility) fiber hinge, v4 (mixed formulation).

WHAT CHANGED vs v3 (the version that diverged past ~0.002 m):

  v3 solved for the 5 basic forces q and, inside every residual evaluation,
  INVERTED the fiber section (moment -> curvature) with a nested Newton.
  That inversion has no solution on a softening branch (M(kappa) is not
  monotonic once the tension fiber snaps), so the nested solve returned
  garbage exactly where the crack event happens.

  v4 never inverts the section.  Unknowns are y = [q (5), d (3)] where
  d = (eps0, kappa2, kappa3) is the section deformation AT the hinge:

      R1 (5) = v_target - [ F_el q + Lh * Sm^T (d - C Sm q) ]     compatibility
      R2 (3) = Sm q - s(d)                                        section equilibrium

  Sm (3x5) maps basic forces to the section resultants (N, M2h, M3h) at the
  hinge (unit-load / linear-moment shape), C = diag(1/EA, 1/EI22, 1/EI33)
  is the elastic section compliance.  The section is only ever evaluated
  FORWARD (state(d)), which is well defined on softening branches.

  Robustness: damped Newton (backtracking line search on a scaled residual
  norm), then continuation (adaptive sub-stepping of v from the last
  converged state, or from zero) if the direct solve fails.

  Consistent tangent: K_basic = dq/dv from the converged 8x8 Jacobian,
  K_local = Bv^T K_basic Bv + torsion (Bv = kinematic basic-deformation
  matrix; the equilibrium matrix is its transpose -- work conjugate).

ALSO FIXED: v3/v2 used eps0_el = N / (EA/L), which has units of length,
not strain (N/EA is the strain). It only mattered when N != 0 (e.g. axially
restrained pushover), where it corrupted the "extra" axial deformation.

Return signature is the ORIGINAL 3-tuple (f_local, K_local, N_axial), so
nonlinear_engine.py's two call sites work unchanged.  `residual_stiffness` overrides the module default RESIDUAL_STIFFNESS
(per load case, from nl_params['residual_stiffness']); None = module default.
Pass `state={}`
(a per-element dict) to get warm starts + diagnostics; pass
`return_info=True` for a 4th item with convergence info.
"""

import numpy as np
from element_library import get_local_stiffness_matrix

RESIDUAL_STIFFNESS = 1e-8
_ALPHA_REG = RESIDUAL_STIFFNESS

_STATIC_CACHE = {}
_STATIC_CACHE_MAX = 4096

def _kinematic_matrix(L):
    """Bv (5x12): v = Bv @ p_local, v = [e, th2i, th2j, th3i, th3j]."""
    Bv = np.zeros((5, 12))
    Bv[0, 0], Bv[0, 6] = -1.0, 1.0
    Bv[1, 4], Bv[1, 2], Bv[1, 8] = 1.0, -1.0 / L, 1.0 / L
    Bv[2, 10], Bv[2, 2], Bv[2, 8] = 1.0, -1.0 / L, 1.0 / L
    Bv[3, 5], Bv[3, 1], Bv[3, 7] = 1.0, 1.0 / L, -1.0 / L
    Bv[4, 11], Bv[4, 1], Bv[4, 7] = 1.0, 1.0 / L, -1.0 / L
    return Bv

class _HingeProblem:
    def __init__(self, fiber_section, xi, Lh, E, A, I22, I33, F_el, EA_L_unused=None, failed=None,
                 alpha_reg=None, _static=None, mat_state=None):
        self.fs = fiber_section
        self.mat_state = mat_state                                                         
        self.alpha = _ALPHA_REG if alpha_reg is None else float(alpha_reg)
        self.failed = failed
        self.Lh = Lh
        self.F_el = F_el
        self._last_y = None                                                          
        self._last_J = None
        if _static is not None:
                                                                            
            (self.kd, self.C, self.Sm, self.SmT, self.W, self.K_el_basic, self._J0) = _static
            return
        self.kd = np.array([E * A, E * I22, E * I33])
        self.C = np.diag(1.0 / self.kd)
        b = np.array([1.0 - xi, xi])
        Sm = np.zeros((3, 5))
        Sm[0, 0] = 1.0
        Sm[1, 1:3] = [-(1.0 - xi), xi]
        Sm[2, 3:5] = [-(1.0 - xi), xi]
        self.Sm = Sm
        self.SmT = Sm.T
        self.W = np.concatenate([np.ones(5), 1.0 / self.kd])                                  
        self.K_el_basic = np.linalg.inv(F_el)
                                                                               
        J0 = np.zeros((8, 8))
        J0[:5, :5] = -self.F_el + self.Lh * self.SmT @ self.C @ self.Sm
        J0[:5, 5:] = -self.Lh * self.SmT
        J0[5:, :5] = self.Sm
        self._J0 = J0

    def static_tuple(self):
        return (self.kd, self.C, self.Sm, self.SmT, self.W, self.K_el_basic, self._J0)

    def section(self, d):
        N, M2, M3, K = self.fs.state(d[0], d[1], d[2], failed=self.failed, mat_state=self.mat_state)
        s = np.array([N, M2, M3]) + self.alpha * self.kd * d
        K = K + self.alpha * np.diag(self.kd)
        return s, K

    def residual_jac(self, y, v_t):
        q, d = y[:5], y[5:]
        s, Ks = self.section(d)
        Sq = self.Sm @ q
        R1 = v_t - (self.F_el @ q + self.Lh * (self.SmT @ (d - self.C @ Sq)))
        R2 = Sq - s
        J = np.zeros((8, 8))
        J[:5, :5] = -self.F_el + self.Lh * self.SmT @ self.C @ self.Sm
        J[:5, 5:] = -self.Lh * self.SmT
        J[5:, :5] = self.Sm
        J[5:, 5:] = -Ks
        return np.concatenate([R1, R2]), J

    def residual(self, y, v_t):
        q, d = y[:5], y[5:]
        s, _ = self.section(d)
        Sq = self.Sm @ q
        R1 = v_t - (self.F_el @ q + self.Lh * (self.SmT @ (d - self.C @ Sq)))
        return np.concatenate([R1, Sq - s])

    def residual_K(self, y, v_t):
        """Identical R to residual(), plus the section tangent Ks evaluated on the
        way, so _newton can build the Jacobian at an accepted point without
        evaluating the fiber section a second time."""
        q, d = y[:5], y[5:]
        s, Ks = self.section(d)
        Sq = self.Sm @ q
        R1 = v_t - (self.F_el @ q + self.Lh * (self.SmT @ (d - self.C @ Sq)))
        return np.concatenate([R1, Sq - s]), Ks

    def jac_from_K(self, Ks):
        """Same J that residual_jac builds, given the section tangent Ks."""
        J = self._J0.copy()
        J[5:, 5:] = -Ks
        return J

    def elastic_guess(self, v_t):
        q = self.K_el_basic @ v_t
        return np.concatenate([q, self.C @ (self.Sm @ q)])

def _scaled_solve(J, rhs):
    """Row/column equilibrated solve; lstsq fallback if singular."""
    r = 1.0 / np.maximum(np.max(np.abs(J), axis=1), 1e-300)
    Jr = J * r[:, None]
    c = 1.0 / np.maximum(np.max(np.abs(Jr), axis=0), 1e-300)
    Js = Jr * c[None, :]
    try:
        y = np.linalg.solve(Js, rhs * r)
    except np.linalg.LinAlgError:
        y = np.linalg.lstsq(Js, rhs * r, rcond=None)[0]
    return y * c

def _scaled_solve_cols(J, B):
    """Column k of the result == _scaled_solve(J, B[:, k]), bit for bit: the row/
    column equilibration of J (identical for every column) is done once instead of
    once per column; each column is still its own np.linalg.solve on the same
    scaled matrix with the same scaled right-hand side."""
    r = 1.0 / np.maximum(np.max(np.abs(J), axis=1), 1e-300)
    Jr = J * r[:, None]
    c = 1.0 / np.maximum(np.max(np.abs(Jr), axis=0), 1e-300)
    Js = Jr * c[None, :]
    cols = []
    for k in range(B.shape[1]):
        bk = B[:, k] * r
        try:
            yk = np.linalg.solve(Js, bk)
        except np.linalg.LinAlgError:
            yk = np.linalg.lstsq(Js, bk, rcond=None)[0]
        cols.append(yk * c)
    return np.column_stack(cols)

_RHS_TANGENT = np.vstack([np.eye(5), np.zeros((3, 5))])

def _newton(prob, y0, v_t, tol, max_iter=60):
    y = y0.copy()
    R, J = prob.residual_jac(y, v_t)
    m = np.linalg.norm(prob.W * R)
    for it in range(max_iter):
        if np.max(np.abs(prob.W * R)) < tol:
            prob._last_y, prob._last_J = y, J                                   
            return y, True, it
        dy = _scaled_solve(J, -R)
        t, best = 1.0, None
        accepted = False
        for _ in range(8):
            y_try = y + t * dy
            R_try, K_try = prob.residual_K(y_try, v_t)
            m_try = np.linalg.norm(prob.W * R_try)
            if best is None or m_try < best[0]:
                best = (m_try, t, y_try, R_try, K_try)
            if m_try < (1.0 - 1e-4 * t) * m:
                accepted = True
                break
            t *= 0.5
        if not accepted:
                                                                                     
            if best[0] >= m:
                prob._last_y, prob._last_J = y, J
                return y, False, it
            m_try, t, y_try, R_try, K_try = best
        y = y_try
                                                                            
        R = R_try
        J = prob.jac_from_K(K_try)
        m = np.linalg.norm(prob.W * R)
    prob._last_y, prob._last_J = y, J
    return y, bool(np.max(np.abs(prob.W * R)) < tol), max_iter

def _continuation(prob, y_start, v_start, v_t, tol, h_min=1e-5):
    """March v from v_start to v_t with adaptive step; returns (y, ok, nsub)."""
    y, v_cur, s, h, nsub = y_start.copy(), v_start.copy(), 0.0, 1.0, 0
    while s < 1.0 - 1e-14:
        h = min(h, 1.0 - s)
        v_try = v_start + (s + h) * (v_t - v_start)
        y_try, ok, _ = _newton(prob, y, v_try, tol)
        nsub += 1
        if ok:
            y, s = y_try, s + h
            h *= 1.5
        else:
            h *= 0.5
            if h < h_min:
                return y, False, nsub
        if nsub > 2000:
            return y, False, nsub
    return y, True, nsub

def compute_hinge_element(fiber_section, hinge_rel_dist, hinge_length,
                          p_local, mat, sec, L, fef_local=None,
                          state=None, return_info=False, q_guess=None, failed=None,
                          residual_stiffness=None, mat_state=None):
    E, A, I22, I33 = mat['E'], sec['A'], sec['I22'], sec['I33']

    _key = (E, mat['G'], A, sec['J'], I22, I33, sec['As2'], sec['As3'], L,
            hinge_rel_dist, hinge_length)
    try:
        _hit = _STATIC_CACHE.get(_key)
    except TypeError:                                                          
        _key, _hit = None, None

    if _hit is not None:
        GJ_L, F_el, Bv, _static = _hit
        prob = _HingeProblem(fiber_section, hinge_rel_dist, hinge_length, E, A, I22, I33, F_el, failed=failed, mat_state=mat_state,
                             alpha_reg=residual_stiffness, _static=_static)
    else:
        k_el = get_local_stiffness_matrix(
            E=E, G=mat['G'], A=A, J=sec['J'], I22=I22, I33=I33,
            As2=sec['As2'], As3=sec['As3'], L=L, L_tor=L)
        GJ_L = k_el[3, 3]

        K2_el = np.array([[k_el[4, 4], k_el[4, 10]], [k_el[4, 10], k_el[4, 4]]])
        K3_el = np.array([[k_el[5, 5], k_el[5, 11]], [k_el[5, 11], k_el[5, 5]]])
        F_el = np.zeros((5, 5))
        F_el[0, 0] = L / (E * A)
        F_el[1:3, 1:3] = np.linalg.inv(K2_el)
        F_el[3:5, 3:5] = np.linalg.inv(K3_el)

        prob = _HingeProblem(fiber_section, hinge_rel_dist, hinge_length, E, A, I22, I33, F_el, failed=failed, mat_state=mat_state,
                             alpha_reg=residual_stiffness)
        Bv = _kinematic_matrix(L)
        if _key is not None:
            _static = prob.static_tuple()
            for _a in (F_el, Bv) + tuple(x for x in _static if isinstance(x, np.ndarray)):
                _a.flags.writeable = False
            if len(_STATIC_CACHE) >= _STATIC_CACHE_MAX:
                _STATIC_CACHE.clear()
            _STATIC_CACHE[_key] = (GJ_L, F_el, Bv, _static)
    v_t = Bv @ p_local
    vmax = max(np.max(np.abs(v_t)), 1e-9)
    tol = 1e-12 + 1e-9 * vmax

    st = state if state is not None else {}
    method, nsub = 'direct', 0

    y0 = st.get('y')
    y_direct0 = y0 if y0 is not None else prob.elastic_guess(v_t)
    
    y, ok, nit = _newton(prob, y_direct0, v_t, tol)

    if not ok:
        method = 'continuation'
        y_last = y0 if y0 is not None else np.zeros(8)
        if y0 is not None and 'v' in st:
            y, ok, nsub = _continuation(prob, y0, st['v'], v_t, tol)
            y_last = y
        if not ok:
            y, ok, nsub = _continuation(prob, np.zeros(8), np.zeros(5), v_t, tol, h_min=1e-7)
            method = 'continuation-from-zero'

    if ok:
        st['y'], st['v'] = y.copy(), v_t.copy()

    q = y[:5]
                                          
    if prob._last_y is y:
        J = prob._last_J                                                                    
    else:
        _, J = prob.residual_jac(y, v_t)
    X = _scaled_solve_cols(J, _RHS_TANGENT)                                                
    K_b = -X[:5, :]
    K_b = 0.5 * (K_b + K_b.T)

    N_total, M2i, M2j, M3i, M3j = q
    f_local = Bv.T @ q
    T = GJ_L * (p_local[3] - p_local[9])
    f_local[3] += T
    f_local[9] -= T

    K_local = Bv.T @ K_b @ Bv
    K_local[3, 3] += GJ_L; K_local[9, 9] += GJ_L
    K_local[3, 9] -= GJ_L; K_local[9, 3] -= GJ_L

    if fef_local is not None:
        f_local = f_local + fef_local

    if return_info:
        info = dict(converged=ok, method=method, nsub=nsub, q=q.copy(), d=y[5:].copy())
        return f_local, K_local, float(N_total), info
    return f_local, K_local, float(N_total)
