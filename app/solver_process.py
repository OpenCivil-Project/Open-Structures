"""
Solver subprocess entry point.

Runs the *unchanged* SolverWorker.run() logic in its own Python process, so the
solver has its own interpreter lock and can never starve the UI thread.

It does NOT depend on stdin/stdout (a --noconsole PyInstaller exe may have none).
Communication goes through two small temp files given on the command line:

    <payload_path>  JSON written by the parent: input_path, output_path,
                    case_type, case_name
    <channel_path>  JSON lines appended by this process:
        {"t": "p", "items": [[message, percent], ...]}     batched progress
        {"t": "f", "ok": bool, "msg": str,
         "failed_steps": [...], "case_failures": [...]}    final result (last line)

Anything the solver print()s goes to stderr (or nowhere, if there is no console).
"""
import sys
import os
import json
import threading
import traceback

FLUSH_INTERVAL_S = 0.1                                                   

def _json_default(o):
    try:
        return o.item()                        
    except Exception:
        return str(o)

class _Signal:
    """Stand-in for a pyqtSignal: only .emit() is used by SolverWorker.run()."""
    def __init__(self, fn):
        self.emit = fn

class _WorkerShim:
    """Provides exactly the attributes SolverWorker.run() touches on `self`."""
    def __init__(self, payload, on_progress, on_finished):
        self.input_path = payload["input_path"]
        self.output_path = payload["output_path"]
        self.case_type = payload["case_type"]
        self.case_name = payload["case_name"]
        self.signal_progress = _Signal(on_progress)
        self.signal_finished = _Signal(on_finished)
        self.batch_failed_steps = []
        self.batch_case_failures = []

def _lower_priority():
    """
    Run the solver at BELOW-NORMAL CPU priority so the OS always gives the UI process the
    CPU first. The solve itself is unchanged (same code, same results); it just yields to the
    desktop when both want the CPU. Best effort - any failure is ignored.
    """
    try:
        if sys.platform == "win32":
            import ctypes
            BELOW_NORMAL_PRIORITY_CLASS = 0x00004000
            k32 = ctypes.windll.kernel32
            k32.SetPriorityClass(k32.GetCurrentProcess(), BELOW_NORMAL_PRIORITY_CLASS)
        else:
            os.nice(5)
    except Exception:
        pass

def main(argv=None):
    _lower_priority()
    argv = list(sys.argv if argv is None else argv)
    payload_path, channel_path = argv[-2], argv[-1]

    devnull = None
    if sys.stdout is None or sys.stderr is None:
        devnull = open(os.devnull, "w")
    if sys.stderr is None:
        sys.stderr = devnull
    try:
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    sys.stdout = sys.stderr

    with open(payload_path, "r", encoding="utf-8") as f:
        payload = json.load(f)
                                                                                     
    if not getattr(sys, "frozen", False):
        root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        if root_dir not in sys.path:
            sys.path.append(root_dir)

    chan = open(channel_path, "a", encoding="utf-8", buffering=1)
    lock = threading.Lock()
    pending = []

    def write_line(obj):
        chan.write(json.dumps(obj, default=_json_default) + "\n")
        chan.flush()

    def flush():
        with lock:
            if not pending:
                return
            batch = pending[:]
            del pending[:]
            write_line({"t": "p", "items": batch})

    stop = threading.Event()

    def flusher():
        while not stop.wait(FLUSH_INTERVAL_S):
            try:
                flush()
            except Exception:
                pass

    threading.Thread(target=flusher, daemon=True).start()

    def on_progress(msg, pct):
        try:
            pct = int(pct)
        except Exception:
            pct = 0
        with lock:
            pending.append([str(msg), pct])

    result = {"ok": False, "msg": "Solver process ended without reporting a result."}

    def on_finished(ok, msg):
        result["ok"] = bool(ok)
        result["msg"] = str(msg)

    shim = _WorkerShim(payload, on_progress, on_finished)

    try:
        from app.solver_worker import SolverWorker
        SolverWorker.run(shim)                                         
    except BaseException as e:                                                        
        result["ok"] = False
        result["msg"] = "Solver Crashed:\n" + "".join(
            traceback.format_exception(None, e, e.__traceback__))

    stop.set()
    flush()
    with lock:
        write_line({
            "t": "f",
            "ok": result["ok"],
            "msg": result["msg"],
            "failed_steps": shim.batch_failed_steps,
            "case_failures": shim.batch_case_failures,
        })
    chan.close()
    return 0

if __name__ == "__main__":
    sys.exit(main())
