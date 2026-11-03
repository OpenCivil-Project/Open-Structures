"""Desktop identity and offline profile management.

An offline remembered profile permits local modelling only. Firebase remains
the authority for account identity; local files never authorize account access.
"""

from datetime import datetime, timedelta, timezone
import json
import logging
from pathlib import Path
from typing import Any, Dict, Optional

from PyQt6.QtWidgets import QDialog

from .config import FirebaseAuthConfig
from .dialog import LoginDialog
from .firebase_client import FirebaseClient, FirebaseAuthError
from .session_store import SessionStore, SessionStoreError

logger = logging.getLogger(__name__)
_INVALID_SESSION_CODES = {
    "INVALID_ID_TOKEN", "INVALID_REFRESH_TOKEN", "USER_DISABLED",
    "USER_NOT_FOUND", "EMAIL_NOT_VERIFIED", "INVALID_GRANT",
    "PROJECT_NUMBER_MISMATCH", "MISSING_REFRESH_TOKEN",
}

def _expires_at(session: dict) -> datetime:
    value = session.get("expires_at")
    if not isinstance(value, str):
        raise ValueError("Missing session expiry.")
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("Session expiry must include its timezone.")
    return result.astimezone(timezone.utc)

def _safe_session(value: Any) -> Dict[str, str]:
    if not isinstance(value, dict):
        raise ValueError("Missing account session.")
    result = {}
    for key in ("access_token", "refresh_token", "expires_at"):
        item = value.get(key)
        if not isinstance(item, str) or not item or len(item) > 16384:
            raise ValueError("Invalid account session.")
        result[key] = item
    _expires_at(result)
    return result

def _safe_user(value: Any) -> Dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("Missing account profile.")
    provider = value.get("provider")
    if provider == "guest":
        return {"name": "Guest", "email": "", "picture": "", "provider": "guest"}
    if provider not in {"email", "google", "password", "google.com"}:
        raise ValueError("Invalid account provider.")
    user = {"provider": "google" if provider in {"google", "google.com"} else "email"}
    for key, maximum in (("uid", 256), ("name", 500), ("email", 320), ("picture", 4096)):
        item = value.get(key, "")
        if not isinstance(item, str) or len(item) > maximum:
            raise ValueError("Invalid account profile.")
        user[key] = item
    if not user["uid"] or not user["email"]:
        raise ValueError("Incomplete account profile.")
    user["name"] = user["name"].strip() or user["email"].split("@", 1)[0]
    user["email_verified"] = value.get("email_verified") is True
    return user

