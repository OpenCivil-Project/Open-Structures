"""Guest, offline profile, and Firebase session boundaries with mocked I/O."""

from datetime import datetime, timedelta, timezone
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import Mock, patch

_AUTH_DIR = Path(__file__).resolve().parents[1] / "app" / "auth"
_PACKAGE = "opencivil_auth_manager_test_package"

class FakeFirebaseError(Exception):
    def __init__(self, code="NETWORK_ERROR", status_code=None):
        super().__init__("Authentication could not be completed.")
        self.code = code
        self.status_code = status_code

def load_manager():
    package = ModuleType(_PACKAGE)
    package.__path__ = [str(_AUTH_DIR)]
    config = ModuleType(_PACKAGE + ".config")
    config.FirebaseAuthConfig = SimpleNamespace(CREDENTIALS_DIR="unused", CREDENTIALS_FILE="unused")
    dialog = ModuleType(_PACKAGE + ".dialog")
    dialog.LoginDialog = Mock()
    firebase = ModuleType(_PACKAGE + ".firebase_client")
    firebase.FirebaseClient = Mock()
    firebase.FirebaseAuthError = FakeFirebaseError
    qt = ModuleType("PyQt6")
    widgets = ModuleType("PyQt6.QtWidgets")
    widgets.QDialog = SimpleNamespace(DialogCode=SimpleNamespace(Accepted=1))
    modules = {
        _PACKAGE: package, config.__name__: config, dialog.__name__: dialog,
        firebase.__name__: firebase, "PyQt6": qt, "PyQt6.QtWidgets": widgets,
    }
    with patch.dict(sys.modules, modules):
        spec = importlib.util.spec_from_file_location(_PACKAGE + ".manager", _AUTH_DIR / "manager.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    return module

manager_module = load_manager()

def session(*, expired=False, suffix=""):
    expiry = datetime.now(timezone.utc) + timedelta(hours=-1 if expired else 1)
    return {
        "access_token": "fake-access" + suffix,
        "refresh_token": "fake-refresh" + suffix,
        "expires_at": expiry.isoformat(),
    }

class AuthManagerTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name)
        config = SimpleNamespace(
            CREDENTIALS_DIR=str(self.path),
            CREDENTIALS_FILE=str(self.path / "user_credentials.json"),
            SESSION_FILE=str(self.path / "session.dat"),
        )
        self.config_patch = patch.object(manager_module, "FirebaseAuthConfig", config)
        self.config_patch.start()
        self.addCleanup(self.config_patch.stop)
        self.store = Mock()
        self.store.load.return_value = None
        self.store_patch = patch.object(manager_module, "SessionStore", return_value=self.store)
        self.store_patch.start()
        self.addCleanup(self.store_patch.stop)
        self.client = Mock(configured=True)
        self.client_patch = patch.object(manager_module, "FirebaseClient", return_value=self.client)
        self.client_patch.start()
        self.addCleanup(self.client_patch.stop)
        self.user = {
            "uid": "test-uid", "name": "Test User", "email": "test@example.invalid",
            "picture": "", "provider": "email", "email_verified": True,
        }
        self.guest = {"name": "Guest", "email": "", "picture": "", "provider": "guest"}
        self.client.lookup.return_value = dict(self.user)
        self.manager = manager_module.GoogleAuthManager()

    def cache(self, *, expired=False):
        payload = {
            "version": 1, "remember_me": True,
            "user_info": dict(self.user), "session": session(expired=expired),
        }
        self.store.load.return_value = payload
        return payload

    def test_guest_restore_allows_local_use_without_account_auth_or_firebase(self):
        self.store.load.return_value = {
            "version": 1, "remember_me": True, "user_info": self.guest,
        }
        self.assertTrue(self.manager.restore_session())
        self.assertEqual(self.manager.user_info["provider"], "guest")
        self.assertFalse(self.manager.is_authenticated())
        self.client.lookup.assert_not_called()
        self.client.refresh.assert_not_called()
        manager_module.FirebaseClient.assert_not_called()

    def test_online_restore_uses_firebase_profile(self):
        payload = self.cache()
        payload["user_info"]["name"] = "Old Cached Name"
        self.assertTrue(self.manager.restore_session())
        self.assertEqual(self.manager.get_user_name(), "Test User")
        self.assertTrue(self.manager.is_authenticated())
        self.assertFalse(self.manager.offline_session)
        self.assertIsNone(self.manager.credentials)

    def test_offline_restore_allows_local_profile_without_account_auth(self):
        self.cache()
        self.client.lookup.side_effect = FakeFirebaseError()
        self.assertTrue(self.manager.restore_session())
        self.assertTrue(self.manager.offline_session)
        self.assertFalse(self.manager.is_authenticated())
        self.assertEqual(self.manager.get_user_email(), self.user["email"])
        self.assertEqual(self.client.TIMEOUT, (1.5, 1.5))
        self.store.remove.assert_not_called()

    def test_unconfigured_firebase_restores_only_offline_profile(self):
        self.cache(expired=True)
        self.client.configured = False
        self.assertTrue(self.manager.restore_session())
        self.assertFalse(self.manager.is_authenticated())
        self.client.lookup.assert_not_called()
        self.client.refresh.assert_not_called()

    def test_expired_token_refreshes_and_saves_rotated_tokens(self):
        self.cache(expired=True)
        new_session = session(suffix="-new")
        self.client.refresh.return_value = {"user": self.user, "session": new_session}
        self.assertTrue(self.manager.restore_session())
        self.assertEqual(self.manager.session, new_session)
        self.assertTrue(self.manager.is_authenticated())
        self.client.lookup.assert_not_called()                                            
        self.assertEqual(self.store.save.call_args.args[0]["session"], new_session)

    def test_firebase_token_expired_response_refreshes(self):
        self.cache()
        self.client.lookup.side_effect = FakeFirebaseError("TOKEN_EXPIRED", 400)
        self.client.refresh.return_value = {"user": self.user, "session": session(suffix="-new")}
        self.assertTrue(self.manager.restore_session())
        self.assertTrue(self.manager.is_authenticated())
        self.client.refresh.assert_called_once()

    def test_disabled_or_invalid_accounts_are_not_restored_offline(self):
        for code in ("USER_DISABLED", "INVALID_ID_TOKEN", "EMAIL_NOT_VERIFIED"):
            with self.subTest(code=code):
                self.cache()
                self.client.lookup.side_effect = FakeFirebaseError(code, 400)
                self.assertFalse(self.manager.restore_session())
                self.assertIsNone(self.manager.user_info)
                self.assertIsNone(self.manager.session)
        self.assertEqual(self.store.remove.call_count, 3)

    def test_rate_limit_retains_only_offline_profile(self):
        self.cache()
        self.client.lookup.side_effect = FakeFirebaseError("TOO_MANY_ATTEMPTS_TRY_LATER", 429)
        self.assertTrue(self.manager.restore_session())
        self.assertFalse(self.manager.is_authenticated())
        self.store.remove.assert_not_called()

    def test_expired_session_does_not_remain_authenticated(self):
        self.cache()
        self.assertTrue(self.manager.restore_session())
        self.manager.session = session(expired=True)
        self.assertFalse(self.manager.is_authenticated())

    def test_account_mismatch_clears_remembered_session(self):
        self.cache()
        self.client.lookup.return_value = dict(self.user, uid="different-uid")
        self.assertFalse(self.manager.restore_session())
        self.store.remove.assert_called_once()

    def test_legacy_account_json_never_autoauthenticates(self):
        legacy = self.path / "user_credentials.json"
        legacy.write_text(json.dumps({"remember_me": True, "user_info": self.user,
                                      "credentials": {"token": "fake-old-token"}}), encoding="utf-8")
        self.assertFalse(self.manager.restore_session())
        self.assertFalse(legacy.exists())
        self.client.lookup.assert_not_called()

    def test_legacy_guest_migrates_without_network(self):
        legacy = self.path / "user_credentials.json"
        legacy.write_text(json.dumps({"remember_me": True, "user_info": self.guest}), encoding="utf-8")
        self.assertTrue(self.manager.restore_session())
        self.assertFalse(legacy.exists())
        self.store.save.assert_called_once()
        self.assertEqual(self.manager.user_info["provider"], "guest")
        self.client.lookup.assert_not_called()

    def test_invalid_expiry_clears_cache_without_network(self):
        payload = self.cache()
        payload["session"]["expires_at"] = "2026-01-01T00:00:00"
        self.assertFalse(self.manager.restore_session())
        self.client.lookup.assert_not_called()
        self.store.remove.assert_called_once()

    def test_login_without_remember_removes_previous_cache(self):
        result = dict(self.user, session=session())
        dialog = Mock(user_info=result, remember_me=False)
        dialog.exec.return_value = 1
        with patch.object(manager_module, "LoginDialog", return_value=dialog):
            self.assertTrue(self.manager.login())
        self.store.remove.assert_called_once()
        self.store.save.assert_not_called()
        self.assertTrue(self.manager.is_authenticated())

    def test_guest_login_remembers_and_does_not_keep_tokens(self):
        dialog = Mock(user_info=self.guest, remember_me=True)
        dialog.exec.return_value = 1
        with patch.object(manager_module, "LoginDialog", return_value=dialog):
            self.assertTrue(self.manager.login())
        self.assertFalse(self.manager.is_authenticated())
        self.assertIsNone(self.manager.session)
        self.assertNotIn("session", self.store.save.call_args.args[0])

    def test_logout_clears_local_secrets_and_legacy_cache(self):
        self.cache()
        self.assertTrue(self.manager.restore_session())
        legacy = self.path / "user_credentials.json"
        legacy.write_text("obsolete", encoding="utf-8")
        self.manager.logout()
        self.assertIsNone(self.manager.user_info)
        self.assertIsNone(self.manager.session)
        self.assertFalse(self.manager.is_authenticated())
        self.assertFalse(legacy.exists())
        self.store.remove.assert_called_once()

    def test_storage_failure_removes_older_cached_identity(self):
        self.manager._adopt(self.user, session(), checked=True)
        self.store.save.side_effect = manager_module.SessionStoreError("unavailable")
        self.manager._save_credentials()
        self.store.remove.assert_called_once()
        self.assertTrue(self.manager.is_authenticated())                                          

if __name__ == "__main__":
    unittest.main()
