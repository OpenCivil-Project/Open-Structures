import json
import logging
import os
from typing import Any, Dict, Optional

from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request

from .config import GoogleAuthConfig
from .dialog import LoginDialog

from PyQt6.QtWidgets import QDialog

logger = logging.getLogger(__name__)

class GoogleAuthManager:
    """
    High-level authentication manager for OpenCivil.

    Usage (in main.py):
        manager = GoogleAuthManager()
        if not manager.login(parent=window):
            sys.exit()          # user cancelled
    """

    def __init__(self):
        self.user_info:   Optional[Dict[str, Any]] = None
        self.credentials: Optional[Credentials]    = None

        os.makedirs(GoogleAuthConfig.CREDENTIALS_DIR, exist_ok=True)

    def login(self, parent=None) -> bool:
        """
        Try to log in.
        1. If saved credentials exist and 'remember_me' was set, auto-login.
        2. Otherwise show the login dialog.
        Returns True on success, False if the user cancelled.
        """
        if self._load_saved_credentials():
            logger.info("Auto-login: %s", self.get_user_email())
            return True

        dialog = LoginDialog(parent)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.user_info   = dialog.user_info
            self.credentials = dialog.user_info.get('credentials')

            if dialog.remember_me:
                self._save_credentials()

            logger.info("Logged in: %s", self.get_user_email())
            return True

        return False

    def restore_session(self) -> bool:
        """
        Silent credential restore for secondary windows.
        No UI shown. Returns True if a valid session was found on disk.
        """
        return self._load_saved_credentials()

    def logout(self):
        """Clear session and remove saved credentials."""
        self.user_info   = None
        self.credentials = None
        self._remove_credentials_file()
        logger.info("User logged out.")

    def is_authenticated(self) -> bool:
        if self.user_info is None:
            return False
        if self.user_info.get('provider') == 'guest':
            return True
        return (
            self.credentials is not None and
            self.credentials.valid
        )

    def get_user_name(self)  -> Optional[str]:
        return self.user_info.get('name')  if self.user_info else None

    def get_user_email(self) -> Optional[str]:
        return self.user_info.get('email') if self.user_info else None

    def get_user_picture(self) -> Optional[str]:
        return self.user_info.get('picture') if self.user_info else None

    def _load_saved_credentials(self) -> bool:
        path = GoogleAuthConfig.CREDENTIALS_FILE
        if not os.path.exists(path):
            return False

        try:
            with open(path) as f:
                data = json.load(f)

            if not data.get('remember_me'):
                return False

            self.user_info = data['user_info']

            if self.user_info.get('provider') == 'guest':
                self.credentials = None
                return True

            if 'credentials' in data:
                cred_data   = data['credentials']
                credentials = Credentials(
                    token         = cred_data.get('token'),
                    refresh_token = cred_data.get('refresh_token'),
                    token_uri     = cred_data.get('token_uri'),
                    client_id     = cred_data.get('client_id'),
                    client_secret = cred_data.get('client_secret'),
                    scopes        = cred_data.get('scopes'),
                )

                if credentials.expired and credentials.refresh_token:
                    credentials.refresh(Request())
                    logger.info("Refreshed expired credentials.")

                if not credentials.valid:
                    self._remove_credentials_file()
                    return False
                self.credentials = credentials
            else:
                self.credentials = None 

            return True

        except Exception as exc:
            logger.error("Could not load saved credentials: %s", exc)
            self._remove_credentials_file()
            return False

    def _save_credentials(self):
        if not self.user_info:
            return
        try:
            payload = {
                'remember_me': True,
                'user_info': {
                    'name':    self.user_info.get('name'),
                    'email':   self.user_info.get('email'),
                    'picture': self.user_info.get('picture'),
                    'provider': self.user_info.get('provider', 'google')
                }
            }
            if self.credentials:
                payload['credentials'] = {
                    'token':         self.credentials.token,
                    'refresh_token': self.credentials.refresh_token,
                    'token_uri':     self.credentials.token_uri,
                    'client_id':     self.credentials.client_id,
                    'client_secret': self.credentials.client_secret,
                    'scopes':        list(self.credentials.scopes or []),
                }
            path = GoogleAuthConfig.CREDENTIALS_FILE
            with open(path, 'w') as f:
                json.dump(payload, f, indent=2)
            if hasattr(os, 'chmod'):
                os.chmod(path, 0o600)
        except Exception as exc:
            logger.error("Could not save credentials: %s", exc)

    def _remove_credentials_file(self):
        path = GoogleAuthConfig.CREDENTIALS_FILE
        try:
            if os.path.exists(path):
                os.remove(path)
        except Exception as exc:
            logger.error("Could not remove credentials file: %s", exc)
