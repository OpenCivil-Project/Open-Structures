"""Google sign-in through Firebase Hosting using the system browser."""
import threading
import webbrowser

from PyQt6.QtCore import QThread, pyqtSignal

from .browser_bridge import BrowserSignInBridge, BrowserSignInError
from .config import FirebaseAuthConfig
from .firebase_client import FirebaseClient, FirebaseAuthError

_CANCELLED = "cancelled"

_ACTIVE_THREADS = set()

def retain_thread(thread):
    _ACTIVE_THREADS.add(thread)
    thread.finished.connect(lambda: _ACTIVE_THREADS.discard(thread))

class AuthOperationThread(QThread):
    result = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, operation):
        super().__init__()
        self._operation = operation
        self._cancelled = threading.Event()
        retain_thread(self)

    def cancel(self):
        self._cancelled.set()

    def run(self):
        try:
            result = self._operation()
            if not self._cancelled.is_set():
                self.result.emit(result)
        except Exception:
            if not self._cancelled.is_set():
                self.failed.emit("Account request could not finish. Please try again.")

class GoogleAuthThread(QThread):
    auth_complete = pyqtSignal(dict)
    auth_failed = pyqtSignal(str)
    auth_progress = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._cancelled = threading.Event()
        retain_thread(self)

    def cancel(self):
        self._cancelled.set()

    def run(self):
        try:
            client = FirebaseClient()
            if not client.configured or not FirebaseAuthConfig.google_sign_in_available():
                self.auth_failed.emit("Account sign-in is not configured yet. You can continue as Guest.")
                return
            with BrowserSignInBridge() as bridge:
                self.auth_progress.emit("Opening your browser for Google sign-in…")
                if not webbrowser.open(bridge.browser_url(FirebaseAuthConfig.GOOGLE_SIGN_IN_URL), new=1):
                    raise BrowserSignInError("Could not open your browser. Please try again.")
                tokens = bridge.wait(self._cancelled)
            self.auth_progress.emit("Checking your account…")
            result = client.session_from_tokens(tokens["id_token"], tokens["refresh_token"],
                                                tokens["expires_in"])
            if result["user"].get("provider") != "google":
                raise BrowserSignInError("Please use Google to sign in on the browser page.")
            if self._cancelled.is_set():
                self.auth_failed.emit(_CANCELLED)
                return
            self.auth_complete.emit({**result["user"], "session": result["session"]})
        except (BrowserSignInError, FirebaseAuthError) as exc:
            self.auth_failed.emit(_CANCELLED if self._cancelled.is_set() else str(exc))
        except Exception:
            self.auth_failed.emit(_CANCELLED if self._cancelled.is_set() else
                                  "Google sign-in could not finish. Please try again.")
