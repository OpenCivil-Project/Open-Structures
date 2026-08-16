"""
cable_catenary_solver.py

Standalone elastic-catenary target resolver for OpenCivil cable elements.

Purpose
-------
Given the two end coordinates of a cable, its axial stiffness (EA), a
distributed self-weight (force per unit UNSTRESSED length), and ONE target
parameter (undeformed length / tension@I / tension@J / horizontal tension /
max sag / low-point sag — matching CableGeometryDialog's combo box), solve
for the full elastic-catenary state: the unstressed length L0, the constant
horizontal tension component H, the vertical tension component at end I
(V0), and the deformed shape.

This has ZERO dependency on the FEM assembler / element classes / solver
engine. It is pure numerics (numpy) and can be dropped in and unit-tested
today. It is meant to be called from two places eventually:

  1. CableGeometryDialog._simulate_refresh() — replaces the fake straight
     line + fake parabola with the real solved shape, fills the table and
     the deformed/undeformed sag & length fields.

  2. Stage 1/2/3 cable element construction — once we know L0, H, V0 for
     the cable's target state, that state becomes the "initial condition"
     used to build the equivalent nodal loads (stage 1, same pattern as
     _generate_tendon_loads), the initial axial force for the P-Delta
     geometric stiffness (stage 2), and the initial shape for the meshed
     large-deflection element (stage 3).

Theory
------
Standard elastic catenary with self-weight w (force / unstressed length)
acting in -z (local "up" axis), constant horizontal tension H, and vertical
tension component V(s) = V0 + w*s at unstressed arc length s in [0, L0]:

    x(s) = (H/EA)*s + (H/w) * [ asinh((V0 + w*s)/H) - asinh(V0/H) ]
    z(s) = (1/EA)*(V0*s + w*s^2/2)
           + (H/w) * [ sqrt(1+((V0+w*s)/H)^2) - sqrt(1+(V0/H)^2) ]

with x(0)=z(0)=0 at end I. Boundary conditions x(L0)=dx, z(L0)=dz (chord
components in the local vertical plane containing gravity and the chord).
Three unknowns (H, V0, L0), two boundary equations, plus one equation from
whichever target parameter the user specified -> solved with a damped
Newton iteration (numerical Jacobian).

A separate closed-form branch handles the vertical-cable degenerate case
(H -> 0, chord has ~zero horizontal projection), which the general
formulas above cannot represent (division by w with H=0 is fine, division
by H is not).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import numpy as np
from scipy.optimize import least_squares

class CableTargetType(Enum):
    UNDEFORMED_LENGTH = "Cable - Undeformed Length"
    TENSION_I = "Cable - Tension at I-End"
    TENSION_J = "Cable - Tension at J-End"
    HORIZONTAL_TENSION = "Cable - Horizontal Tension Component"
    MAX_VERTICAL_SAG = "Cable - Maximum Vertical Sag"
    LOW_POINT_SAG = "Cable - Low-Point Vertical Sag"

    @classmethod
    def from_combo_text(cls, text: str) -> "CableTargetType":
        for member in cls:
            if member.value == text:
                return member
        raise ValueError(f"Unrecognized cable target type: {text!r}")

@dataclass
class CablePoint:
    s_unstressed: float                                                
    rel_dist: float                        
    xyz: tuple                                 
    sag: float                                                                

@dataclass
class CableSolveResult:
    converged: bool
    message: str = ""

    H: float = 0.0                                                                 
    V0: float = 0.0                                                
    Vj: float = 0.0                                                
    L0: float = 0.0                                           
    deformed_length: float = 0.0

    T_i: float = 0.0                                      
    T_j: float = 0.0                                      

    max_sag: float = float("nan")
    low_point_sag: float = float("nan")

    is_compression_anywhere: bool = False                                    
    points: list = field(default_factory=list)                     

def _local_frame(node_i, node_j, gravity_dir):
    """
    Build the local (ex, ez) axes of the vertical plane containing gravity
    and the chord, and return (dx, dz, Lc_local, ex, ez) where dx, dz are
    the chord components in that plane (z positive UP), and Lc_local is
    the chord length (should equal the true 3D chord length).
    """
    p_i = np.asarray(node_i, dtype=float)
    p_j = np.asarray(node_j, dtype=float)
    chord = p_j - p_i
    Lc = np.linalg.norm(chord)
    if Lc < 1e-9:
        raise ValueError("Cable end nodes coincide (zero-length chord).")

    g = np.asarray(gravity_dir, dtype=float)
    g = g / np.linalg.norm(g)
    ez = -g              

    dz = float(np.dot(chord, ez))
    horiz = chord - dz * ez
    horiz_norm = np.linalg.norm(horiz)

    if horiz_norm < 1e-9:
                                                                            
        arbitrary = np.array([1.0, 0.0, 0.0])
        if abs(np.dot(arbitrary, ez)) > 0.9:
            arbitrary = np.array([0.0, 1.0, 0.0])
        ex = arbitrary - np.dot(arbitrary, ez) * ez
        ex = ex / np.linalg.norm(ex)
        dx = 0.0
    else:
        ex = horiz / horiz_norm
        dx = horiz_norm

    return dx, dz, Lc, ex, ez, p_i

def _shape_xz(H, V0, w, EA, s):
    """Vectorized local (x(s), z(s)) per the elastic catenary equations."""
    Vs = V0 + w * s
    if abs(H) < 1e-9:
        raise FloatingPointError("H too close to zero for general formula")
    x = (H / EA) * s + (H / w) * (np.arcsinh(Vs / H) - np.arcsinh(V0 / H))
    z = (1.0 / EA) * (V0 * s + 0.5 * w * s ** 2) + (H / w) * (
        np.sqrt(1.0 + (Vs / H) ** 2) - np.sqrt(1.0 + (V0 / H) ** 2)
    )
    return x, z

def _residual(u, w, EA, dx, dz, target_type, target_value):
    H, V0, L0 = u
    if H <= 1e-9 or L0 <= 1e-9:
        return np.array([1e6, 1e6, 1e6])                                        

    x_end, z_end = _shape_xz(H, V0, w, EA, np.array([L0]))
    x_end, z_end = float(x_end[0]), float(z_end[0])

    r1 = x_end - dx
    r2 = z_end - dz

    if target_type == CableTargetType.UNDEFORMED_LENGTH:
        r3 = L0 - target_value
    elif target_type == CableTargetType.TENSION_I:
        r3 = np.hypot(H, V0) - target_value
    elif target_type == CableTargetType.TENSION_J:
        Vj = V0 + w * L0
        r3 = np.hypot(H, Vj) - target_value
    elif target_type == CableTargetType.HORIZONTAL_TENSION:
        r3 = H - target_value
    elif target_type == CableTargetType.MAX_VERTICAL_SAG:
        r3 = _max_vertical_sag(H, V0, w, EA, L0, dx, dz) - target_value
    elif target_type == CableTargetType.LOW_POINT_SAG:
        sag, ok = _low_point_sag(H, V0, w, L0, dz)
        if not ok:
            return np.array([1e6, 1e6, 1e6])
        r3 = sag - target_value
    else:
        raise ValueError(f"Unhandled target type: {target_type}")

    return np.array([r1, r2, r3])

def _max_vertical_sag(H, V0, w, EA, L0, dx, dz, n_samples=400):
    """Maximum vertical sag measured from the straight chord to the cable."""
    if dx < 1e-12:
        return 0.0
    s = np.linspace(0.0, L0, n_samples)
    x, z = _shape_xz(H, V0, w, EA, s)
    z_chord = (dz / dx) * x
    sag = z_chord - z
    return float(max(0.0, np.max(sag)))

def _max_perp_sag(H, V0, w, EA, L0, dx, dz, n_samples=400):
    """Perpendicular-to-chord sag retained for compatibility/diagnostics."""
    s = np.linspace(0.0, L0, n_samples)
    x, z = _shape_xz(H, V0, w, EA, s)
    Lc = np.hypot(dx, dz)
    if Lc < 1e-9:
        return float(np.max(np.abs(z)))
    d = (dz * x - dx * z) / Lc
    return float(np.max(np.abs(d)))

def _solve_max_vertical_sag_robust(dx, dz, w, EA, target_value,
                                   tol=1e-9, max_nfev=1200):
    """Robust inverse solve for a specified maximum vertical sag."""
    Lc = max(np.hypot(dx, dz), 1e-9)
    target = float(target_value)
    if target <= 1e-12 or dx < 1e-12:
        return None

    sag_scale = max(target, 0.01 * Lc, 1e-6)
    w_scale = max(w * Lc, 1.0)

    def residual(q):
        H = float(np.exp(q[0]))
        V0 = float(q[1] * w_scale)
        L0 = float(np.exp(q[2]) * Lc)
        try:
            xe, ze = _shape_xz(H, V0, w, EA, np.array([L0]))
            sag = _max_vertical_sag(H, V0, w, EA, L0, dx, dz, 300)
            return np.array([
                (float(xe[0]) - dx) / Lc,
                (float(ze[0]) - dz) / Lc,
                (sag - target) / sag_scale,
            ])
        except (FloatingPointError, OverflowError, ValueError):
            return np.full(3, 1e6)

    Hpar = w * dx * dx / max(8.0 * target, 1e-9)
    H_candidates = [Hpar, 0.1*Hpar, 0.5*Hpar, 2.0*Hpar,
                    10.0*Hpar, w*Lc, 5.0*w*Lc, 20.0*w*Lc]

    best = None
    for H0 in H_candidates:
        H0 = max(float(H0), 1e-6)
        for lfac in (0.98, 1.0, 1.02, 1.05, 1.10, 1.25):
            L0 = Lc * lfac
            V0 = H0 * dz / max(dx, 1e-9) - 0.5 * w * L0
            q0 = np.array([np.log(H0), V0 / w_scale, np.log(lfac)])
            try:
                sol = least_squares(
                    residual, q0, max_nfev=max_nfev,
                    xtol=tol, ftol=tol, gtol=tol
                )
            except Exception:
                continue

            norm = float(np.linalg.norm(sol.fun))
            if best is None or norm < best[0]:
                best = (norm, sol)
            if norm < 1e-7:
                q = sol.x
                return (float(np.exp(q[0])),
                        float(q[1] * w_scale),
                        float(np.exp(q[2]) * Lc))

    return None

def _low_point_sag(H, V0, w, L0, dz):
    """
    Low point = where the tangent is horizontal, i.e. V(s*) = 0 -> s* = -V0/w.
    Only meaningful if s* lies strictly inside (0, L0); otherwise the cable
    has no interior low point (monotonically rising/falling) and this
    target does not apply.
    """
    if abs(w) < 1e-12:
        return 0.0, False
    s_star = -V0 / w
    if not (0.0 < s_star < L0):
        return 0.0, False
    _, z_star = _shape_xz(H, V0, w, 1e30, np.array([s_star]))                            
    z_star = float(z_star[0])
    lower_support_z = min(0.0, dz)
    sag = lower_support_z - z_star
    return sag, True

def _numeric_jacobian(u, w, EA, dx, dz, target_type, target_value, eps_rel=1e-6):
    n = len(u)
    J = np.zeros((n, n))
    r0 = _residual(u, w, EA, dx, dz, target_type, target_value)
    for k in range(n):
        du = np.zeros(n)
        step = max(abs(u[k]), 1.0) * eps_rel
        du[k] = step
        r1 = _residual(u + du, w, EA, dx, dz, target_type, target_value)
        J[:, k] = (r1 - r0) / step
    return J, r0

def _solve_newton(u0, w, EA, dx, dz, target_type, target_value,
                   tol=1e-8, max_iter=60, damping=1.0):
    u = np.array(u0, dtype=float)
    for _ in range(max_iter):
        J, r = _numeric_jacobian(u, w, EA, dx, dz, target_type, target_value)
        if np.linalg.norm(r) < tol:
            return u, True
        try:
            du = np.linalg.solve(J, -r)
        except np.linalg.LinAlgError:
            return u, False
                                                                         
        step = damping * du
        u_new = u + step
        if u_new[0] <= 0 or u_new[2] <= 0:
            step *= 0.3
            u_new = u + step
        u = u_new
    J, r = _numeric_jacobian(u, w, EA, dx, dz, target_type, target_value)
    return u, np.linalg.norm(r) < tol * 100

def _initial_guesses(dx, dz, w, target_type, target_value):
    """A short list of (H0, V0_0, L0_0) candidates to try, in order."""
    Lc = max(np.hypot(dx, dz), 1e-6)
    guesses = []

    if target_type == CableTargetType.UNDEFORMED_LENGTH:
        L0_0 = max(target_value, Lc * 1.0001)
    else:
        L0_0 = Lc * 1.02

    if target_type == CableTargetType.HORIZONTAL_TENSION:
        H0_list = [target_value]
    elif target_type == CableTargetType.MAX_VERTICAL_SAG:
        sag0 = max(target_value, Lc * 0.01)
        H0_list = [w * dx ** 2 / (8.0 * sag0)] if dx > 1e-6 else [w * Lc]
    elif target_type in (CableTargetType.TENSION_I, CableTargetType.TENSION_J):
                                                                      
        H0_list = [target_value * f for f in (0.95, 0.7, 0.4, 0.15, 1.2)]
    else:
        sag_guess = 0.05 * Lc
        H0_list = [w * max(dx, Lc) ** 2 / (8.0 * sag_guess), w * Lc, 5 * w * Lc, 0.3 * w * Lc]

    for H0 in H0_list:
        H0 = max(H0, 1e-3)
        for frac in (0.5, 0.2, 0.8, 0.05, 0.95):
            V0_0 = (dz / Lc) * H0 * 2.0 - w * L0_0 * frac
            guesses.append((H0, V0_0, L0_0))
    return guesses

def solve_catenary_local(dx, dz, w, EA, target_type, target_value,
                          tol=1e-8, max_iter=60):
    """
    Solve the elastic catenary in the local (x,z) plane (z up), given the
    chord components dx (horizontal, >=0), dz (vertical rise, signed).
    Returns (H, V0, L0, converged: bool).
    """
    if dx < 1e-6:
                                                                     
        if target_type == CableTargetType.UNDEFORMED_LENGTH:
            L0 = target_value
        elif target_type in (CableTargetType.TENSION_I, CableTargetType.TENSION_J,
                              CableTargetType.HORIZONTAL_TENSION):
                                                                          
            L0 = abs(dz) / (1.0 + max(target_value, 0.0) / EA) if EA > 0 else abs(dz)
        else:
            L0 = abs(dz) * 0.999
        return 0.0, 0.0, max(L0, 1e-6), True

    if target_type == CableTargetType.MAX_VERTICAL_SAG:
        robust = _solve_max_vertical_sag_robust(
            dx, dz, w, EA, target_value, tol=tol, max_nfev=1200
        )
        if robust is not None:
            return robust[0], robust[1], robust[2], True

    for guess in _initial_guesses(dx, dz, w, target_type, target_value):
        u, ok = _solve_newton(guess, w, EA, dx, dz, target_type, target_value,
                               tol=tol, max_iter=max_iter)
        if ok and u[0] > 0 and u[2] > 0:
            return float(u[0]), float(u[1]), float(u[2]), True

    return _solve_via_continuation(dx, dz, w, EA, target_type, target_value, tol, max_iter)

def _target_residual_scalar(u, w, EA, dx, dz, target_type, target_value):
    """Just the third (target) residual component, for continuation steps."""
    return _residual(u, w, EA, dx, dz, target_type, target_value)

def _solve_via_continuation(dx, dz, w, EA, target_type, target_value,
                             tol=1e-8, max_iter=60, n_steps=25):
    Lc = max(np.hypot(dx, dz), 1e-6)

    if target_type == CableTargetType.HORIZONTAL_TENSION:
        easy_value = max(20.0 * w * Lc, target_value * 5.0, 10.0)
    elif target_type in (CableTargetType.TENSION_I, CableTargetType.TENSION_J):
        easy_value = max(20.0 * w * Lc, target_value * 5.0, 10.0)
    elif target_type == CableTargetType.UNDEFORMED_LENGTH:
        easy_value = Lc * 1.001                                            
    elif target_type in (CableTargetType.MAX_VERTICAL_SAG, CableTargetType.LOW_POINT_SAG):
        easy_value = max(0.005 * Lc, 1e-4)                                          
    else:
        return float("nan"), float("nan"), float("nan"), False

    for guess in _initial_guesses(dx, dz, w, target_type, easy_value):
        u, ok = _solve_newton(guess, w, EA, dx, dz, target_type, easy_value,
                               tol=tol, max_iter=max_iter)
        if ok and u[0] > 0 and u[2] > 0:
            break
    else:
        return float("nan"), float("nan"), float("nan"), False

    for frac in np.linspace(0.0, 1.0, n_steps)[1:]:
        step_target = easy_value + frac * (target_value - easy_value)
        u, ok = _solve_newton(u, w, EA, dx, dz, target_type, step_target,
                               tol=tol, max_iter=max_iter, damping=0.8)
        if not (ok and u[0] > 0 and u[2] > 0):
            return float("nan"), float("nan"), float("nan"), False

    return float(u[0]), float(u[1]), float(u[2]), True

def solve_cable_geometry(node_i, node_j, weight_per_length, EA,
                          target_type, target_value,
                          gravity_dir=(0.0, 0.0, -1.0),
                          n_points=21) -> CableSolveResult:
    """
    Main entry point. node_i / node_j: (x,y,z) tuples in global coords.
    weight_per_length: total distributed weight (self-weight + added
    weight), force per unit UNSTRESSED length, always >= 0, acting along
    gravity_dir.
    EA: axial stiffness (material.E * cable_section.area).
    target_type: CableTargetType (or its combo-box string, auto-converted).
    target_value: value paired with target_type (consistent units with
    the rest of the geometry/EA inputs -- caller is responsible for unit
    conversion, same convention as your other dialogs' get_data()).
    """
    if isinstance(target_type, str):
        target_type = CableTargetType.from_combo_text(target_type)

    dx, dz, Lc, ex, ez, p_i = _local_frame(node_i, node_j, gravity_dir)
    w = max(float(weight_per_length), 0.0)

    if target_type in (CableTargetType.MAX_VERTICAL_SAG, CableTargetType.LOW_POINT_SAG) and target_value <= 1e-12:
        return CableSolveResult(
            converged=False,
            message="Sag target must be greater than zero when cable weight is nonzero."
        )

    if w < 1e-9:
                                                                    
        if target_type == CableTargetType.UNDEFORMED_LENGTH:
            L0 = target_value
            T = EA * (Lc - L0) / L0 if L0 > 1e-9 else 0.0
        elif target_type in (CableTargetType.HORIZONTAL_TENSION,
                              CableTargetType.TENSION_I, CableTargetType.TENSION_J):
            T = target_value
            L0 = EA * Lc / (EA + T) if (EA + T) > 1e-9 else Lc
        else:
            return CableSolveResult(
                converged=False,
                message="Sag-based targets require nonzero self-weight."
            )
        result = CableSolveResult(
            converged=True, H=T, V0=0.0, Vj=0.0, L0=L0,
            deformed_length=Lc, T_i=T, T_j=T,
            max_sag=0.0, low_point_sag=0.0,
            is_compression_anywhere=(T <= 0),
        )
        s_vals = np.linspace(0.0, L0, n_points)
        for k, s in enumerate(s_vals):
            t = s / L0 if L0 > 0 else 0.0
            xyz = tuple(np.asarray(node_i) + t * (np.asarray(node_j) - np.asarray(node_i)))
            result.points.append(CablePoint(float(s), float(t), xyz, 0.0))
        return result

    H, V0, L0, ok = solve_catenary_local(dx, dz, w, EA, target_type, target_value)
    if not ok:
        hint = ""
        if target_type in (CableTargetType.TENSION_I, CableTargetType.TENSION_J):
            hint = (" Tension-at-end targets have a physical MINIMUM achievable "
                     "value for a given span and weight (the fully-sagged, "
                     "near-zero-horizontal-tension limit) -- a target below "
                     "that minimum has no solution. Try a larger tension, or "
                     "reduce the weight/span.")
        elif target_type in (CableTargetType.MAX_VERTICAL_SAG, CableTargetType.LOW_POINT_SAG):
            hint = (" Sag targets have a physical MAXIMUM for a given chord "
                     "and weight if the cable is also constrained not to "
                     "exceed a sensible unstressed length -- an excessively "
                     "large sag request may have no converged solution.")
        return CableSolveResult(
            converged=False,
            message="Target could not be resolved to a valid cable state." + hint,
        )

    Vj = V0 + w * L0
    T_i = float(np.hypot(H, V0))
    T_j = float(np.hypot(H, Vj))
    max_sag = _max_vertical_sag(H, V0, w, EA, L0, dx, dz)
    low_sag, low_ok = _low_point_sag(H, V0, w, L0, dz)

    s_vals = np.linspace(0.0, L0, n_points)
    x_local, z_local = _shape_xz(H, V0, w, EA, s_vals)
    Lc_local = max(np.hypot(dx, dz), 1e-9)

    points = []
    for k, s in enumerate(s_vals):
        xl, zl = float(x_local[k]), float(z_local[k])
        global_xyz = tuple(np.asarray(p_i) + xl * ex + zl * ez)
        sag_k = float((dz / dx) * xl - zl) if abs(dx) > 1e-12 else 0.0
        points.append(CablePoint(float(s), float(s / L0), global_xyz, sag_k))

    deformed_length = float(np.sum(np.hypot(np.diff(x_local), np.diff(z_local))))

    return CableSolveResult(
        converged=True,
        H=H, V0=V0, Vj=Vj, L0=L0, deformed_length=deformed_length,
        T_i=T_i, T_j=T_j,
        max_sag=max_sag,
        low_point_sag=(low_sag if low_ok else float("nan")),
        is_compression_anywhere=(H <= 0 or V0 * Vj < -1e-9 and min(T_i, T_j) <= 0),
        points=points,
    )

if __name__ == "__main__":
    node_i = (0.0, 0.0, 10.0)
    node_j = (40.0, 0.0, 10.0)                                         
    EA = 2.0e5                                                               
    w = 0.5                                       

    print("=== Target: Max Vertical Sag = 3.0 m ===")
    res = solve_cable_geometry(node_i, node_j, w, EA,
                                CableTargetType.MAX_VERTICAL_SAG, 3.0)
    print(f"converged={res.converged}  H={res.H:.4f}  L0={res.L0:.4f}  "
          f"T_i={res.T_i:.4f}  T_j={res.T_j:.4f}  max_sag={res.max_sag:.4f}")

    print("\n=== Re-solve same case via Undeformed Length target (should match H, sag) ===")
    res2 = solve_cable_geometry(node_i, node_j, w, EA,
                                 CableTargetType.UNDEFORMED_LENGTH, res.L0)
    print(f"converged={res2.converged}  H={res2.H:.4f}  max_sag={res2.max_sag:.4f}  "
          f"(expect H≈{res.H:.4f}, sag≈{res.max_sag:.4f})")

    print("\n=== Target: Tension at I-End = 16.0 (above the feasible minimum ~15.09 for this span/weight) ===")
    res3 = solve_cable_geometry(node_i, node_j, w, EA,
                                 CableTargetType.TENSION_I, 16.0)
    print(f"converged={res3.converged}  T_i={res3.T_i:.4f} (expect 16.0)  "
          f"T_j={res3.T_j:.4f}  max_sag={res3.max_sag:.4f}")

    print("\n=== Target: Tension at I-End = 15.0 (BELOW feasible minimum -- should correctly fail) ===")
    res3b = solve_cable_geometry(node_i, node_j, w, EA,
                                  CableTargetType.TENSION_I, 15.0)
    print(f"converged={res3b.converged}  message={res3b.message}")

    print("\n=== Inclined cable, Horizontal Tension = 20.0 ===")
    node_j_incl = (40.0, 0.0, 4.0)                         
    res4 = solve_cable_geometry(node_i, node_j_incl, w, EA,
                                 CableTargetType.HORIZONTAL_TENSION, 20.0)
    print(f"converged={res4.converged}  H={res4.H:.4f} (expect 20.0)  "
          f"L0={res4.L0:.4f}  low_point_sag={res4.low_point_sag}")
