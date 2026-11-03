import numpy as np
from element_library import (get_local_stiffness_matrix,
                            get_geometric_stiffness_matrix,
                            get_rotation_matrix)

"""
================================================================================
ul_element.py -- 3D Updated-Lagrangian frame element for METUFIRE
================================================================================
Drop-in alternative to corotational_beam.py: identical constructor signature,
identical call signature, identical 3-tuple return contract, so
nonlinear_engine.py selects it purely from the load case's "formulation" setting
and the corotational call path is never entered.

--------------------------------------------------------------------------------
1. WHAT MAKES THIS UPDATED-LAGRANGIAN
--------------------------------------------------------------------------------
The reference configuration is C_n, the LAST CONVERGED configuration.  Inside a
load step the following are FROZEN:

    state.L_ref     reference chord length
    state.E_ref     reference element triad -- does NOT follow the chord
    state.R1_ref    reference nodal triads
    state.R2_ref
    the six stored natural resultants (section 3)

and the unknown is the INCREMENTAL displacement measured from C_n.  Between
steps, commit() advances all of them.  The answer is therefore a function of the
load-step sequence and converges as the step size shrinks; that is ordinary
incremental-analysis behaviour, not a defect, and it is not argued about here.

The point of having this element is arbitration.  It reaches the answer by a
different route from the corotational element:

    corotational                        updated Lagrangian (this file)
    ------------------------------      ---------------------------------------
    frame follows the chord every       frame frozen at C_n for the whole step
      residual evaluation
    rigid-body motion filtered OUT      rigid-body motion ALSO filtered out, by
      of p_local by construction          the INCREMENTAL frame rotation
                                          R_inc = E_cur E_ref^T.  See section 6:
                                          an earlier draft of this file claimed
                                          the initial-stress matrix could carry
                                          it instead.  That claim was MEASURED
                                          AND IS FALSE for this tree's k_geo.
    p_local carries the TOTAL local     dp carries the INCREMENTAL local
      rotation from C_0 -- 46 deg on      rotation from C_n -- bounded by the
      the n=1 mesh, fed into a LINEAR     step size, so k_local is evaluated
      k_local                             where it is actually valid
    f recomputed from TOTAL             resultants ACCUMULATED increment by
      displacement each time              increment from the stored state
    needs a hand-derived K_spin         no spin term exists: the frame is frozen
                                          for the whole Newton loop

Where the two agree, neither is being flattered by its own bookkeeping.

--------------------------------------------------------------------------------
2. INCREMENTAL KINEMATICS
--------------------------------------------------------------------------------
The current triad E_cur is built FIRST, from the current chord and the current
geodesic-mean nodal triad (the same construction corotational_beam.py uses, so
the two elements cannot disagree about what "local" means).  The incremental
frame rotation is then

    R_inc = E_cur @ E_ref^T          (global-axes rotation C_n -> C_n+1 of the
                                      element frame itself)

and the deformational increment is what is LEFT of each node's incremental
rotation once R_inc is removed, pulled back into reference-local axes:

    th1 = E_ref^T log( R_inc^T (R1 R1_ref^T) )
    th2 = E_ref^T log( R_inc^T (R2 R2_ref^T) )

    dp[3:6]  = th1
    dp[6]    = L_rec - L_flex        (chord stretch)
    dp[9:12] = th2

Everything else in dp is identically zero.  The incremental transverse
translations do NOT appear as dp entries: they enter through E_cur (which
direction the chord now points) and through L_rec (how much longer it got).
That is the whole of their content -- a transverse end translation IS a chord
rotation plus a chord extension -- so nothing is discarded by not listing them.

Consequence, and it is the reason the file is written this way: under ANY finite
rigid motion, R_inc^T (Ri Ri_ref^T) = I exactly and L_rec = L_flex exactly, so
dp = 0 identically and the resultants are unchanged to the last bit.  There is
no O(dtheta^2) rigid-motion residual to be removed by step refinement, because
there is no rigid-motion residual at all.  Section 6 records the measurement
that forced this construction, and what it costs.

--------------------------------------------------------------------------------
3. NATURAL RESULTANTS AND CURRENT-CONFIGURATION EQUILIBRIUM
--------------------------------------------------------------------------------
The stored state is six scalars, not a 12-vector:

    N                axial force
    T                St-Venant torque
    My1, My2         end moments about local y  (x-z plane bending, DOFs 4, 10)
    Mz1, Mz2         end moments about local z  (x-y plane bending, DOFs 5, 11)

The two transverse shears are NOT stored.  They are recovered from statics in
the CURRENT configuration every call, at the current chord length L_c:

    sum(M_z) about node 1:   Mz1 + Mz2 + L_c * f[7] = 0   ->  f[7] = -(Mz1+Mz2)/L_c
    sum(M_y) about node 1:   My1 + My2 - L_c * f[8] = 0   ->  f[8] = +(My1+My2)/L_c

(the sign difference is the cross product r x F with r = L_c*e1: a force along
local y produces +z moment, a force along local z produces -y moment), giving

    f_l = [ -N, (Mz1+Mz2)/L_c, -(My1+My2)/L_c, -T, My1, Mz1,
            +N, -(Mz1+Mz2)/L_c, +(My1+My2)/L_c, +T, My2, Mz2 ]

and then f_global = blockdiag(E_cur) @ f_l.

Two consequences, both deliberate:

  * sum(F) = 0 and sum(M about node 1) = 0 hold EXACTLY, to machine precision,
    in the CURRENT configuration, for every state, converged or not.  They are
    identities of the construction, not properties to be hoped for.  Rotating a
    stored 12-vector by a frozen triad instead -- the first thing one writes --
    does NOT have this property: it is equilibrated with respect to C_n's
    geometry, so it carries a spurious moment of order (chord rotation) x (shear)
    which the global Newton loop absorbs into the reactions.

  * storing natural resultants removes the objective-transport question
    entirely.  There is no Lambda operator to get wrong, because the resultants
    are defined relative to the element's own axes and are simply re-read in the
    current triad.  This is the standard co-rotating (objective) choice for
    stress resultants, and test_ul_element.py verifies it directly instead of
    trusting it.

Discarding k_geo's transverse-force rows loses no physics.  The P-Delta content
is the coupling from transverse displacement and end rotation INTO the end
moments -- kg[5,1], kg[11,1], kg[5,5], kg[5,11] and their y-plane twins -- and
all of those are retained.  k_geo's own transverse rows are not moment-consistent
anyway (sum(M) over column 1 is -30*c*L, not 0), because they represent the axial
force working through the deformed shape in the REFERENCE frame; recovering the
shear from statics in the CURRENT frame captures the same P-Delta moment more
accurately and exactly equilibrated.

--------------------------------------------------------------------------------
4. TERM INVENTORY -- read this before trusting a number
--------------------------------------------------------------------------------
IMPLEMENTED, derived rather than asserted:

  (1) Linear Timoshenko constitutive relation, reused VERBATIM from
      element_library.get_local_stiffness_matrix, so the phi_y<->I33<->As2 and
      phi_z<->I22<->As3 pairings cannot drift from the linear solver's.  Pinned
      by test_ul_element.py::test_shear_pairing.

  (2) Axial-force-driven initial stress, including the Wagner term
      P*(I22+I33)/A/L on the torsion DOFs.  Reused VERBATIM from
      element_library.get_geometric_stiffness_matrix.

  (3) Second-order (bowing / curvature-shortening) axial strain, with the FULL
      cubic field, not the rotation-only reduction.

      Derivation.  von Karman membrane strain, averaged over the element (the
      axial force is constant along a 2-node element with no distributed axial
      load):
          eps_bow = (1/L) * 0.5 * integral_0^L (v'^2 + w'^2) dx
      The consistent geometric stiffness is BY DEFINITION the Hessian of
      N * 0.5*integral(v'^2 + w'^2) dx with respect to the nodal DOFs.  So with
      G := k_geo evaluated at unit axial force,
          0.5 * integral(v'^2 + w'^2) dx = 0.5 * dp^T G dp
      because a quadratic form equals half its Hessian contracted twice, and
      therefore
          eps_bow = dp^T G dp / (2 L)
      exactly -- G is literally the Hessian of the integral being evaluated, so
      this is an identity for this k_geo, not a fit.  Cross-checked in
      test_ul_element.py against the closed form (2 t1^2 - t1 t2 + 2 t2^2)/30
      derived by hand in UL_kinematics_decision.md section 5.2.

      This term is necessary because get_geometric_stiffness_matrix has NO
      entries in axial rows 0 and 6.  Without it the second-order effect would
      appear in the TANGENT but be missing from the axial FORCE -- precisely the
      half-a-pair asymmetry that drove ||K-K^T||/||K|| to 16.64% in the
      corotational patch.  Both halves are present here by construction.

NOT IMPLEMENTED -- known missing, deliberately NOT guessed:

  (A) MOMENT- AND TORQUE-DRIVEN INITIAL STRESS.
      get_geometric_stiffness_matrix is a function of the axial force alone.  A
      complete UL initial-stress matrix also has blocks driven by the stored
      My1, My2, Mz1, Mz2 and T.  Those are the discrete image of the
      bending-torsion coupling derived in UL_kinematics_decision.md 5.1,

          M_z gains  + E*I33 * w' * thx'
          M_y gains  - E*I22 * v' * thx'

      They are second order in the INCREMENT, so they vanish under step
      refinement; they do NOT vanish from the stored state, and they are exactly
      the class of term that acts at large twist.  THEY ARE NOT IN THIS FILE.
      Any twist-related discrepancy this element shows must be read with that in
      mind.  Closing it is the next derivation, not a tuning knob.

  (B) Consistent tangent of term (3).  K_approx omits the derivative of the
      eps_bow axial force with respect to dp (an EA/L * (G dp) outer-product
      term) and omits the derivative of the statics shear recovery with respect
      to L_c.  K_approx is therefore APPROXIMATE: it changes Newton's
      convergence rate, not the converged root, because convergence is tested on
      the residual.  For production runs set use_fd_tangent: true and the engine
      differences the residual instead -- exact by construction, and what
      tee.mf already uses.

--------------------------------------------------------------------------------
5. LOG MAP -- why this file does not call rotation_utils.rotation_to_vector
--------------------------------------------------------------------------------
That function extracts the angle with arccos, whose relative error is
~sqrt(eps_machine)/t -- about 1% at t = 1e-6 -- and which returns exactly 0.0
below t = 1e-8.  A UL element differentiates a residual built from INCREMENTAL
rotations, which are small by construction and are perturbed by ~1e-6 during
finite differencing, so that is the worst possible place to use it.  _log_map
below uses arctan2 and holds full relative precision uniformly down to t = 0.
Nothing in rotation_utils.py is modified, so the corotational element is
bit-for-bit unaffected.

--------------------------------------------------------------------------------
6. THE OBJECTIVITY MEASUREMENT, AND THE FALSE CLAIM IT KILLED
--------------------------------------------------------------------------------
An earlier draft of this header asserted that a UL element need NOT filter rigid
body motion out of the increment, because "the initial-stress matrix carries it,
which is exactly that matrix's job in UL".  That is a textbook statement and it
is FALSE FOR THIS TREE.  Rather than argue about it, four candidate force
updates were implemented and driven by a pure rigid rotation of a stressed
element -- for which the correct answer is known exactly, f -> blockdiag(Rw) f.
Relative error in the updated resultants, worst over seeds, from
test_ul_element.py's harness:

    construction                                     theta=0.003   theta=0.4
    (a) dp from raw global increment, k_local only      ~1e-2       2.744e-01
    (b) bd(E_ref) @ (f_ref + (k_local+k_geo) @ dp)     1.318e-02    2.138e+02
    (c) as (b) but with the triad refreshed first       first order in theta
    (d) chord-filtered increment (THIS FILE)            5.110e-16   5.110e-16

(b) is the construction the old header advocated, and it is the WORST of the
four -- two orders of magnitude worse than doing nothing clever at all.  The
reason is specific and checkable: this tree's get_geometric_stiffness_matrix has
NO entries in axial rows 0 and 6, and its transverse rows are not
moment-consistent (sum(M) over column 1 is -30*c*L, not 0).  It is a bending
geometric stiffness, not a full initial-stress matrix.  It cannot transport an
axial force through a finite rotation because it has no axial row to do it with.
So the "job" the old claim assigned to it is a job this matrix does not do.

Two things follow, and both matter for how this element should be read:

  * There is NO step-size requirement arising from objectivity.  dp is
    identically zero under rigid motion, so the property is exact at any step
    size, not asymptotic.  Step-count dependence of the FINAL ANSWER is a
    separate and ordinary matter -- it is the convergence of an incremental
    scheme, SAP2000 has it too, and it is not evidence of anything wrong here.

  * Filtering the chord rotation does NOT make this element a corotational
    element in disguise, and objectivity was never what distinguished them.  The
    difference is in section 1's second row: corotational feeds the TOTAL local
    rotation from C_0 into a LINEAR k_local -- 46 degrees on the n=1 portal mesh
    -- while this element feeds only the increment from C_n and accumulates the
    resultants.  That is the documented coarse-mesh failure mode, and it is the
    one this element exists to test.

WHAT IT COSTS -- the axial conditioning floor.
For the PART 1 section, EA/L = 1.067e8 while 12EI/L^3 = 1.185e5: a ratio of 900.
The axial force is therefore recovered as a difference of much larger numbers,
and the measured amplification is

    1 ulp of error in the chord length  ->  5.9e-13 relative error in N

verified directly: the residual in test [5] tracks |L_cur/3 - 1| perfectly
(2.220e-16 -> 7.894e-13, 1.110e-16 -> 3.947e-13, 0 -> ~1e-16), and is unchanged
if the rigid translation is set to zero, so the ulp originates in Rw @ (p2-p1)
not preserving the vector's length to the last bit -- floating-point rotation,
nothing to do with the formulation.  5.9e-13 is the floor for any axial-force
comparison with this element.  It is 10 orders of magnitude below the 0.1%
target, so it is a fact to record, not a problem to solve.

--------------------------------------------------------------------------------
7. THE INITIAL-SLOPE COUPLING TERM, AND WHY THE AXIAL FORCE IS TOTAL
--------------------------------------------------------------------------------
This section exists because an earlier version of this file had a term missing,
the measurement below found it, and the fix is derived here rather than asserted.

THE DERIVATION.
The Green-Lagrange axial strain of a beam whose axis carries transverse slope v'
is

    eps(x) = u' + 0.5 v'^2                            (and likewise in w)

Refer that to C_n, where the slope is ALREADY v'_n and the increment is Dv:

    v'        = v'_n + Dv'
    eps_total = u'_n + Du' + 0.5 (v'_n + Dv')^2
              = [ u'_n + 0.5 v'_n^2 ]  +  [ Du' + v'_n Dv' + 0.5 Dv'^2 ]
              =        eps_n           +            Deps

so

    Deps = Du'  +  v'_n Dv'  +  0.5 Dv'^2
                   ^^^^^^^^^
                   the initial-slope (initial-displacement) coupling term

Drop that middle term and accumulate over n_steps equal increments
Dv' = v'_tot / n_steps:

    sum_{i=1..n} 0.5 (v'_tot/n)^2  =  0.5 v'_tot^2 / n

which is 1/n_steps of the truth.  The bowing strain then VANISHES under step
refinement instead of converging to it.  This is not a step-size preference and
not a convergence-tolerance question: it is a term that must survive to the
limit and does not.  Refining the step makes it WORSE, monotonically.

THE MEASUREMENT THAT FOUND IT (rollup.py, before the fix).
Predicted first, measured second.  If the bowing were a sum of squares of
increments then the error must fall like 1/n_steps, i.e. halve when the steps
double.  Measured ratios on the 360-degree closure: 1.88, 1.94, 1.97 -> 2.00.
Independently, on the 90-degree n=2 step study the UL error climbed monotonically
toward the LEGACY corotational value as the steps were refined --

    5 steps 5.76e-02   10 steps 6.42e-02   20 steps 6.74e-02   40 steps 6.91e-02
    legacy corotational_beam.py, step-invariant:  7.068965e-02

-- because legacy corot has NO bowing term at all, and a bowing term that decays
like 1/n_steps degenerates into exactly that as n_steps grows.  Two independent
measurements, one mechanism.

THE FIX, AND WHY THE STRONGER OF THE TWO OPTIONS WAS TAKEN.
The minimal repair is to add v'_n Dv' to an incremental axial accumulator.  This
file does something stronger instead: it computes the axial force from the TOTAL
deformational strain,

    N         = EA (eps_chord + eps_bow + eps_wag)
    eps_chord = (L_cur^2 - L0^2) / (2 L0^2)        exact Green-Lagrange of the chord
    eps_bow, eps_wag                               from the TOTAL deformational
                                                   end rotations th1_tot, th2_tot

For a linear-elastic element that is EXACT and path-independent; the incremental
form is only an approximation to it.  Since EA/L is 900x the bending stiffness
(section 6), the axial force is the single quantity that cannot afford an
approximation, and this removes it from the incremental error budget entirely.
The MOMENTS remain incremental, which is what preserves the bounded-local-
rotation character the element exists for -- see section 1, second row.

THE SECOND DEFECT IN THE SAME MEASUREMENT: L_flex IS THE MATERIAL LENGTH.
An earlier draft referred the constitutive integrals to the CURRENT chord.
Bending an element through 90 degrees shortens its chord by

    chord / arc = sin(t/2)/(t/2) = 0.900        a 10% shortening

with zero material stretch.  Feeding that into k_local = 4EI/L stiffens bending
by 1/0.900 = 11% for a purely geometric reason, and the two errors partly cancel,
which is why neither was visible on its own.  corotational_beam.py refers to the
material length; this file now does too.

RESULT AFTER BOTH CHANGES (rollup.py, plane x-z, error = |tip - exact arc|).
    Phi = 90 deg, 8 steps      n=1        n=2        n=4        n=8      order
    legacy corotational        2.99e-01   7.07e-02   1.74e-02   4.34e-03  p=2.00
    this element               2.71e-02   1.49e-03   9.01e-05   5.59e-06  p=4.01

    Phi = 360 deg, n=4, 40 steps, |tip| is a pure error:
    legacy corotational 2.832090e-15 m     this element 4.452123e-15 m
    (this element was 4.158501e-03 m before the fix -- 12 orders of magnitude)

    Phi = 90 deg, n=2, at 5 / 10 / 20 / 40 steps:
    1.487052e-03 at EVERY step count, to all 7 printed digits.

The step-invariance is the direct confirmation that the term now survives
refinement.  The order rising from 2 to 4 is the expected payoff of a correct
second-order axial strain.

READ THIS BEFORE QUOTING THE TABLE.  It is NOT a claim of superiority over the
PRODUCTION corotational element in Ahmed's tree, which already has the bowing
term promoted to default and would also show p=4 here.  The comparison column is
the LEGACY corotational_beam.py in this sandbox, which has no bowing term.  What
this element is supposed to add over the production corotational element is the
bounded local rotation into k_local, and a moment-loaded roll-up at 90 degrees
does not isolate that.  The portal-frame ladder is what tests it.

================================================================================
8.  WHAT SAP2000 ACTUALLY IS, AND WHAT THIS ELEMENT IS THEREFORE FOR
    (measured 2026-08-22; this supersedes the framing in section 6)
================================================================================
Ahmed ran SAP2000 on the planar (fy=0) portal frame at n=4 AND n=10 elements per
member and exported every joint, including the interior member nodes.  That was
the first SAP export in this project at n>=4, and it settles what "the SAP gap"
was.

    SAP2000 IS the legacy corotational element.  Not close to -- the same.

Max per-component residual, legacy corotational_beam.py vs SAP, 25 steps:

    mesh   joints   max|dU1|     max|dU3|     max|dR2|     outside SAP's
                                                           +-5e-7 print box
    n=4      11     4.12e-07 m   4.91e-07 m   4.21e-07 rad   0 / 11
    n=10     29     4.88e-07 m   5.07e-07 m   4.77e-07 rad   1 / 29 (1.01 ulp)

Base My: n=4 SAP -1126.0115 / ours -1126.0115.  n=10 SAP -1125.9634 / ours
-1125.9633.  Worst |du|/|u| 0.0011% at n=4, 0.0056% at n=10.  The problem is
strongly nonlinear (U1 = 0.336 m over a 3 m column, R2 = 0.166 rad, beam sag
0.30 m) and U3 moves 26% between n=1 and n=10, so reproducing the whole
h-sequence to SAP's last printed digit along full member profiles is a
formulation identity, not a near-linear coincidence.  SAP is chord-only.

All three converge to the SAME answer.  Fit f(n) = f_inf + C n^-p, colA top:

                      U1  p/f_inf          U3  p/f_inf          R2  p/f_inf
    SAP2000        1.56 / 0.3367739     1.57 / -0.0223622    1.92 / 0.1659273
    legacy corot   1.83 / 0.3364857     1.53 / -0.0223854    2.33 / 0.1657961
    this element   1.60 / 0.3368478     1.26 / -0.0223926    2.00 / 0.1658970

Limits agree to 0.09-0.14%.  Independently, the legacy-vs-this separation is
itself O(h^2) and dying: U3 differs by 14.756 / 4.293 / 1.370 / 0.351 / 0.220 %
at n=1/2/4/8/10, implied order 1.78, 1.65, 1.97, 2.09.  Two elements whose
difference vanishes at second order share a limit.  The bowing term moves the
error CONSTANT, not the answer.

Distance from SAP's own converged U3:

                    n=1      n=2      n=4      n=8      n=10
    SAP2000        21.15%     --      2.40%     --      0.57%
    legacy corot   21.15%   7.31%     2.40%   0.78%     0.57%
    this element    7.50%   3.15%     1.04%   0.43%     0.35%

CONSEQUENCES, and they are the reason this file exists at all:

  * The coarse-mesh "SAP gap" is SAP's own discretisation error.  It cannot be
    eliminated by a better element -- only INHERITED.  Legacy inherits it
    exactly.  No formulation can beat legacy against a SAP n=1 or n=2 row,
    because legacy is already exact against those rows to 5e-7 m.
  * So use LEGACY (formulation = "Corotational") whenever the acceptance test is
    "reproduce SAP".  Use THIS element when the acceptance test is "be right".
    They are not competing on the same axis, and neither is broken.
  * The 3.66%-vs-0.82% result at 30 kN n=2 quoted in section 6 is REAL but is
    NOT a test of the 3D coupling.  At n=2 SAP is 7.3% from its own converged
    answer on planar U3 alone, so that comparison is dominated by who inherits
    SAP's coarse bias -- exactly like the planar rows were.  Every 3D SAP row in
    this project is at n=1 or n=2.  The 3D torsion-bending coupling is therefore
    UN-ADJUDICATED in both directions: there is no evidence this element is
    worse in 3D, and no evidence legacy is right in 3D.  Do not quote 3.66% as a
    3D verdict.  The datum that would settle it is a SAP run on the full 3D
    model at fy = 30 kN, n = 10, raw joint rows.

Reproduce all of the above with sap_planar.py / sap_planar_norm.py / chk_ulp.py /
limitfit.py, which carry Ahmed's SAP exports embedded.
"""

