"""
ui_stall_watchdog.py  -  tells you EXACTLY what freezes the UI.

How it works
------------
A QTimer ticks on the GUI thread every 50 ms. Each tick (re)arms faulthandler's
dump_traceback_later(). If the GUI thread is blocked and the tick does not fire for
THRESHOLD seconds, faulthandler (a C-level thread - it does not need the GIL, so it
works even while the GUI thread is stuck inside json / scipy / numpy C code) writes
the Python stack of EVERY thread to the log, and repeats every THRESHOLD seconds
while the freeze lasts. When the GUI thread wakes up again, a summary line with the
total freeze time is added.

Reading the log: for each freeze, look at the stack of the thread marked
"most recent call first" that is the main thread (usually the last "Thread 0x...
(most recent call first)" block with MainWindow / Qt slot frames). The top line is
where the GUI thread was stuck.

Cost: one timer tick per 50 ms. It changes no behaviour.

Usage (main.py, right after  app = QApplication(sys.argv) ):
    from app.ui_stall_watchdog import install as _install_watchdog
    _install_watchdog()
Log file: ~/.OpenCivil_ui_stalls.log   (override with install(log_path=...))
Remove those two lines to turn it off.
"""
import faulthandler
import os
import time

from PyQt6.QtCore import QObject, QTimer

THRESHOLD_S = 0.5
TICK_MS = 50

_instance = None

class _Watchdog(QObject):
    def __init__(self, log_path, threshold):
        super().__init__()
        self._thr = threshold
        self._f = open(log_path, "a", buffering=1, encoding="utf-8")
        self._f.write("\n===== session start %s =====\n" % time.strftime("%Y-%m-%d %H:%M:%S"))
        self._f.flush()
        self._last = time.perf_counter()
        self._timer = QTimer(self)
        self._timer.setInterval(TICK_MS)
        self._timer.timeout.connect(self._beat)
        self._timer.start()
        self._arm()

    def _arm(self):
        faulthandler.cancel_dump_traceback_later()
        faulthandler.dump_traceback_later(self._thr, repeat=True, file=self._f)

    def _beat(self):
        now = time.perf_counter()
        gap = now - self._last
        if gap > self._thr:
            self._f.write("[%s] ^^^ GUI thread was blocked for %.2f s ^^^\n"
                          % (time.strftime("%H:%M:%S"), gap))
            self._f.flush()
        self._last = now
        self._arm()

def install(log_path=None, threshold=THRESHOLD_S):
    """Call once, after the QApplication exists. Returns the watchdog (kept alive internally)."""
    global _instance
    if _instance is not None:
        return _instance
    if log_path is None:
        log_path = os.path.join(os.path.expanduser("~"), ".OpenCivil_ui_stalls.log")
    _instance = _Watchdog(log_path, threshold)
    return _instance
