"""
shell_element.py  --  4-node flat shell (MITC4) for the MetuFire solver.

Scope: linear static (+ lumped mass for modal). Homogeneous isotropic,
user-meshed 4-node quads only.

Formulation (per element, in its own local frame, 6 DOF/node = 24 DOF):
  * Bending (THIN types)       : user choice PER SECTION (sec['thin_formulation']):
        "DKQ"   True Kirchhoff: Discrete Kirchhoff Quadrilateral (Batoz &
                Tahar 1982), 2x2 Gauss. The thin-plate element SAP2000 uses;
                verified to reproduce SAP2000 plate/shell-thin results to the
                printed precision. DEFAULT.
        "MITC4" Reissner-Mindlin with MITC4 shear tying (Bathe-Dvorkin) and the
                shear stiffness multiplied by THIN_SHEAR_FACTOR (thin limit).
                No locking, one formulation for thin and thick.
    Sections without the key fall back to USE_DKQ_FOR_THIN.
  * Bending + transverse shear : (THICK types) Reissner-Mindlin, MITC4 shear
                                 tying (Bathe-Dvorkin) -> no shear locking.
                                 Always MITC4; the thin option does not apply.
  * Membrane                   : bilinear Q4 + Wilson-Taylor incompatible
                                 modes (statically condensed, Taylor
                                 correction for distorted quads).
  * Drilling (rot. about normal): Hughes-Brezzi style rotation-coupling
                                 penalty  gamma * (omega - theta_z)^2, which
                                 keeps the rigid-body mode exact (no spurious
                                 stiffness in a rigid rotation about the normal).
                                 The penalty is sampled at the four EDGE
                                 MIDPOINTS (not at Gauss points) with
                                 gamma = G * t_m / 3 -- this is what reproduces
                                 SAP2000's in-plane rotational restraint at
                                 supports (Mz reactions and the support-couple
                                 Fx reactions), see _k_drilling.

Shell types (ShellSection.shell_type):
    "Shell - Thin" / "Shell - Thick"  membrane + bending
    "Plate - Thin" / "Plate Thick"    bending only
    "Membrane"                        membrane only
    Thin  = shear stiffness multiplied by THIN_SHEAR_FACTOR (shear
            deformation effectively suppressed, i.e. Kirchhoff limit).
    Thick = true Reissner-Mindlin shear (kappa = 5/6).
    "Shell - Layered/Nonlinear", Plane and Asolid sections are NOT supported
    (SolverException E208).  Tributary Area slabs are skipped (not FEM).

Local axes (CSI convention): local 3 = normal from node order (right-hand
rule, from the cross product of the diagonals); local 2 = projection of
global +Z on the element plane (global +Y if the element is horizontal);
local 1 = 2 x 3.  Rotated about local 3 by the section's material_angle.

Insertion offset (cardinal point): a single signed distance `offset` along local 3
between the drawn joints and the shell mid-surface (positive = toward +local 3).
The mid-surface moves rigidly with the joint:  u_mid = u_node + theta x d,
d = (0, 0, offset) in local axes (same 6x6 block as the frame eccentricity matrix).
  * stiffness : k_local <- Tecc' k_local Tecc
  * loads     : force F acting on the mid-surface -> force F + moment (d x F) at the node
  * recovery  : strains/resultants are computed from u_mid, xyz is reported at the mid-surface
Plate-only sections are unaffected (uz, rx, ry map onto themselves); membrane/shell
sections pick up the offset coupling (composite action with adjacent frames).
Mass is NOT transformed (translational mass stays at the node).

Units: the solver is SI-internal; nothing here is unit aware.
"""
import numpy as np
from error_definitions import SolverException

G_ACC = 9.80665

KAPPA_S = 5.0 / 6.0                                            
THIN_SHEAR_FACTOR = 1.0e3                                                      
DRILL_W0 = 2.0 / 5.0                                                                            
DRILL_W2 = 0.0072                                                                                                                                                                                                                   
STAB_EPS = 1.0e-10                                                                                                   
                                                                                                    
USE_DKQ_FOR_THIN = True                                                                                
                                                                                          
BATCH_SHELL_BUILD = True                                                                                                
_SHELL_CHUNK = 1024                                             

_GP = 1.0 / np.sqrt(3.0)
_GAUSS = [(-_GP, -_GP), (_GP, -_GP), (_GP, _GP), (-_GP, _GP)]                   

def _N(r, s):
    return 0.25 * np.array([(1 - r) * (1 - s), (1 + r) * (1 - s),
                            (1 + r) * (1 + s), (1 - r) * (1 + s)])

def _dN(r, s):
    """(2,4): row 0 = dN/dr, row 1 = dN/ds"""
    return 0.25 * np.array([[-(1 - s), (1 - s), (1 + s), -(1 + s)],
                            [-(1 - r), -(1 + r), (1 + r), (1 - r)]])

def _cross3(a, b):
    """3-vector cross product with the same arithmetic as np.cross (bit-identical result),
    without np.cross's per-call overhead (it dominated element setup for large meshes)."""
    return np.array([a[1] * b[2] - a[2] * b[1],
                     a[2] * b[0] - a[0] * b[2],
                     a[0] * b[1] - a[1] * b[0]])

def local_axes(P, beta_deg=0.0):
    """P: (4,3) node coords. Returns R (3,3), rows = local 1,2,3 in global axes."""
    P = np.asarray(P, dtype=float)
    n = _cross3(P[2] - P[0], P[3] - P[1])
    nn = np.linalg.norm(n)
    if nn < 1e-14:
        raise ValueError("degenerate (zero-area) quad")
    e3 = n / nn
    if abs(e3[2]) > 1.0 - 1e-9:                                
        e2 = np.array([0.0, 1.0, 0.0])
    else:
        e2 = np.array([0.0, 0.0, 1.0]) - e3[2] * e3
        e2 /= np.linalg.norm(e2)
    e1 = _cross3(e2, e3)
    if beta_deg:
        b = np.radians(beta_deg)
        c, s = np.cos(b), np.sin(b)
        e1, e2 = c * e1 + s * e2, -s * e1 + c * e2
    return np.array([e1, e2, e3])