def _skew(v):
    return np.array([[0.0, -v[2], v[1]],
                     [v[2], 0.0, -v[0]],
                     [-v[1], v[0], 0.0]])

def _log_map(R):
    """
    Rotation matrix -> rotation vector, via arctan2.

        axis_vec = 0.5*(R - R^T) stacked   ==  sin(t) * n
        c        = 0.5*(trace(R) - 1)      ==  cos(t)
        t        = arctan2(|axis_vec|, c)      accurate for all t in [0, pi]
        result   = axis_vec * (t / sin t)

    t/sin(t) -> 1 smoothly as t -> 0 and arctan2 keeps full relative precision on
    small s, so the small-angle limit needs no special case beyond avoiding 0/0.
    The t -> pi branch is separate because sin t -> 0 there while t does not; it
    is not exercised by incremental UL rotations but is implemented so this is a
    correct general log map.
    """
    R = np.asarray(R, dtype=float)
    axis_vec = 0.5 * np.array([R[2, 1] - R[1, 2],
                               R[0, 2] - R[2, 0],
                               R[1, 0] - R[0, 1]])
    s = np.linalg.norm(axis_vec)
    c = min(1.0, max(-1.0, 0.5 * (np.trace(R) - 1.0)))

    if s < 1e-150:
        if c > 0.0:
            return axis_vec                              
    elif c > -0.9:
        t = np.arctan2(s, c)
        return axis_vec * (t / s)

    t = np.arctan2(s, c)
    B = 0.5 * (R + R.T) - c * np.eye(3)
    n = B[:, int(np.argmax(np.diag(B)))].copy()
    nn = np.linalg.norm(n)
    if nn < 1e-300:
        return np.zeros(3)
    n /= nn
    if np.dot(n, axis_vec) < 0.0:
        n = -n
    return n * t

