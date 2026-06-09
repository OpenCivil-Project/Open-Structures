import logging
import threading
from PyQt6.QtCore import QThread, pyqtSignal

from google_auth_oauthlib.flow import InstalledAppFlow
import requests

from .config import GoogleAuthConfig

logger = logging.getLogger(__name__)

_CANCELLED = "cancelled"

class GoogleAuthThread(QThread):
    """
    Runs the Google OAuth2 browser flow in a background thread
    so the UI stays responsive.
    
    Supports cancellation: call cancel() at any time to abort.
    """

    auth_complete = pyqtSignal(dict)                                    
    auth_failed   = pyqtSignal(str)                                    
    auth_progress = pyqtSignal(str)                                           

    def __init__(self):
        super().__init__()
        self._cancelled = threading.Event()

    def cancel(self):
        """
        Signal the thread to abandon the current OAuth wait.
        """
        self._cancelled.set()

    def run(self):
        try:
            if not GoogleAuthConfig.validate():
                self.auth_failed.emit(
                    "Missing Google OAuth configuration. "
                    "Please check your environment variables."
                )
                return

            self.auth_progress.emit("Preparing authentication…")

            flow = InstalledAppFlow.from_client_config(
                GoogleAuthConfig.as_client_config(),
                GoogleAuthConfig.SCOPES,
            )

            self.auth_progress.emit("Opening browser — please sign in…")

            result = [None, None]                             
            done  = threading.Event()

            def _do_oauth():
                try:
                    creds = flow.run_local_server(
                        port=0,
                        prompt='consent',
                        authorization_prompt_message='',
                        success_message='All done! You can close this tab.',
                        open_browser=True,
                        timeout_seconds=120,
                    )
                    result[0] = creds
                except Exception as exc:                                          
                    result[1] = exc
                finally:
                    done.set()

            sub = threading.Thread(target=_do_oauth, daemon=True, name="GoogleOAuth")
            sub.start()

            while not done.wait(timeout=0.5):
                if self._cancelled.is_set():
                    self.auth_failed.emit(_CANCELLED)
                    return

            if self._cancelled.is_set():
                self.auth_failed.emit(_CANCELLED)
                return

            exc = result[1]
            if exc is not None:
                if "Scope has changed" in str(exc):
                    credentials = getattr(flow, 'credentials', None)
                    if not credentials:
                        self.auth_failed.emit(
                            "OAuth scope mismatch. "
                            "Please check your Google Cloud Console settings."
                        )
                        return
                else:
                    self.auth_failed.emit(
                        "Browser was closed before sign-in completed. "
                        "Please try again."
                    )
                    return
            else:
                credentials = result[0]

            if not credentials:
                self.auth_failed.emit("Sign-in did not complete. Please try again.")
                return

            self.auth_progress.emit("Fetching your profile…")

            headers  = {'Authorization': f'Bearer {credentials.token}'}
            response = requests.get(
                GoogleAuthConfig.USER_INFO_URL,
                headers=headers,
                timeout=10,
            )
            response.raise_for_status()
            user_info = response.json()

            if 'email' not in user_info:
                raise ValueError("Google did not return an email address.")

            user_info['credentials'] = credentials
            self.auth_complete.emit(user_info)

        except requests.RequestException as exc:
            if not self._cancelled.is_set():
                logger.error("Network error during auth: %s", exc)
                self.auth_failed.emit(f"Network error: {exc}")
        except ValueError as exc:
            if not self._cancelled.is_set():
                logger.error("Value error during auth: %s", exc)
                self.auth_failed.emit(str(exc))
        except Exception as exc:
            if not self._cancelled.is_set():
                logger.exception("Unexpected auth error")
                self.auth_failed.emit(f"Authentication failed: {exc}")