def _mod(mods, key, default=1.0):
    """tolerant stiffness-modifier lookup (case-insensitive)"""
    if not mods:
        return default
    for k, v in mods.items():
        if str(k).lower() == key:
            try:
                return float(v)
            except (TypeError, ValueError):
                return default
    return default

class ShellElement:
    def __init__(self, eid, node_indices, coords, E, nu, rho, sec, offset=0.0, _defer_build=False):
        """
        sec: dict(name, shell_type, tm, tb, angle, mods)
        offset: insertion offset along local 3 (length, + = toward local 3)
        """
        self.id = eid
        self.node_indices = list(node_indices)
        self.coords = np.asarray(coords, dtype=float)
        self.E, self.nu, self.rho = float(E), float(nu), float(rho)
        self.sec = sec
        st = sec['shell_type'].lower()
        self.has_membrane = ('membrane' in st) or ('shell' in st)
        self.has_bending = ('plate' in st) or ('shell' in st)
        self.is_thin = 'thin' in st
        self.tm = float(sec['tm'])
        self.tb = float(sec['tb'])
        mods = sec.get('mods') or {}
        self.mods = mods

        try:
            self.R = local_axes(self.coords, sec.get('angle', 0.0))
        except ValueError:
            raise SolverException("E207", f"Shell {eid}: zero-area / degenerate quad.")
        c = self.coords.mean(axis=0)
        self.xy = (self.coords - c) @ self.R[:2].T                                       

        self.dof_map = [6 * i + k for i in self.node_indices for k in range(6)]
        self.T = _blockdiag3(self.R, 8)                                          

        self.offset = float(offset or 0.0)
        self.d_global = self.offset * self.R[2]                                                
        self.Tecc = None                                                                 
        if self.offset != 0.0:
            A = np.eye(6)
            A[0, 4] = self.offset
            A[1, 3] = -self.offset
            self.Tecc = np.kron(np.eye(4), A)
        if not _defer_build:
            self._build()

    def _jac(self, r, s):
        J = _dN(r, s) @ self.xy
        det = J[0, 0] * J[1, 1] - J[0, 1] * J[1, 0]
        return J, det

    def _build(self):
        xy = self.xy
        E, nu = self.E, self.nu
        G = E / (2 * (1 + nu))
        mods = self.mods
                                   
        self.gp = []
        area = 0.0
        for (r, s) in _GAUSS:
            J, det = self._jac(r, s)
            if det <= 1e-14 * max(1.0, abs(J).max() ** 2):
                raise SolverException(
                    "E207", f"Shell {self.id}: non-positive Jacobian (concave / badly shaped quad).")
            self.gp.append((r, s, J, det))
            area += det
        self.area = area

        K = np.zeros((24, 24))
        self._alpha_map = None
        if self.has_membrane:
            K += self._k_membrane(G)
            K += self._k_drilling(G)
        if self.has_bending:
            K += self._k_bending(G)
        K += self._k_stabilization(G)
        if self.Tecc is not None:
            K = self.Tecc.T @ K @ self.Tecc
        self.k_local = 0.5 * (K + K.T)
        self.k_global = self.T.T @ self.k_local @ self.T

    def _Dm(self):
        E, nu, t = self.E, self.nu, self.tm
        m = self.mods
        f11, f22, f12 = _mod(m, 'f11'), _mod(m, 'f22'), _mod(m, 'f12')
        c = E / (1 - nu ** 2)
        return t * c * np.array([[f11, nu * np.sqrt(f11 * f22), 0.0],
                                 [nu * np.sqrt(f11 * f22), f22, 0.0],
                                 [0.0, 0.0, (1 - nu) / 2 * f12]])

    def _k_membrane(self, G):
        D = self._Dm()
        J0, det0 = self._jac(0.0, 0.0)
        J0i = np.linalg.inv(J0)
        Kuu = np.zeros((8, 8)); Kua = np.zeros((8, 4)); Kaa = np.zeros((4, 4))
        for (r, s, J, det) in self.gp:
            dN = _dN(r, s)
            dNx = np.linalg.solve(J, dN)                                          
            B = np.zeros((3, 8))
            B[0, 0::2] = dNx[0]
            B[1, 1::2] = dNx[1]
            B[2, 0::2] = dNx[1]
            B[2, 1::2] = dNx[0]
                                                                          
            g1 = J0i @ np.array([-2 * r, 0.0])
            g2 = J0i @ np.array([0.0, -2 * s])
            Gm = np.array([[g1[0], g2[0], 0, 0],
                           [0, 0, g1[1], g2[1]],
                           [g1[1], g2[1], g1[0], g2[0]]]) * (det0 / det)
            Kuu += B.T @ D @ B * det
            Kua += B.T @ D @ Gm * det
            Kaa += Gm.T @ D @ Gm * det
        Kaa_inv_Kau = np.linalg.solve(Kaa, Kua.T)                      
        self._alpha_map = -Kaa_inv_Kau                                                  
        Kc = Kuu - Kua @ Kaa_inv_Kau
        K = np.zeros((24, 24))
        idx = [6 * i + k for i in range(4) for k in (0, 1)]
        K[np.ix_(idx, idx)] = Kc
        return K

    def _k_drilling(self, G):
        """
        Drilling (rotation about the normal) coupling.

        Rotation constraint on the defect  q = omega_enh - theta,
            omega_enh = omega_bilinear + KINC(nu) * omega_incompat
        omega = (dv/dx - du/dy)/2 is the skew rotation of the Q4 displacement field, omega_incompat the skew
        rotation of the Wilson-Taylor incompatible modes (condensed alpha, _alpha_map), theta the bilinear
        interpolation of the nodal drilling rotations. The defect is L2-projected on {1, r, s, rs}; each
        projected mode has its own weight (units G*t):

            K = G t  Gc^T diag(w0, w1, w1, w2) H^-1 Gc,   Gc = int phi q dA,  H = int phi phi^T dA
            w0 = 2/5, w1 = 2/(3-nu), KINC = 1-2nu, w2 = small theta-hourglass stabiliser.

        Rigid rotation about the normal (theta = omega = const) gives zero energy. Constants identified from
        SAP2000 runs at nu = 0.2 and 0.3.
        """
        nu = self.nu
        w = np.array([DRILL_W0, 2.0 / (3.0 - nu), 2.0 / (3.0 - nu), DRILL_W2])
        kinc = 1.0 - 2.0 * nu
        J0, det0 = self._jac(0.0, 0.0)
        J0i = np.linalg.inv(J0)
        amap = self._alpha_map
        ui = [6 * i + k for i in range(4) for k in (0, 1)]
        Gc = np.zeros((4, 24))
        H = np.zeros((4, 4))
        for (r, s, J, det) in self.gp:
            dNx = np.linalg.solve(J, _dN(r, s))
            N = _N(r, s)
            q = np.zeros(24)
            for i in range(4):
                q[6 * i + 0] = -0.5 * dNx[1, i]
                q[6 * i + 1] = 0.5 * dNx[0, i]
                q[6 * i + 5] = -N[i]
            g1 = J0i @ np.array([-2 * r, 0.0])
            g2 = J0i @ np.array([0.0, -2 * s])
            row = 0.5 * np.array([-g1[1], -g2[1], g1[0], g2[0]]) * (det0 / det)
            q[ui] += kinc * (row @ amap)
            phi = np.array([1.0, r, s, r * s])
            Gc += np.outer(phi, q) * det
            H += np.outer(phi, phi) * det
        return G * self.tm * (Gc.T @ np.diag(w) @ np.linalg.solve(H, Gc))

    def _Db(self):
        E, nu, t = self.E, self.nu, self.tb
        m = self.mods
        m11, m22, m12 = _mod(m, 'm11'), _mod(m, 'm22'), _mod(m, 'm12')
        c = E * t ** 3 / (12 * (1 - nu ** 2))
        return c * np.array([[m11, nu * np.sqrt(m11 * m22), 0.0],
                             [nu * np.sqrt(m11 * m22), m22, 0.0],
                             [0.0, 0.0, (1 - nu) / 2 * m12]])

    def _Ds(self, G):
        f = THIN_SHEAR_FACTOR if self.is_thin else 1.0
        c = KAPPA_S * G * self.tb * f
        return c * np.diag([_mod(self.mods, 'v13'), _mod(self.mods, 'v23')])

    def _tying_rows(self):
        xy = self.xy

        def rows(r, s):
            N = _N(r, s); dN = _dN(r, s); J = dN @ xy
            rr = np.zeros(24); rs = np.zeros(24)
            for i in range(4):
                rr[6 * i + 2] = dN[0, i]
                rr[6 * i + 4] = J[0, 0] * N[i]                                          
                rr[6 * i + 3] = -J[0, 1] * N[i]                                          
                rs[6 * i + 2] = dN[1, i]
                rs[6 * i + 4] = J[1, 0] * N[i]
                rs[6 * i + 3] = -J[1, 1] * N[i]
            return rr, rs
        A = rows(0.0, 1.0)[0]; B = rows(0.0, -1.0)[0]
        C = rows(1.0, 0.0)[1]; D = rows(-1.0, 0.0)[1]
        return A, B, C, D

    def _Bb(self, r, s, J):
        dNx = np.linalg.solve(J, _dN(r, s))
        B = np.zeros((3, 24))
        for i in range(4):
            B[0, 6 * i + 4] = dNx[0, i]
            B[1, 6 * i + 3] = -dNx[1, i]
            B[2, 6 * i + 4] = dNx[1, i]
            B[2, 6 * i + 3] = -dNx[0, i]
        return B

    def _Bs(self, r, s, J, ty):
        A, B, C, D = ty
        gr = 0.5 * (1 + s) * A + 0.5 * (1 - s) * B
        gs = 0.5 * (1 + r) * C + 0.5 * (1 - r) * D
        return np.linalg.solve(J, np.vstack([gr, gs]))                            

    @staticmethod
    def _serend(r, s):
        N5 = .5 * (1 - r * r) * (1 - s); N6 = .5 * (1 + r) * (1 - s * s)
        N7 = .5 * (1 - r * r) * (1 + s); N8 = .5 * (1 - r) * (1 - s * s)
        d5r = -r * (1 - s); d5s = -.5 * (1 - r * r); d6r = .5 * (1 - s * s); d6s = -(1 + r) * s
        d7r = -r * (1 + s); d7s = .5 * (1 - r * r); d8r = -.5 * (1 - s * s); d8s = -(1 - r) * s
        Nb = _N(r, s); dNb = _dN(r, s)
        N = np.array([Nb[0] - .5 * (N5 + N8), Nb[1] - .5 * (N5 + N6), Nb[2] - .5 * (N6 + N7),
                      Nb[3] - .5 * (N7 + N8), N5, N6, N7, N8])
        dr = np.array([dNb[0, 0] - .5 * (d5r + d8r), dNb[0, 1] - .5 * (d5r + d6r),
                       dNb[0, 2] - .5 * (d6r + d7r), dNb[0, 3] - .5 * (d7r + d8r), d5r, d6r, d7r, d8r])
        ds = np.array([dNb[1, 0] - .5 * (d5s + d8s), dNb[1, 1] - .5 * (d5s + d6s),
                       dNb[1, 2] - .5 * (d6s + d7s), dNb[1, 3] - .5 * (d7s + d8s), d5s, d6s, d7s, d8s])
        return N, dr, ds

    def _dkq_side_rows(self):
        """Kirchhoff constraints on the 4 mid-side nodes (cubic w along the side, linear normal slope)."""
        xy = self.xy; e = np.eye(12); rs_, rn_, tv, nv = [], [], [], []
        for k in range(4):
            i, j = k, (k + 1) % 4
            d = xy[j] - xy[i]; l = np.linalg.norm(d); t = d / l; n = np.array([-t[1], t[0]]); a = 1.5 / l
            bsi = t[0] * e[3 * i + 1] + t[1] * e[3 * i + 2]; bsj = t[0] * e[3 * j + 1] + t[1] * e[3 * j + 2]
            bni = n[0] * e[3 * i + 1] + n[1] * e[3 * i + 2]; bnj = n[0] * e[3 * j + 1] + n[1] * e[3 * j + 2]
            rs_.append(a * (e[3 * j] - e[3 * i]) - 0.25 * (bsi + bsj)); rn_.append(0.5 * (bni + bnj))
            tv.append(t); nv.append(n)
        return rs_, rn_, tv, nv

    def _dkq_B(self, r, s, side=None):
        """3x24 curvature matrix in the SAME sign convention as _Bb (kappa=[th_y,x ; -th_x,y ; th_y,y - th_x,x]).
        Slopes beta=(w,x,w,y)=(-th_y, th_x)."""
        if side is None:
            side = self._dkq_side_rows()
        rs_, rn_, tv, nv = side
        J = _dN(r, s) @ self.xy; Ji = np.linalg.inv(J)
        N, dr, ds = self._serend(r, s)
        dHx_r = np.zeros(12); dHx_s = np.zeros(12); dHy_r = np.zeros(12); dHy_s = np.zeros(12)
        for i in range(4):
            dHx_r[3 * i + 1] += dr[i]; dHx_s[3 * i + 1] += ds[i]
            dHy_r[3 * i + 2] += dr[i]; dHy_s[3 * i + 2] += ds[i]
        for k in range(4):
            bx = tv[k][0] * rs_[k] + nv[k][0] * rn_[k]; by = tv[k][1] * rs_[k] + nv[k][1] * rn_[k]
            dHx_r += dr[4 + k] * bx; dHx_s += ds[4 + k] * bx
            dHy_r += dr[4 + k] * by; dHy_s += ds[4 + k] * by
        bxx = Ji[0, 0] * dHx_r + Ji[0, 1] * dHx_s; bxy = Ji[1, 0] * dHx_r + Ji[1, 1] * dHx_s
        byx = Ji[0, 0] * dHy_r + Ji[0, 1] * dHy_s; byy = Ji[1, 0] * dHy_r + Ji[1, 1] * dHy_s
        Bm = np.array([bxx, byy, bxy + byx])                                                      
        T3 = np.array([[1, 0, 0], [0, 0, -1], [0, 1, 0]], float)                                 
        B12 = -Bm @ np.kron(np.eye(4), T3)                                                         
        B = np.zeros((3, 24))
        for i in range(4):
            B[:, 6 * i + 2] = B12[:, 3 * i]; B[:, 6 * i + 3] = B12[:, 3 * i + 1]; B[:, 6 * i + 4] = B12[:, 3 * i + 2]
        return B

    def _k_bending_dkq(self):
        Db = self._Db(); side = self._dkq_side_rows(); K = np.zeros((24, 24))
        for (r, s, J, det) in self.gp:
            B = self._dkq_B(r, s, side); K += B.T @ Db @ B * det
        return K

    def _use_dkq(self):
        """True -> this element's bending is DKQ (true Kirchhoff); False -> MITC4.
        Only thin types with bending can use DKQ; per-section choice wins over the module default."""
        if not (self.is_thin and self.has_bending):
            return False
        f = str(self.sec.get('thin_formulation') or '').strip().upper()
        if f.startswith('MITC'):
            return False
        if f.startswith('DKQ') or f.startswith('KIRCHHOFF'):
            return True
        return bool(USE_DKQ_FOR_THIN)

    def _k_bending(self, G):
        if self._use_dkq():
            return self._k_bending_dkq()
        Db, Ds = self._Db(), self._Ds(G)
        ty = self._tying_rows()
        K = np.zeros((24, 24))
        for (r, s, J, det) in self.gp:
            Bb = self._Bb(r, s, J)
            Bs = self._Bs(r, s, J, ty)
            K += (Bb.T @ Db @ Bb + Bs.T @ Ds @ Bs) * det
        return K

    def _k_stabilization(self, G):
        """Tiny stiffness on whatever DOFs the section type leaves empty so a
        plate-only / membrane-only region cannot make K singular."""
        k = np.zeros(24)
        A = self.area
        Em = self.E * self.tm
        Db = self.E * self.tb ** 3 / 12.0
        for i in range(4):
            if not self.has_membrane:
                k[6 * i + 0] = k[6 * i + 1] = STAB_EPS * self.E * self.tb / 4.0
                k[6 * i + 5] = STAB_EPS * G * self.tb * A / 4.0
            if not self.has_bending:
                k[6 * i + 2] = STAB_EPS * Em / 4.0
                k[6 * i + 3] = k[6 * i + 4] = STAB_EPS * Em * A / 4.0
        return np.diag(k)

    @property
    def thickness_weight(self):
        return self.tm

    @property
    def weight(self):
        """gross self-weight (force units) = rho(weight density) * t * A * weight_mod"""
        return self.rho * self.tm * self.area * _mod(self.mods, 'weight')

    @property
    def mass(self):
        return self.rho / G_ACC * self.tm * self.area * _mod(self.mods, 'mass')

    def nodal_forces_from_traction(self, q_global):
        """Consistent nodal forces (4,3, GLOBAL) of a uniform traction q (force/area)."""
        q = np.asarray(q_global, dtype=float)
        w = np.zeros(4)
        for (r, s, J, det) in self.gp:
            w += _N(r, s) * det
        return np.outer(w, q)

    def nodal_forces_from_total(self, f_total_global):
        """Distribute a total force vector over the nodes with the same weights."""
        return self.nodal_forces_from_traction(np.asarray(f_total_global, float) / self.area)

    def offset_moments(self, f):
        """(4,3) GLOBAL nodal moments that go with the (4,3) nodal forces f acting at the
        mid-surface: M = d x F (zero when there is no offset or F is parallel to d)."""
        if self.offset == 0.0:
            return np.zeros((4, 3))
        return np.cross(self.d_global, np.asarray(f, dtype=float))

    def recover(self, u_global24):
        """Per-Gauss-point resultants in LOCAL axes (force & moment per unit width).
        Moment sign convention: M = D_b * kappa (see module note). Returns list of dicts."""
        u = self.T @ np.asarray(u_global24, dtype=float)
        if self.Tecc is not None:
            u = self.Tecc @ u                                                             
        out = []
        ty = self._tying_rows()
        Dm, Db, Ds = self._Dm(), self._Db(), self._Ds(self.E / (2 * (1 + self.nu)))
        idx = [6 * i + k for i in range(4) for k in (0, 1)]
        u_ip = u[idx]
        alpha = self._alpha_map @ u_ip if self._alpha_map is not None else None
        J0, det0 = self._jac(0.0, 0.0)
        J0i = np.linalg.inv(J0)
        for (r, s, J, det) in self.gp:
            rec = {}
            if self.has_membrane:
                dNx = np.linalg.solve(J, _dN(r, s))
                B = np.zeros((3, 8))
                B[0, 0::2] = dNx[0]; B[1, 1::2] = dNx[1]
                B[2, 0::2] = dNx[1]; B[2, 1::2] = dNx[0]
                g1 = J0i @ np.array([-2 * r, 0.0]); g2 = J0i @ np.array([0.0, -2 * s])
                Gm = np.array([[g1[0], g2[0], 0, 0], [0, 0, g1[1], g2[1]],
                               [g1[1], g2[1], g1[0], g2[0]]]) * (det0 / det)
                eps = B @ u_ip + Gm @ alpha
                rec['F11'], rec['F22'], rec['F12'] = (Dm @ eps).tolist()
            if self.has_bending and self._use_dkq():
                side = self._dkq_side_rows()
                kap = self._dkq_B(r, s, side) @ u
                rec['M11'], rec['M22'], rec['M12'] = (Db @ kap).tolist()
                                                                                                                         
                h = 1e-4
                Mr = lambda rr, ss: Db @ (self._dkq_B(rr, ss, side) @ u)
                dM_dr = (Mr(r + h, s) - Mr(r - h, s)) / (2 * h); dM_ds = (Mr(r, s + h) - Mr(r, s - h)) / (2 * h)
                Ji = np.linalg.inv(J)
                dM_dx = Ji[0, 0] * dM_dr + Ji[0, 1] * dM_ds; dM_dy = Ji[1, 0] * dM_dr + Ji[1, 1] * dM_ds
                rec['V13'] = float(dM_dx[0] + dM_dy[2]); rec['V23'] = float(dM_dx[2] + dM_dy[1])
            elif self.has_bending:
                kap = self._Bb(r, s, J) @ u
                rec['M11'], rec['M22'], rec['M12'] = (Db @ kap).tolist()
                gam = self._Bs(r, s, J, ty) @ u
                rec['V13'], rec['V23'] = (Ds @ gam).tolist()
            pt = _N(r, s) @ self.coords + self.d_global
            rec['xyz'] = pt.tolist()
            out.append(rec)
        return out