def _exp_map(v):
    """Rodrigues. Local copy so this file adds no dependency on shared code."""
    v = np.asarray(v, dtype=float)
    t = np.linalg.norm(v)
    S = _skew(v)
    if t < 1e-14:
        return np.eye(3) + S + 0.5 * (S @ S)
    Sn = S / t
    return np.eye(3) + np.sin(t) * Sn + (1.0 - np.cos(t)) * (Sn @ Sn)

def _blockdiag4(M):
    out = np.zeros((12, 12))
    for b in range(4):
        out[3 * b:3 * b + 3, 3 * b:3 * b + 3] = M
    return out

def _element_triad(p1, p2, R1, R2, R0, fallback):
    """
    Current element triad.

    Construction is deliberately IDENTICAL to corotational_beam.py lines
    118-145: e1 along the chord, e2 from the geodesic-mean nodal triad's
    reference y-axis orthogonalised against e1, e3 = e1 x e2.  Reused rather
    than re-invented for two reasons: it is already validated, and
    nonlinear_engine._compute_reprojected_target_free reads state.R_r to
    re-integrate coord='Global' member loads, so a different triad here would
    silently alter the follower-load path instead of the element.
    """
    chord = p2 - p1
    L = np.linalg.norm(chord)
    e1 = chord / L

    v_y_init = R0[:, 1]
    R_mean = R1 @ _exp_map(0.5 * _log_map(R1.T @ R2))
    v_y_avg = R_mean @ v_y_init

    v_y_ort = v_y_avg - np.dot(v_y_avg, e1) * e1
    nrm = np.linalg.norm(v_y_ort)
    if nrm > 1e-12:
        e2 = v_y_ort / nrm
    else:
        e2 = fallback[:, 1].copy()
        e2 = e2 - np.dot(e2, e1) * e1
        e2 /= np.linalg.norm(e2)

    return np.column_stack((e1, e2, np.cross(e1, e2))), L

