"""Nonblocking cold result loads, with Qt owning running job lifetimes."""

from PyQt6.QtCore import QObject, QRunnable, QThreadPool, pyqtSignal
from core.result_file_cache import load_json_cached

class _ResultLoadSignals(QObject):
    finished = pyqtSignal(object, str, object, object)

class ResultFileLoader(QRunnable):
    """Connect ``signals.finished(job, path, data, error)`` before starting."""

    def __init__(self, path):
        super().__init__()
        self.path = path
        self.signals = _ResultLoadSignals()

    def start(self):
        QThreadPool.globalInstance().start(self)

    def run(self):
        try:
            data = load_json_cached(self.path)
        except Exception as error:
            self.signals.finished.emit(self, self.path, None, error)
        else:
            self.signals.finished.emit(self, self.path, data, None)