_UNSUPPORTED = ("PlaneSection", "AsolidSection")

def _blockdiag3(R, n):
    """Same matrix as np.kron(np.eye(n), R) for a 3x3 R, built without kron's overhead."""
    T = np.zeros((3 * n, 3 * n))
    for i in range(n):
        T[3 * i:3 * i + 3, 3 * i:3 * i + 3] = R
    return T

_T3_DKQ = np.array([[1, 0, 0], [0, 0, -1], [0, 1, 0]], float)
_KT3_DKQ = np.kron(np.eye(4), _T3_DKQ)
_IP_DOFS = np.array([6 * i + k for i in range(4) for k in (0, 1)])

def _build_dkq_chunk(els):
    """
    Computes k_local / k_global / area / gp / _alpha_map for many shells at once with numpy
    (leading axis = element). It is the SAME math as ShellElement._build for a thin DKQ shell
    with membrane + bending (_k_membrane, _k_drilling, _k_bending_dkq, then Tecc, symmetrise,
    T'kT), written with the element index as a batch dimension. Results agree with the scalar
    path to rounding (~1e-15 relative).

    Returns the list of elements it did NOT handle (non-positive Jacobian etc.); the caller
    builds those with the scalar _build(), which raises exactly the original error.
    """
    n = len(els)
    xy = np.array([e.xy for e in els])                                            
    E = np.array([e.E for e in els]); nu = np.array([e.nu for e in els])
    tm = np.array([e.tm for e in els])

    J_g = [np.matmul(_dN(r, s), xy) for (r, s) in _GAUSS]                              
    det_g = [J[:, 0, 0] * J[:, 1, 1] - J[:, 0, 1] * J[:, 1, 0] for J in J_g]
    J0 = np.matmul(_dN(0.0, 0.0), xy)
    det0 = J0[:, 0, 0] * J0[:, 1, 1] - J0[:, 0, 1] * J0[:, 1, 0]

    bad = det0 == 0.0
    for J, det in zip(J_g, det_g):
        jmax = np.abs(J).reshape(n, 4).max(axis=1)
        bad = bad | (det <= 1e-14 * np.maximum(1.0, jmax ** 2))                               
    if bad.any():
        good = ~bad
        unhandled = [e for e, g in zip(els, good) if not g]
        keep = [e for e, g in zip(els, good) if g]
        return unhandled + (_build_dkq_chunk(keep) if keep else [])

    area = 0.0
    for det in det_g:
        area = area + det

    cache = {}
    Dm_l, Db_l = [], []
    for e in els:
        key = (e.sec['name'], e.E, e.nu, e.tm, e.tb)
        if key not in cache:
            cache[key] = (e._Dm(), e._Db())
        Dm_l.append(cache[key][0]); Db_l.append(cache[key][1])
    Dm = np.array(Dm_l); Db = np.array(Db_l)
    G = E / (2 * (1 + nu))

    J0i = np.linalg.inv(J0)
    dNx_g = [np.linalg.solve(J, np.broadcast_to(_dN(r, s), (n, 2, 4))) for (r, s), J in zip(_GAUSS, J_g)]
    Kuu = np.zeros((n, 8, 8)); Kua = np.zeros((n, 8, 4)); Kaa = np.zeros((n, 4, 4))
    g12 = []
    for gi, (r, s) in enumerate(_GAUSS):
        dNx, det = dNx_g[gi], det_g[gi]
        B = np.zeros((n, 3, 8))
        B[:, 0, 0::2] = dNx[:, 0]; B[:, 1, 1::2] = dNx[:, 1]
        B[:, 2, 0::2] = dNx[:, 1]; B[:, 2, 1::2] = dNx[:, 0]
        g1 = np.einsum('nij,j->ni', J0i, np.array([-2 * r, 0.0]))
        g2 = np.einsum('nij,j->ni', J0i, np.array([0.0, -2 * s]))
        ratio = det0 / det
        Gm = np.zeros((n, 3, 4))
        Gm[:, 0, 0] = g1[:, 0]; Gm[:, 0, 1] = g2[:, 0]
        Gm[:, 1, 2] = g1[:, 1]; Gm[:, 1, 3] = g2[:, 1]
        Gm[:, 2, 0] = g1[:, 1]; Gm[:, 2, 1] = g2[:, 1]; Gm[:, 2, 2] = g1[:, 0]; Gm[:, 2, 3] = g2[:, 0]
        Gm *= ratio[:, None, None]
        Bt = B.transpose(0, 2, 1); wd = det[:, None, None]
        Kuu += (Bt @ Dm @ B) * wd
        Kua += (Bt @ Dm @ Gm) * wd
        Kaa += (Gm.transpose(0, 2, 1) @ Dm @ Gm) * wd
        g12.append((g1, g2, ratio))
    X = np.linalg.solve(Kaa, Kua.transpose(0, 2, 1))                               
    amap = -X
    Kc = Kuu - Kua @ X
    K = np.zeros((n, 24, 24))
    K[:, _IP_DOFS[:, None], _IP_DOFS[None, :]] = Kc

    w = np.stack([np.full(n, DRILL_W0), 2.0 / (3.0 - nu), 2.0 / (3.0 - nu), np.full(n, DRILL_W2)], axis=1)
    kinc = 1.0 - 2.0 * nu
    Gc = np.zeros((n, 4, 24)); H = np.zeros((n, 4, 4))
    for gi, (r, s) in enumerate(_GAUSS):
        dNx, det = dNx_g[gi], det_g[gi]
        g1, g2, ratio = g12[gi]
        Nn = _N(r, s)
        q = np.zeros((n, 24))
        for i in range(4):
            q[:, 6 * i + 0] = -0.5 * dNx[:, 1, i]
            q[:, 6 * i + 1] = 0.5 * dNx[:, 0, i]
            q[:, 6 * i + 5] = -Nn[i]
        row = 0.5 * np.stack([-g1[:, 1], -g2[:, 1], g1[:, 0], g2[:, 0]], axis=1) * ratio[:, None]
        q[:, _IP_DOFS] += kinc[:, None] * np.einsum('nk,nkj->nj', row, amap)
        phi = np.array([1.0, r, s, r * s])
        wd = det[:, None, None]
        Gc += phi[None, :, None] * q[:, None, :] * wd
        H += (phi[:, None] * phi[None, :])[None] * wd
    Y = np.linalg.solve(H, Gc)
    K += (G * tm)[:, None, None] * ((Gc.transpose(0, 2, 1) * w[:, None, :]) @ Y)

    I12 = np.eye(12)
    rs_, rn_, tv, nv = [], [], [], []
    for k in range(4):
        i, j = k, (k + 1) % 4
        d = xy[:, j] - xy[:, i]
        l = np.sqrt((d * d).sum(axis=1))
        t = d / l[:, None]
        nrm = np.stack([-t[:, 1], t[:, 0]], axis=1)
        a = 1.5 / l
        bsi = t[:, 0:1] * I12[3 * i + 1] + t[:, 1:2] * I12[3 * i + 2]
        bsj = t[:, 0:1] * I12[3 * j + 1] + t[:, 1:2] * I12[3 * j + 2]
        bni = nrm[:, 0:1] * I12[3 * i + 1] + nrm[:, 1:2] * I12[3 * i + 2]
        bnj = nrm[:, 0:1] * I12[3 * j + 1] + nrm[:, 1:2] * I12[3 * j + 2]
        rs_.append(a[:, None] * (I12[3 * j] - I12[3 * i]) - 0.25 * (bsi + bsj))
        rn_.append(0.5 * (bni + bnj)); tv.append(t); nv.append(nrm)
    Kb = np.zeros((n, 24, 24))
    for gi, (r, s) in enumerate(_GAUSS):
        Ji = np.linalg.inv(J_g[gi])
        _, dr, ds = ShellElement._serend(r, s)
        dHx_r = np.zeros((n, 12)); dHx_s = np.zeros((n, 12)); dHy_r = np.zeros((n, 12)); dHy_s = np.zeros((n, 12))
        for i in range(4):
            dHx_r[:, 3 * i + 1] += dr[i]; dHx_s[:, 3 * i + 1] += ds[i]
            dHy_r[:, 3 * i + 2] += dr[i]; dHy_s[:, 3 * i + 2] += ds[i]
        for k in range(4):
            bx = tv[k][:, 0:1] * rs_[k] + nv[k][:, 0:1] * rn_[k]
            by = tv[k][:, 1:2] * rs_[k] + nv[k][:, 1:2] * rn_[k]
            dHx_r += dr[4 + k] * bx; dHx_s += ds[4 + k] * bx
            dHy_r += dr[4 + k] * by; dHy_s += ds[4 + k] * by
        bxx = Ji[:, 0, 0:1] * dHx_r + Ji[:, 0, 1:2] * dHx_s
        bxy = Ji[:, 1, 0:1] * dHx_r + Ji[:, 1, 1:2] * dHx_s
        byx = Ji[:, 0, 0:1] * dHy_r + Ji[:, 0, 1:2] * dHy_s
        byy = Ji[:, 1, 0:1] * dHy_r + Ji[:, 1, 1:2] * dHy_s
        Bm = np.stack([bxx, byy, bxy + byx], axis=1)                                
        B12 = (-Bm) @ _KT3_DKQ
        B = np.zeros((n, 3, 24))
        for i in range(4):
            B[:, :, 6 * i + 2] = B12[:, :, 3 * i]
            B[:, :, 6 * i + 3] = B12[:, :, 3 * i + 1]
            B[:, :, 6 * i + 4] = B12[:, :, 3 * i + 2]
        Kb += (B.transpose(0, 2, 1) @ Db @ B) * det_g[gi][:, None, None]
    K += Kb

    off = [m for m, e in enumerate(els) if e.Tecc is not None]
    if off:
        Te = np.array([els[m].Tecc for m in off])
        K[off] = Te.transpose(0, 2, 1) @ K[off] @ Te
    k_local = 0.5 * (K + K.transpose(0, 2, 1))
    T = np.array([e.T for e in els])
    k_global = T.transpose(0, 2, 1) @ k_local @ T

    for m, e in enumerate(els):
        e.gp = [(r, s, J_g[gi][m].copy(), det_g[gi][m]) for gi, (r, s) in enumerate(_GAUSS)]
        e.area = area[m]
        e._alpha_map = amap[m].copy()
        e.k_local = k_local[m].copy()
        e.k_global = k_global[m].copy()
    return []