def natural_to_local_force(N, T, My1, My2, Mz1, Mz2, L_c):
    """
    Six natural resultants -> the 12-vector of local end forces, with the
    transverse shears supplied by statics at the current chord length L_c.

    Exact identities by construction, for any inputs:
        f[0] + f[6] = 0,  f[1] + f[7] = 0,  f[2] + f[8] = 0
        f[3] + f[9] = 0
        f[4] + f[10] - L_c*f[8] = 0
        f[5] + f[11] + L_c*f[7] = 0
    i.e. sum(F) = 0 and sum(M about node 1) = 0 to machine precision.
    """
    Vy = (Mz1 + Mz2) / L_c
    Vz = -(My1 + My2) / L_c
    return np.array([-N, Vy, Vz, -T, My1, Mz1,
                     N, -Vy, -Vz, T, My2, Mz2], dtype=float)

def local_force_to_natural(f):
    """Inverse of the map above, reading only the six equilibrium-independent
    entries. The transverse rows are ignored on purpose -- see section 3."""
    return (0.5 * (f[6] - f[0]),         
            0.5 * (f[9] - f[3]),         
            f[4], f[10],                        
            f[5], f[11])                        

class ElementULState:
    """
    Persistent per-element Updated-Lagrangian state.  Constructor signature is
    byte-identical to ElementCorotState so nonlinear_engine.py builds either
    from the same call site.
    """

    def __init__(self, p1_0, p2_0, beta_deg, section, material, L_clear, L_tor):
        p1_0 = np.asarray(p1_0, dtype=float)
        p2_0 = np.asarray(p2_0, dtype=float)

        self.L0 = float(np.linalg.norm(p2_0 - p1_0))
        self.L_clear = L_clear
        self.L_tor = L_tor
        self.rigid_zone_total = max(self.L_tor - self.L_clear, 0.0)

        beta_eff = beta_deg - np.degrees(section.get('theta_p', 0.0))
        self.R0 = get_rotation_matrix(p1_0, p2_0, beta_eff)
        self.R0 = self.R0.T                                                    

        self.section = section
        self.material = material

        self.p1_ref = p1_0.copy()
        self.p2_ref = p2_0.copy()
        self.L_ref = self.L0
        self.E_ref = self.R0.copy()
        self.R1_ref = np.eye(3)
        self.R2_ref = np.eye(3)

        self.N_ref = 0.0
        self.T_ref = 0.0
        self.My1_ref = 0.0
        self.My2_ref = 0.0
        self.Mz1_ref = 0.0
        self.Mz2_ref = 0.0

        self.R_r = self.R0.copy()

        self._pending = None

    def flex_length(self, L_of_config, is_strict_statics):
        """
        Flexible (clear) length referred to a given configuration length.

        Corotational uses state.L_clear -- the ORIGINAL clear length -- when not
        in strict-statics mode.  A UL element must refer its integrals to C_n, so
        the clear length advances by exactly the amount the chord has:

            L_flex = L_clear + (L_config - L0)

        With zero rigid end zones (L_clear == L0, which is this model) that is
        exactly L_config, the textbook UL choice.  With rigid zones it holds the
        rigid length constant and lets the flexible part carry the stretch, the
        only behaviour consistent with those zones being rigid.
        """
        if is_strict_statics:
            return max(L_of_config - self.rigid_zone_total, 1e-9)
        return max(self.L_clear + (L_of_config - self.L0), 1e-9)

    def commit(self):
        """
        Advance C_n -> C_n+1.  Called ONCE per converged load step by
        nonlinear_engine.py, after node_rot[*].R has been composed to the
        converged orientation.  No-op if the element has not been evaluated
        since the last commit.

        Follows UL_kinematics_decision.md section 3: positions, nodal triads,
        element triad, reference length, resultants.  The resultants need no
        rotation operator -- they are natural (element-relative) scalars and are
        simply re-read in the new triad, which is the objective choice.
        """
        if self._pending is None:
            return
        p1, p2, R1, R2, E_new, L_new, nat = self._pending

        self.p1_ref = p1.copy()
        self.p2_ref = p2.copy()
        self.R1_ref = R1.copy()
        self.R2_ref = R2.copy()
        self.E_ref = E_new.copy()
        self.L_ref = float(L_new)
        (self.N_ref, self.T_ref,
         self.My1_ref, self.My2_ref,
         self.Mz1_ref, self.Mz2_ref) = nat
        self._pending = None

