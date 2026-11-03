"""Public Firebase settings; desktop builds never load database/email secrets."""

import json
import os
import re
import sys
from pathlib import Path
from urllib.parse import urlsplit

def _public_settings():
    """Read the optional public resource, including in a frozen distribution."""
    candidates = []
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        root = Path(sys._MEIPASS)
        candidates.extend((root / "resources" / "auth_config.json",
                           root / "app" / "resources" / "auth_config.json"))
    candidates.append(Path(__file__).resolve().parents[1] / "resources" / "auth_config.json")
    for path in candidates:
        try:
            if not path.is_file() or path.stat().st_size > 16384:
                continue
            settings = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(settings, dict):
                return {key: value.strip() for key, value in settings.items()
                        if key in {"api_key", "project_id", "auth_domain", "google_sign_in_url"}
                        and isinstance(value, str)}
        except (OSError, UnicodeError, ValueError):
                                                                                             
            continue
    return {}

_settings = _public_settings()

class FirebaseAuthConfig:
    """Only public identifiers belong in these settings or the packaged JSON."""

    API_KEY = os.getenv("OPENCIVIL_FIREBASE_API_KEY", _settings.get("api_key", "")).strip()
    PROJECT_ID = os.getenv("OPENCIVIL_FIREBASE_PROJECT_ID", _settings.get("project_id", "")).strip()
    AUTH_DOMAIN = os.getenv(
        "OPENCIVIL_FIREBASE_AUTH_DOMAIN",
        _settings.get("auth_domain", f"{PROJECT_ID}.firebaseapp.com" if PROJECT_ID else ""),
    ).strip().lower()
    GOOGLE_SIGN_IN_URL = os.getenv(
        "OPENCIVIL_FIREBASE_GOOGLE_SIGN_IN_URL", _settings.get("google_sign_in_url", "")
    ).strip()

    CREDENTIALS_DIR = os.path.join(os.path.expanduser("~"), ".opencivil")
                                                                                      
    CREDENTIALS_FILE = os.path.join(CREDENTIALS_DIR, "user_credentials.json")
    SESSION_FILE = os.path.join(CREDENTIALS_DIR, "session.dat")

    @classmethod
    def validate(cls):
        return bool(re.fullmatch(r"[A-Za-z0-9_-]{10,200}", cls.API_KEY)
                    and re.fullmatch(r"[a-z][a-z0-9-]{4,62}", cls.PROJECT_ID))

    @classmethod
    def google_sign_in_available(cls):
        """Only the configured project's HTTPS hosting helper may receive tokens."""
        if not cls.validate():
            return False
        try:
            parts = urlsplit(cls.GOOGLE_SIGN_IN_URL)
            allowed = {f"{cls.PROJECT_ID}.firebaseapp.com", f"{cls.PROJECT_ID}.web.app"}
            if (re.fullmatch(r"[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?", cls.AUTH_DOMAIN)
                    and "." in cls.AUTH_DOMAIN):
                allowed.add(cls.AUTH_DOMAIN)
            return bool(parts.scheme == "https" and parts.hostname in allowed
                        and parts.port in (None, 443) and not parts.username
                        and not parts.password and not parts.fragment)
        except ValueError:
            return False

GoogleAuthConfig = FirebaseAuthConfig