def _build_all(shells):
    """Builds every deferred shell. Thin-DKQ membrane+bending shells go through the batched
    kernel; every other type (thick, plate-only, membrane-only, MITC4) and anything the kernel
    declines uses the original scalar _build(), so errors and results are unchanged."""
    pending = [e for e in shells if not hasattr(e, 'k_local')]
    batch = [e for e in pending if e.has_membrane and e.has_bending and e._use_dkq()]
    batch_ids = {id(e) for e in batch}
    for e in pending:
        if id(e) not in batch_ids:
            e._build()
    for a in range(0, len(batch), _SHELL_CHUNK):
        chunk = batch[a:a + _SHELL_CHUNK]
        try:
            left = _build_dkq_chunk(chunk)
        except np.linalg.LinAlgError:
            left = chunk
        for e in left:
            e._build()

def build_shell_elements(dm):
    """Fills dm.shells. No-op if the .mf has no area_elements."""
    dm.shells = []
    a_elems = dm.raw.get('area_elements') or []
    if not a_elems:
        return
    sec_raw = {s['name']: s for s in dm.raw.get('area_sections', [])}
    mat_raw = {m['name']: m for m in dm.raw.get('materials', [])}
    coords_by_idx = {n['idx']: n['coords'] for n in dm.nodes}

    for ae in a_elems:
        s = sec_raw.get(ae['sec_name'])
        if s is None:
            raise SolverException("E103", f"Area {ae['id']} references missing area section '{ae['sec_name']}'.")
        if s.get('type') in _UNSUPPORTED:
            raise SolverException("E208", f"Area {ae['id']}: section '{s['name']}' is a {s['type']}.")
        if s.get('modeling_type', 'True FEM (Shell)') == "Tributary Area":
            continue                                                                     
        stype = s.get('shell_type', 'Shell - Thin')
        if 'layered' in stype.lower():
            raise SolverException("E208", f"Area {ae['id']}: section '{s['name']}' is Layered/Nonlinear.")
        if len(ae['node_ids']) != 4:
            raise SolverException("E207", f"Area {ae['id']}: only 4-node quads are supported.")
        m = mat_raw.get(s.get('material'))
        if m is None:
            raise SolverException("E103", f"Area section '{s['name']}' references missing material '{s.get('material')}'.")
        tm = float(s.get('membrane_thickness', 0.0)); tb = float(s.get('bending_thickness', 0.0))
        if tm <= 0 and tb <= 0:
            raise SolverException("E207", f"Area section '{s['name']}' has zero thickness.")
        sec = {'name': s['name'], 'shell_type': stype, 'tm': tm if tm > 0 else tb,
               'tb': tb if tb > 0 else tm, 'angle': float(s.get('material_angle', 0.0) or 0.0),
               'mods': s.get('stiffness_modifiers') or {},
               'thin_formulation': s.get('thin_formulation')}
        try:
            idxs = [dm.node_id_to_idx[nid] for nid in ae['node_ids']]
        except KeyError as e:
            raise SolverException("E207", f"Area {ae['id']} references unknown node {e}.")
        P = np.array([coords_by_idx[i] for i in idxs])
        dm.shells.append(ShellElement(ae['id'], idxs, P, m['E'], m['nu'], m['rho'], sec,
                                      offset=ae.get('insertion_offset', 0.0),
                                      _defer_build=BATCH_SHELL_BUILD))
    if BATCH_SHELL_BUILD:
        _build_all(dm.shells)
    if dm.shells:
        n_dkq = sum(1 for e in dm.shells if e._use_dkq())
        n_thick = sum(1 for e in dm.shells if e.has_bending and not e.is_thin)
        n_mitc_thin = sum(1 for e in dm.shells if e.has_bending and e.is_thin and not e._use_dkq())
        n_memb = len(dm.shells) - n_dkq - n_thick - n_mitc_thin
        print(f"      Processed {len(dm.shells)} shell elements "
              f"(thin DKQ: {n_dkq}, thin MITC4: {n_mitc_thin}, thick MITC4: {n_thick}, membrane-only: {n_memb}).")