def compute_ul_element(state: ElementULState,
                       p1_current, p2_current,
                       R_node1, R_node2,
                       is_strict_statics: bool = False,
                       fef_local: np.ndarray = None):
    """
    Returns (f_global, K_approx, N_axial) -- same contract as
    corotational_beam.compute_corotational_element.

    f_global   internal force, GLOBAL axes, EXCLUDING fef_local.  The engine
               carries member loads on the external side; corotational does the
               same (its f_local = (k_local + k_geo) @ p_local drops fef too).
    K_approx   blockdiag(E_cur) (k_local + k_geo) blockdiag(E_cur)^T, symmetric.
               Approximate -- see term (B) in the header.  No spin term is
               needed or present.
    N_axial    axial force INCLUDING the fef contribution, matching what
               corotational returns, since the engine feeds it to the P-Delta
               geometric-stiffness path.
    """
    p1 = np.asarray(p1_current, dtype=float)
    p2 = np.asarray(p2_current, dtype=float)
    R1 = R_node1.R
    R2 = R_node2.R

    sec, mat = state.section, state.material
    E_ref = state.E_ref

    E_cur, L_cur = _element_triad(p1, p2, R1, R2, state.R0, state.R_r)
    state.R_r = E_cur

    if is_strict_statics:
        L_flex = max(L_cur - state.rigid_zone_total, 1e-9)
    else:
        L_flex = state.L_clear

    R_inc = E_cur @ E_ref.T
    th1 = E_ref.T @ _log_map(R_inc.T @ (R1 @ state.R1_ref.T))
    th2 = E_ref.T @ _log_map(R_inc.T @ (R2 @ state.R2_ref.T))

    dp = np.zeros(12)
    dp[3:6] = th1
                                                                              
    dp[6] = L_cur - state.L_ref
    dp[9:12] = th2

    th1_tot = _log_map(E_cur.T @ (R1 @ state.R0))
    th2_tot = _log_map(E_cur.T @ (R2 @ state.R0))

    state.dp_raw = np.concatenate([
        E_ref.T @ (p1 - state.p1_ref),
        E_ref.T @ _log_map(R1 @ state.R1_ref.T),
        E_ref.T @ (p2 - state.p2_ref),
        E_ref.T @ _log_map(R2 @ state.R2_ref.T)])

    k_local = get_local_stiffness_matrix(
        E=mat['E'], G=mat['G'], A=sec['A'], J=sec['J'],
        I22=sec['I22'], I33=sec['I33'], As2=sec['As2'], As3=sec['As3'],
        L=L_flex, L_tor=state.L_tor)

    phi_y = ((12 * mat['E'] * sec['I33']) / (mat['G'] * sec['As2'] * L_flex ** 2)
             if sec['As2'] > 0 else 0.0)
    phi_z = ((12 * mat['E'] * sec['I22']) / (mat['G'] * sec['As3'] * L_flex ** 2)
             if sec['As3'] > 0 else 0.0)

    G_unit = get_geometric_stiffness_matrix(
        -1.0, L_flex, phi_y=phi_y, phi_z=phi_z,
        A=sec['A'], I22=sec['I22'], I33=sec['I33'])
    k_geo = state.N_ref * G_unit

    df_l = (k_local + k_geo) @ dp
    _, dT, dMy1, dMy2, dMz1, dMz2 = local_force_to_natural(df_l)

    eps_chord = (L_cur ** 2 - state.L0 ** 2) / (2.0 * state.L0 ** 2)

    dp_bend = np.zeros(12)
    dp_bend[4], dp_bend[5] = th1_tot[1], th1_tot[2]
    dp_bend[10], dp_bend[11] = th2_tot[1], th2_tot[2]
    eps_bow = float(dp_bend @ (G_unit @ dp_bend)) / (2.0 * L_flex)

    dp_tw = np.zeros(12)
    dp_tw[3], dp_tw[9] = th1_tot[0], th2_tot[0]
    eps_wag = float(dp_tw @ (G_unit @ dp_tw)) / (2.0 * L_flex)

    N = mat['E'] * sec['A'] * (eps_chord + eps_bow + eps_wag)

    T = state.T_ref + dT
    My1 = state.My1_ref + dMy1
    My2 = state.My2_ref + dMy2
    Mz1 = state.Mz1_ref + dMz1
    Mz2 = state.Mz2_ref + dMz2

    f_l = natural_to_local_force(N, T, My1, My2, Mz1, Mz2, L_cur)

    state._pending = (p1, p2, R1, R2, E_cur, L_cur,
                      (N, T, My1, My2, Mz1, Mz2))

    E_full = _blockdiag4(E_cur)
    f_global = E_full @ f_l
    K_approx = E_full @ (k_local + k_geo) @ E_full.T

    if fef_local is None:
        N_axial = N
    else:
        fl = np.asarray(fef_local, dtype=float)
        N_axial = N + 0.5 * (fl[6] - fl[0])

    return f_global, K_approx, N_axial
