"""
compare_shell_k.py  -  does the batched shell kernel give the SAME element stiffness as the original?

Builds your model's shells twice (batched kernel ON, then OFF = original per-element code) and compares
k_global of EVERY shell. No solve - takes a few seconds.

    python -u compare_shell_k.py "E:\\OpenCivil\\SimpleModel\\Full_Model_DoNotRun_JustForShow.mf" DEAD

Reading it: worst relative difference ~1e-15  -> the kernel is right (then the model is ill-conditioned).
            anything above ~1e-9             -> a real kernel bug; the worst shells are listed with their properties.
"""
import contextlib, io, os, sys
import numpy as np

def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args:
        print(__doc__); return 2
    mf = os.path.abspath(args[0]); case = args[1] if len(args) > 1 else "DEAD"
    here = os.path.dirname(os.path.abspath(__file__))
    for p in (os.path.join(here, "app"), here):
        if p not in sys.path:
            sys.path.insert(0, p)
    import core.solver.linear_static.main_engine as ME

    def set_flag(v):
        n = 0
        for m in list(sys.modules.values()):
            f = getattr(m, "__file__", None) or ""
            if os.path.basename(f) == "shell_element.py" and hasattr(m, "BATCH_SHELL_BUILD"):
                m.BATCH_SHELL_BUILD = v; n += 1
        return n

    def build(flag):
        n = set_flag(flag)
        with contextlib.redirect_stdout(io.StringIO()):
            dm = ME.DataManager(mf)
            dm.process_all(case_name=case)
        print(f"built shells with BATCH_SHELL_BUILD={flag} (flag found in {n} module(s)): {len(getattr(dm, 'shells', []))} shells")
        return dm

    dm_a = build(True)
    dm_b = build(False)
    A, B = dm_a.shells, dm_b.shells
    assert len(A) == len(B) and [s.id for s in A] == [s.id for s in B], "different shell lists"

    rel = np.array([np.abs(a.k_global - b.k_global).max() / max(np.abs(b.k_global).max(), 1e-300) for a, b in zip(A, B)])
    rel_loc = np.array([np.abs(a.k_local - b.k_local).max() / max(np.abs(b.k_local).max(), 1e-300) for a, b in zip(A, B)])
    print(f"\nworst relative difference  k_global: {rel.max():.3e}    k_local: {rel_loc.max():.3e}")
    for thr in (1e-12, 1e-9, 1e-6, 1e-3):
        print(f"  shells with difference > {thr:.0e}: {int((rel > thr).sum())}")

    order = np.argsort(-rel)[:10]
    print("\nworst 10 shells:")
    print(f"{'id':>8} {'rel diff':>10}  {'section':<14} {'type':<14} {'tm':>6} {'tb':>6} {'offset':>7} {'angle':>6} {'dkq':>4} {'aspect':>7}  mods")
    for i in order:
        a = A[i]
        edges = [np.linalg.norm(a.coords[(k + 1) % 4] - a.coords[k]) for k in range(4)]
        print(f"{str(a.id):>8} {rel[i]:>10.2e}  {str(a.sec['name']):<14} {str(a.sec['shell_type']):<14} {a.tm:>6.3f} {a.tb:>6.3f} "
              f"{a.offset:>7.3f} {a.sec.get('angle', 0.0):>6.1f} {str(a._use_dkq()):>4} {max(edges) / min(edges):>7.2f}  {sorted((a.mods or {}).keys())}")

    n_diff_tm_tb = sum(1 for a in A if abs(a.tm - a.tb) > 1e-12)
    n_mods = sum(1 for a in A if a.mods)
    print(f"\nmodel has: {n_diff_tm_tb} shells with membrane thickness != bending thickness, {n_mods} shells with stiffness modifiers, "
          f"{sum(1 for a in A if a.offset != 0)} with insertion offset")
    print("\nVERDICT:")
    if rel.max() < 1e-9:
        print("  The batched kernel reproduces every shell stiffness to rounding. It is NOT a kernel bug; the\n"
              "  different displacements come from an ill-conditioned / unsupported model. Next: diagnose_singularity.py")
    else:
        print("  The batched kernel DIFFERS from the original on the shells listed above. That is a bug in my kernel.\n"
              "  Send me this whole output. (Meanwhile set BATCH_SHELL_BUILD = False in shell_element.py.)")
    return 0

if __name__ == "__main__":
    sys.exit(main())