class GoogleAuthManager:
    """Compatibility name retained for existing desktop entry points."""

    def __init__(self):
        self.user_info: Optional[Dict[str, Any]] = None
        self.session: Optional[Dict[str, str]] = None
        self.credentials = None                                                   
        self.offline_session = False
        self._firebase_checked = False
        path = getattr(
            FirebaseAuthConfig, "SESSION_FILE",
            str(Path(FirebaseAuthConfig.CREDENTIALS_DIR) / "session.dat"),
        )
        self._store = SessionStore(path)

    def login(self, parent=None) -> bool:
        if self._load_saved_credentials():
            return True
        dialog = LoginDialog(parent)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return False
        try:
            user = _safe_user(dialog.user_info)
            if user["provider"] == "guest":
                self._adopt(user, None, checked=False)
            else:
                session = _safe_session(dialog.user_info.get("session"))
                if not user["email_verified"] or _expires_at(session) <= datetime.now(timezone.utc):
                    raise ValueError("An unverified or expired session cannot sign in.")
                                                                          
                self._adopt(user, session, checked=True)
        except (ValueError, TypeError):
            self._clear_memory()
            logger.warning("The sign-in result did not contain a valid account session.")
            return False
        if dialog.remember_me:
            self._save_credentials()
        else:
            self._remove_credentials_file()
        return True

    def restore_session(self) -> bool:
        """Restore guest mode or a profile usable for local offline modelling."""
        return self._load_saved_credentials()

    def logout(self):
        """Sign out this desktop by clearing memory and its protected cache.

        Global Firebase token revocation requires a privileged server/Admin SDK;
        this method deliberately makes no claim of remote revocation.
        """
        self._clear_memory()
        self._remove_credentials_file()

    def is_authenticated(self) -> bool:
        """Report verified account access, separately from local guest access.

        Guest and offline profiles can launch the application through login()
        or restore_session(), but cannot authorize account-specific features.
        """
        if self.user_info is None:
            return False
        if self.user_info.get("provider") == "guest":
            return False
        if self.offline_session or not self._firebase_checked or not self.session:
            return False
        try:
            return (
                self.user_info.get("email_verified") is True
                and _expires_at(self.session) > datetime.now(timezone.utc)
            )
        except ValueError:
            return False

    def get_user_name(self):
        return self.user_info.get("name") if self.user_info else None

    def get_user_email(self):
        return self.user_info.get("email") if self.user_info else None

    def get_user_picture(self):
        return self.user_info.get("picture") if self.user_info else None

    def _clear_memory(self):
        self.user_info = None
        self.session = None
        self.credentials = None
        self.offline_session = False
        self._firebase_checked = False

    def _adopt(self, user, session, *, checked=False, offline=False):
        self.user_info = _safe_user(user)
        self.session = _safe_session(session) if session else None
        self.credentials = None
        self.offline_session = offline
        self._firebase_checked = checked

    def _load_saved_credentials(self) -> bool:
        self._clear_memory()
        legacy_guest = self._migrate_legacy_guest()
        try:
            payload = self._store.load()
        except SessionStoreError:
            logger.warning("The protected remembered session could not be restored.")
            self._remove_credentials_file()
            return False
        if payload is None:
            if legacy_guest:
                self._adopt(legacy_guest, None)
                self._save_credentials()
                return True
            return False
        try:
            if payload.get("version") != 1 or payload.get("remember_me") is not True:
                raise ValueError("Unsupported session metadata.")
            user = _safe_user(payload.get("user_info"))
            if user["provider"] == "guest":
                if payload.get("session"):
                    raise ValueError("Guest metadata cannot authorize account access.")
                self._adopt(user, None)
                return True
            session = _safe_session(payload.get("session"))
            if not user["email_verified"]:
                raise ValueError("An unverified profile cannot restore a session.")
        except (ValueError, TypeError):
            self._remove_credentials_file()
            return False

        client = FirebaseClient()
        if not client.configured:
            self._adopt(user, session, offline=True)
            return True
                                                                             
        client.TIMEOUT = (1.5, 1.5)
        try:
            if _expires_at(session) <= datetime.now(timezone.utc) + timedelta(seconds=30):
                refreshed = client.refresh(session["refresh_token"])
                verified_user = _safe_user(refreshed.get("user"))
                session = _safe_session(refreshed.get("session"))
                if verified_user.get("uid") != user.get("uid"):
                    raise ValueError("The refreshed session changed its account.")
                self._adopt(verified_user, session, offline=True)
                                                                                  
                self._save_credentials()
            else:
                try:
                    verified_user = _safe_user(client.lookup(session["access_token"]))
                except FirebaseAuthError as exc:
                    if getattr(exc, "code", None) != "TOKEN_EXPIRED":
                        raise
                    refreshed = client.refresh(session["refresh_token"])
                    verified_user = _safe_user(refreshed.get("user"))
                    session = _safe_session(refreshed.get("session"))
                    if verified_user.get("uid") != user.get("uid"):
                        raise ValueError("The refreshed session changed its account.")
                    self._adopt(verified_user, session, offline=True)
                    self._save_credentials()
            if (
                not verified_user.get("email_verified")
                or verified_user.get("uid") != user.get("uid")
                or _expires_at(session) <= datetime.now(timezone.utc)
            ):
                raise ValueError("The restored session did not match its account.")
            self._adopt(verified_user, session, checked=True)
            self._save_credentials()
            return True
        except FirebaseAuthError as exc:
            if (
                getattr(exc, "code", None) in _INVALID_SESSION_CODES
                or getattr(exc, "status_code", None) in {401, 403}
            ):
                self._clear_memory()
                self._remove_credentials_file()
                return False
                                                                               
            self._adopt(user, session, offline=True)
            return True
        except (ValueError, TypeError, KeyError):
            self._clear_memory()
            self._remove_credentials_file()
            return False

    def _save_credentials(self):
        if not self.user_info:
            return
        payload = {
            "version": 1,
            "remember_me": True,
            "user_info": _safe_user(self.user_info),
        }
        if self.session:
            payload["session"] = _safe_session(self.session)
        try:
            self._store.save(payload)
        except SessionStoreError:
                                                                             
            self._remove_credentials_file()
            logger.warning("Remember me is unavailable: a secure session store could not be used.")

    def _migrate_legacy_guest(self):
        """Only guest metadata survives migration from the old plaintext cache."""
        path = Path(FirebaseAuthConfig.CREDENTIALS_FILE)
        if not path.exists():
            return None
        guest = None
        try:
            with path.open("rb") as stream:
                raw = stream.read(128 * 1024 + 1)
            if len(raw) <= 128 * 1024:
                payload = json.loads(raw)
                user = payload.get("user_info") if isinstance(payload, dict) else None
                if (
                    isinstance(payload, dict)
                    and payload.get("remember_me") is True
                    and isinstance(user, dict)
                    and user.get("provider") == "guest"
                ):
                    guest = _safe_user(user)
        except (OSError, ValueError, TypeError):
            pass
        finally:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                logger.warning("The obsolete plaintext session file could not be removed.")
        return guest

    def _remove_credentials_file(self):
        try:
            self._store.remove()
        except SessionStoreError:
            logger.warning("The protected session file could not be removed.")
        try:
            Path(FirebaseAuthConfig.CREDENTIALS_FILE).unlink(missing_ok=True)
        except OSError:
            logger.warning("The obsolete plaintext session file could not be removed.")
