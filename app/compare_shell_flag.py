"""
compare_shell_flag.py  -  is the displacement change a bug, or a rigid-body (unsupported) mode?

Runs run_linear_static_analysis TWICE on the same .mf in one process:
   A) shell_element.BATCH_SHELL_BUILD = True   (new batched shell stiffness)
   B) shell_element.BATCH_SHELL_BUILD = False  (original per-element path)
then compares the displacement fields.

Put it next to profile_solve.py (the app folder in your case), then:

    python -u compare_shell_flag.py "E:\\OpenCivil\\SimpleModel\\Full_Model_DoNotRun_JustForShow.mf" DEAD

It writes results only to your temp folder.
"""
import contextlib
import io
import json
import os
import sys
import tempfile
import time

import numpy as np

DOF = ["UX", "UY", "UZ", "RX", "RY", "RZ"]

def _skew(x):
    return np.array([[0, -x[2], x[1]], [x[2], 0, -x[0]], [-x[1], x[0], 0]])

def rigid_fit(X, U):
    """Least-squares rigid motion (t, theta) for translations U[:, :3] at points X. Returns (params, fitted (n,6))."""
    n = len(X)
    A = np.zeros((3 * n, 6))
    for i in range(n):
        A[3 * i:3 * i + 3, 0:3] = np.eye(3)
        A[3 * i:3 * i + 3, 3:6] = -_skew(X[i])
    p, *_ = np.linalg.lstsq(A, U[:, :3].reshape(-1), rcond=None)
    fit = np.zeros((n, 6))
    fit[:, :3] = (A @ p).reshape(n, 3)
    fit[:, 3:] = p[3:]
    return p, fit

def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args:
        print(__doc__)
        return 2
    mf = os.path.abspath(args[0])
    case = args[1] if len(args) > 1 else "DEAD"

    here = os.path.dirname(os.path.abspath(__file__))
    for p in (os.path.join(here, "app"), here):
        if p not in sys.path:
            sys.path.insert(0, p)

    print(f"model: {mf}")
    print(f"file last modified: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(os.path.getmtime(mf)))}")
    raw = json.load(open(mf, encoding="utf-8"))
    ids = [str(n["id"]) for n in raw["nodes"]]
    X = np.array([[n["x"], n["y"], n["z"]] for n in raw["nodes"]], float)

    from core.solver.linear_static.main_engine import run_linear_static_analysis

    def set_flag(value):
        found = 0
        for m in list(sys.modules.values()):
            f = getattr(m, "__file__", None) or ""
            if os.path.basename(f) == "shell_element.py" and hasattr(m, "BATCH_SHELL_BUILD"):
                m.BATCH_SHELL_BUILD = value
                found += 1
        return found

    def run(label, flag):
        n_mod = set_flag(flag)
        out = os.path.join(tempfile.gettempdir(), f"oc_cmp_{label}_results.json")
        with contextlib.redirect_stdout(io.StringIO()):
            t = time.perf_counter()
            ok = run_linear_static_analysis(mf, out, case, progress_callback=lambda m, p: None)
            dt = time.perf_counter() - t
        res = json.load(open(out))
        for p in (out, out.replace("_results.json", "_matrices.json")):
            try:
                os.remove(p)
            except OSError:
                pass
        D = res["displacements"]
        U = np.array([D[i] for i in ids], float)
        print(f"run {label}: BATCH_SHELL_BUILD={flag}  (flag found in {n_mod} module(s))  ok={ok}  {dt:.1f}s  max|U|={np.abs(U).max():.6f}")
        return U

    UA = run("A_batched", True)
    UB = run("B_original", False)
    if set_flag(True) == 0:
        print("WARNING: could not find BATCH_SHELL_BUILD in any shell_element module - the two runs may be identical.")

    d = UA - UB
    print("\n=== A (batched) vs B (original) ===")
    print(f"max|U|  A = {np.abs(UA).max():.6f}   B = {np.abs(UB).max():.6f}")
    print(f"max|A-B| = {np.abs(d).max():.3e}   ({np.abs(d).max() / max(np.abs(UB).max(), 1e-300):.3e} of max|B|)")
    for k in range(6):
        i = int(np.argmax(np.abs(UA[:, k])))
        j = int(np.argmax(np.abs(UB[:, k])))
        print(f"  {DOF[k]}: max|A|={np.abs(UA[:, k]).max():.4e} (node {ids[i]})   max|B|={np.abs(UB[:, k]).max():.4e} (node {ids[j]})")

    p, fit = rigid_fit(X, d)
    nb = np.linalg.norm(d[:, :3])
    res_t = np.linalg.norm(d[:, :3] - fit[:, :3]) / max(nb, 1e-300)
    res_r = min(np.linalg.norm(d[:, 3:] - fit[:, 3:]) / max(np.linalg.norm(d[:, 3:]), 1e-300), 1.0e6)
    print("\nDifference A-B fitted by ONE rigid-body motion (translation t + rotation theta):")
    print(f"  t = ({p[0]:.4e}, {p[1]:.4e}, {p[2]:.4e})   theta = ({p[3]:.4e}, {p[4]:.4e}, {p[5]:.4e})")
    print(f"  unexplained part: translations {res_t:.3e}   rotations {res_r:.3e}   (0 = the difference IS a rigid motion)")

    _, fa = rigid_fit(X, UA)
    _, fb = rigid_fit(X, UB)
    EA, EB = UA - fa, UB - fb
    print("\nAfter removing each result's best-fit rigid motion:")
    print(f"  max|A_elastic| = {np.abs(EA).max():.6f}   max|B_elastic| = {np.abs(EB).max():.6f}")
    print(f"  max|A_elastic - B_elastic| = {np.abs(EA - EB).max():.3e}   ({np.abs(EA - EB).max() / max(np.abs(EB).max(), 1e-300):.3e} relative)")

    print("\nVERDICT:")
    if np.abs(d).max() <= 1e-9 * max(np.abs(UB).max(), 1e-300):
        print("  A and B agree to rounding. The new shell build is not the cause of any change.")
    elif res_t < 1e-3 and res_r < 1e-3:
        print("  The difference is a pure RIGID-BODY motion. The stiffness matrix has unrestrained rigid-body modes\n"
              "  (the model is not fully supported), so the solver returns an arbitrary rigid component that changes\n"
              "  with rounding. The deformation itself agrees. This is a MODEL/SOLVER-SAFETY issue, not a shell bug.")
    else:
        print("  The difference is NOT a rigid-body motion. Send me this whole output - I need to find the cause.")
    return 0

if __name__ == "__main__":
    sys.exit(main())