def generate_shell_self_weight_loads(dm, target_patterns):
    """Pattern self-weight multiplier -> lumped nodal loads flagged _is_sw
    (same mechanism the frame self-weight uses, so the net-load mass path
    regenerates them automatically)."""
    shells = getattr(dm, 'shells', None)
    if not shells:
        return 0
    node_id_of = {n['idx']: n['id'] for n in dm.nodes}
    dm.raw.setdefault('loads', [])
    count = 0
    for sh in shells:
        w = sh.weight
        if w <= 1e-12:
            continue
        for pat in target_patterns:
            f = sh.nodal_forces_from_total([0.0, 0.0, -w * pat['sw_mult']])
            m = sh.offset_moments(f)
            for k, nidx in enumerate(sh.node_indices):
                dm.raw['loads'].append({
                    'type': 'nodal', 'pattern': pat['name'], 'node_id': node_id_of[nidx],
                    'fx': float(f[k, 0]), 'fy': float(f[k, 1]), 'fz': float(f[k, 2]),
                    'mx': float(m[k, 0]), 'my': float(m[k, 1]), 'mz': float(m[k, 2]), '_is_sw': True})
                count += 1
    return count

def area_load_nodal_forces(sh, load, scale=1.0):
    """(4,3) global nodal forces of ONE area_uniform / area_gravity load record."""
    t = load.get('type')
    if t == 'area_gravity':
        v = np.array([load.get('gx', 0.0), load.get('gy', 0.0), load.get('gz', 0.0)], float) * scale
        if str(load.get('coord', 'GLOBAL')).upper() != 'GLOBAL':
            v = sh.R.T @ v
        return sh.nodal_forces_from_total(sh.weight * v)
    if t == 'area_uniform':
        p = float(load['load']) * scale
        d = str(load.get('direction', 'Gravity')).upper().replace('_', ' ')
        e = {'GRAVITY': (np.array([0, 0, -1.0]), False),
             'GLOBAL X': (np.array([1.0, 0, 0]), False), 'GLOBAL Y': (np.array([0, 1.0, 0]), False),
             'GLOBAL Z': (np.array([0, 0, 1.0]), False),
             'LOCAL 1': (np.array([1.0, 0, 0]), True), 'LOCAL 2': (np.array([0, 1.0, 0]), True),
             'LOCAL 3': (np.array([0, 0, 1.0]), True)}.get(d)
        if e is None:
            raise SolverException("E000", f"Unknown area load direction '{load.get('direction')}'.")
        vec, is_local = e
        q = sh.R.T @ vec if is_local else vec
        return sh.nodal_forces_from_traction(p * q)
    return None

def add_shell_area_loads(dm, P):
    """Adds area_uniform / area_gravity loads of the active patterns into P (in place)."""
    shells = getattr(dm, 'shells', None)
    if not shells:
        return
    by_id = {sh.id: sh for sh in shells}
    active = {pat: scale for pat, scale in dm.load_case['patterns']}
    n_applied = 0
    for load in dm.raw.get('loads', []):
        if load.get('type') not in ('area_uniform', 'area_gravity'):
            continue
        if load.get('pattern') not in active:
            continue
        sh = by_id.get(load['area_id'])
        if sh is None:
            print(f"      [!] Area load on area {load['area_id']} ignored: no such solved shell "
                  f"(deleted by meshing, or a Tributary slab).")
            continue
        f = area_load_nodal_forces(sh, load, active[load['pattern']])
        m = sh.offset_moments(f)
        for k, nidx in enumerate(sh.node_indices):
            P[6 * nidx: 6 * nidx + 3] += f[k]
            P[6 * nidx + 3: 6 * nidx + 6] += m[k]
        n_applied += 1
    if n_applied:
        print(f"      Applied {n_applied} area load record(s) to shells.")
