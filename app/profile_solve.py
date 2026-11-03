"""
profile_solve.py  -  where do the 59 seconds go?

Runs the SAME function the app's solver process runs (run_linear_static_analysis) on a
saved .mf file, in this process, with no UI. Prints
  1) a stage timeline (time of each progress message and the gap since the previous one),
  2) with profiling on: the functions that use the most time.

Put this file in the project root (the folder that contains core/ and app/), then:

    python -u profile_solve.py "C:\\path\\to\\model.mf" DEAD --no-profile     <- true wall-clock stages
    python -u profile_solve.py "C:\\path\\to\\model.mf" DEAD                  <- same, with cProfile (runs slower)

The .mf is the file the app already saved for the run. Results are written to your temp
folder and deleted afterwards - your real *_results.json files are not touched.
"""
import cProfile
import io
import os
import pstats
import sys
import tempfile
import time

def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    flags = {a for a in sys.argv[1:] if a.startswith("--")}
    if not args:
        print(__doc__)
        return 2
    mf = os.path.abspath(args[0])
    case = args[1] if len(args) > 1 else "DEAD"
    use_profile = "--no-profile" not in flags

    here = os.path.dirname(os.path.abspath(__file__))
    for p in (os.path.join(here, "app"), here):
        if p not in sys.path:
            sys.path.insert(0, p)

    out = os.path.join(tempfile.gettempdir(), "oc_profile_results.json")

    t_start = time.perf_counter()
    last = [t_start]

    def cb(msg, pct):
        now = time.perf_counter()
        text = str(msg).strip()
        if text:
            print(f"  [{now - t_start:7.2f}s  +{now - last[0]:6.2f}s  {int(pct):3d}%]  {text}")
        last[0] = now

    t_imp = time.perf_counter()
    from core.solver.linear_static.main_engine import run_linear_static_analysis
    print(f"\nimports: {time.perf_counter() - t_imp:.2f}s")
    print(f"model  : {mf}   case: {case}   profile: {use_profile}\n")
    print("STAGE TIMELINE  [elapsed  +since-previous-message  percent]  message")

    t_start = time.perf_counter()
    last[0] = t_start
    pr = cProfile.Profile() if use_profile else None
    if pr:
        pr.enable()
    try:
        ok = run_linear_static_analysis(mf, out, case, progress_callback=cb)
    finally:
        if pr:
            pr.disable()
    total = time.perf_counter() - t_start
    print(f"\nreturned: {ok}    total: {total:.2f}s")

    if pr:
        for title, key, n in (("TOP BY TOTAL TIME (own time, excluding callees)", "tottime", 25),
                              ("TOP BY CUMULATIVE TIME (including callees)", "cumulative", 35)):
            s = io.StringIO()
            pstats.Stats(pr, stream=s).strip_dirs().sort_stats(key).print_stats(n)
            print("\n" + title)
            print(s.getvalue())

    for p in (out, out.replace("_results.json", "_matrices.json")):
        try:
            os.remove(p)
        except OSError:
            pass
    return 0

if __name__ == "__main__":
    sys.exit(main())
