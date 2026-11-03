"""
SolverProcessRunner - drop-in replacement for SolverWorker (QThread) that runs
the solver in a separate OS process, so the UI never competes with it for the GIL.

Differences from SolverWorker that main.py must know about:
  * progress arrives in batches:  signal_progress_batch(list[(message, percent)])
  * cancel() kills the solver process
Everything else (start(), signal_finished, batch_failed_steps, batch_case_failures)
behaves the same.
"""
import sys
import os
import json
import tempfile
from PyQt6.QtCore import (QObject, QProcess, QProcessEnvironment, QCoreApplication,
                          QTimer, pyqtSignal)

class SolverProcessRunner(QObject):
    signal_finished = pyqtSignal(bool, str)
    signal_progress_batch = pyqtSignal(list)                                 

    POLL_MS = 100

    def __init__(self, input_path, output_path, case_type="Linear Static",
                 case_name="DEAD", parent=None):
        super().__init__(parent)
        self.input_path = input_path
        self.output_path = output_path
        self.case_type = case_type
        self.case_name = case_name

        self.batch_failed_steps = []
        self.batch_case_failures = []

        self._proc = None
        self._payload_path = None
        self._channel_path = None
        self._read_pos = 0
        self._partial = b""
        self._final = None
        self._emitted = False
        self._timer = None

    def start(self):
        fd, self._payload_path = tempfile.mkstemp(prefix="oc_solver_", suffix=".json")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump({
                "input_path": self.input_path,
                "output_path": self.output_path,
                "case_type": self.case_type,
                "case_name": self.case_name,
            }, f)
        fd, self._channel_path = tempfile.mkstemp(prefix="oc_solver_", suffix=".log")
        os.close(fd)

        proc = QProcess(self)
        self._proc = proc
                                                                                     
        proc.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        env = QProcessEnvironment.systemEnvironment()
        env.insert("PYTHONIOENCODING", "utf-8")
        env.insert("PYTHONUNBUFFERED", "1")
        proc.setProcessEnvironment(env)

        proc.readyReadStandardOutput.connect(self._forward_console)
        proc.finished.connect(self._on_finished)
        proc.errorOccurred.connect(self._on_error)

        if getattr(sys, "frozen", False):
                                                                                    
            proc.start(sys.executable, ["--run-solver", self._payload_path, self._channel_path])
        else:
            script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "solver_process.py")
            proc.start(sys.executable, ["-u", script, self._payload_path, self._channel_path])

        self._timer = QTimer(self)
        self._timer.setInterval(self.POLL_MS)
        self._timer.timeout.connect(self._poll)
        self._timer.start()

        app = QCoreApplication.instance()
        if app is not None:
            app.aboutToQuit.connect(self.cancel)                                           

    def isRunning(self):
        return self._proc is not None and self._proc.state() != QProcess.ProcessState.NotRunning

    def cancel(self):
        self._emitted = True
        if self._timer is not None:
            self._timer.stop()
        if self._proc is not None and self._proc.state() != QProcess.ProcessState.NotRunning:
            pid = self._proc.processId()
            if sys.platform == "win32" and pid:
                import subprocess
                subprocess.run(
                    ["taskkill", "/F", "/T", "/PID", str(pid)],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            self._proc.kill()
            self._proc.waitForFinished(300)
        self._cleanup()

    def _poll(self):
        """Read any new complete lines from the channel file; one UI update per poll."""
        try:
            with open(self._channel_path, "rb") as f:
                f.seek(self._read_pos)
                data = f.read()
        except OSError:
            return
        if not data:
            return
        self._read_pos += len(data)
        self._partial += data
        batch = []
        while b"\n" in self._partial:
            line, self._partial = self._partial.split(b"\n", 1)
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line.decode("utf-8", errors="replace"))
            except ValueError:
                continue
            if msg.get("t") == "p":
                batch.extend((m, p) for m, p in msg.get("items", []))
            elif msg.get("t") == "f":
                self._final = msg
        if batch:
            self.signal_progress_batch.emit(batch)

    def _forward_console(self):
                                                                           
        data = bytes(self._proc.readAllStandardOutput()).decode("utf-8", errors="replace")
        if data:
            try:
                sys.__stdout__.write(data)
                sys.__stdout__.flush()
            except Exception:
                pass                                                                    

    def _cleanup(self):
        if self._timer is not None:
            self._timer.stop()
        for p in (self._payload_path, self._channel_path):
            if p:
                try:
                    os.remove(p)
                except OSError:
                    pass

    def _on_error(self, err):
        if err == QProcess.ProcessError.FailedToStart and not self._emitted:
            self._emitted = True
            self._cleanup()
            self.signal_finished.emit(False, "Could not start the solver process.")

    def _on_finished(self, exit_code, exit_status):
        if self._emitted:
            return
        self._poll()                                                                  
        self._forward_console()
        self._emitted = True
        self._cleanup()
        if self._final is not None:
            self.batch_failed_steps = self._final.get("failed_steps", []) or []
            self.batch_case_failures = self._final.get("case_failures", []) or []
            self.signal_finished.emit(bool(self._final.get("ok")), str(self._final.get("msg", "")))
        else:
            self.signal_finished.emit(
                False, f"Solver process ended unexpectedly (exit code {exit_code}).")
