"""Real Qt account UI: email links and uninterrupted offline guest access."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from datetime import datetime, timedelta, timezone
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from PyQt6.QtWidgets import QApplication, QDialog
from app.auth.dialog import LoginDialog, EmailVerificationDialog, EmailNoticeDialog
from app.auth.thread import _ACTIVE_THREADS

def profile():
    return {"uid":"test-user", "name":"Test User", "email":"test@example.com",
            "picture":"", "provider":"email", "email_verified":True,
            "session":{"access_token":"fake-access", "refresh_token":"fake-refresh",
                       "expires_at":(datetime.now(timezone.utc)+timedelta(hours=1)).isoformat()}}

class AuthDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.application = QApplication.instance() or QApplication([])

    def setUp(self):
        self.config = patch("app.auth.dialog.FirebaseAuthConfig.validate", return_value=True)
        self.config.start()
        self.addCleanup(self.config.stop)
        self.dialog = LoginDialog()
        self.addCleanup(self.dialog.close)

    def pump(self, seconds=0.1):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            self.application.processEvents()
            time.sleep(0.005)

    def test_guest_requires_no_account_request(self):
        with patch("app.auth.email_auth._get_client", side_effect=AssertionError("No network")):
            self.dialog._on_guest_login()
            self.pump(0.25)
        self.assertEqual(self.dialog.result(), QDialog.DialogCode.Accepted)
        self.assertEqual(self.dialog.user_info["provider"], "guest")
        self.assertNotIn("session", self.dialog.user_info)

    def test_guest_remains_available_while_login_is_stalled(self):
        release = threading.Event()
        entered = threading.Event()
        self.addCleanup(release.set)
        def stalled(_email, _password):
            entered.set()
            release.wait(3)
            return True, "", profile()
        self.dialog.input_email.setText("test@example.com")
        self.dialog.input_password.setText("example-password")
        with patch("app.auth.email_auth.login", side_effect=stalled):
            self.dialog._on_primary()
            self.assertTrue(entered.wait(1))
            self.assertTrue(self.dialog.btn_guest.isEnabled())
            self.assertFalse(self.dialog.btn_primary.isEnabled())
            self.dialog._on_guest_login()
            self.pump(0.3)
            self.assertEqual(self.dialog.user_info["provider"], "guest")
            self.assertEqual(self.dialog.result(), QDialog.DialogCode.Accepted)
            release.set()
            self.pump(0.2)
            self.assertEqual(self.dialog.user_info["provider"], "guest")

    def test_unverified_login_only_opens_email_link_screen(self):
        pending = profile()
        pending["email_verified"] = False
        pending["pending_verification"] = True
        with patch.object(self.dialog, "_show_verify_dialog") as show:
            self.dialog._on_login_result((False, "Verify your email", pending))
        show.assert_called_once_with(pending)
        self.assertIsNone(self.dialog.user_info)
        self.assertNotEqual(self.dialog.result(), QDialog.DialogCode.Accepted)

    def test_partial_registration_failure_allows_resend(self):
        pending = profile()
        pending["pending_verification"] = True
        with patch.object(self.dialog, "_show_verify_dialog") as show:
            self.dialog._on_register_result((False, "Email could not be sent", pending))
        show.assert_called_once_with(pending, "Email could not be sent")

    def test_verification_uses_server_check_and_fresh_tokens(self):
        pending = profile()
        pending["email_verified"] = False
        verify = EmailVerificationDialog(pending, parent=self.dialog)
        self.addCleanup(verify.close)
        updated = profile()
        updated["session"]["access_token"] = "fresh-verified-access"
        with patch("app.auth.email_auth.check_verification", return_value=(True,"",updated)) as check:
            verify._check()
            self.pump(0.2)
        check.assert_called_once_with("fake-access", "fake-refresh")
        self.assertEqual(verify.result(), QDialog.DialogCode.Accepted)
        self.assertEqual(verify.user_info["session"]["access_token"], "fresh-verified-access")
        self.assertFalse(hasattr(verify, "input_code"))

    def test_reset_uses_email_link_notice(self):
        notice = EmailNoticeDialog("test@example.com", parent=self.dialog)
        self.addCleanup(notice.close)
        self.assertFalse(hasattr(notice, "input_code"))
        with patch("app.auth.dialog.EmailNoticeDialog") as constructor:
            self.dialog._on_reset_result("test@example.com", (True,"",None))
        constructor.assert_called_once_with("test@example.com", parent=self.dialog)

    def test_late_google_worker_cannot_override_new_attempt_or_email_work(self):
        cancelled = SimpleNamespace(_cancelled=threading.Event(), isRunning=lambda:False, cancel=Mock())
        cancelled._cancelled.set()
        current = SimpleNamespace(_cancelled=threading.Event(), isRunning=lambda:False, cancel=Mock())
        self.dialog._auth_thread = current
        with patch.object(self.dialog, "_on_auth_complete") as complete,              patch.object(self.dialog, "_on_auth_failed") as failed:
            self.dialog._google_complete(cancelled, profile())
            self.dialog._google_failed(cancelled, "late failure")
            self.dialog._google_progress(cancelled, "late progress")
            complete.assert_not_called()
            failed.assert_not_called()
            account_worker = SimpleNamespace(cancel=Mock())
            self.dialog._account_thread = account_worker
            self.dialog._google_complete(current, profile())
            self.dialog._google_failed(current, "late failure")
            complete.assert_not_called()
            failed.assert_not_called()
            self.dialog._account_thread = None

    @classmethod
    def tearDownClass(cls):
        deadline = time.monotonic() + 3
        while _ACTIVE_THREADS and time.monotonic() < deadline:
            cls.application.processEvents()
            time.sleep(0.01)
        if _ACTIVE_THREADS:
            raise AssertionError("An authentication thread remained running")

if __name__ == "__main__":
    unittest.main()
