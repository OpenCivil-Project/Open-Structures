"""Account security tests with fake HTTP; no Firebase, Atlas, or email calls."""

import base64
import importlib
import importlib.util
import json
import os
import sys
import types
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch

import requests

AUTH_PATH = Path(__file__).resolve().parents[1] / "app" / "auth"
PACKAGE = "opencivil_firebase_test_subject"
package = types.ModuleType(PACKAGE)
package.__path__ = [str(AUTH_PATH)]
sys.modules.setdefault(PACKAGE, package)
firebase = importlib.import_module(PACKAGE + ".firebase_client")
config_module = importlib.import_module(PACKAGE + ".config")
email_auth = importlib.import_module(PACKAGE + ".email_auth")
FirebaseClient = firebase.FirebaseClient
FirebaseAuthError = firebase.FirebaseAuthError
EmailNotVerified = firebase.EmailNotVerified

NOW = datetime(2026, 10, 31, 12, 0, tzinfo=timezone.utc)

class Config(config_module.FirebaseAuthConfig):
    API_KEY = "public-test-api-key"
    PROJECT_ID = "test-project"
    AUTH_DOMAIN = "test-project.firebaseapp.com"
    GOOGLE_SIGN_IN_URL = "https://test-project.web.app/sign-in/"

def token(*, uid="test-user", project="test-project", verified=True,
          provider="password", expires=None, **extra):
    claims = {"aud": project, "iss": "https://securetoken.google.com/" + project,
              "sub": uid, "exp": expires if expires is not None else int((NOW + timedelta(hours=1)).timestamp()),
              "email_verified": verified, "firebase": {"sign_in_provider": provider}}
    claims.update(extra)
    encode = lambda value: base64.urlsafe_b64encode(json.dumps(value).encode()).decode().rstrip("=")
    return encode({"alg": "RS256"}) + "." + encode(claims) + ".testsignature"

def account_response(id_token=None, refresh="refresh-test-token", uid="test-user"):
    return {"localId": uid, "idToken": id_token or token(), "refreshToken": refresh, "expiresIn": "3600"}

def user_response(*, verified=True, uid="test-user", provider="password", disabled=False):
    return {"users": [{"localId": uid, "email": "PERSON@example.com", "displayName": "Person",
                       "photoUrl": "https://example.com/avatar.png", "emailVerified": verified,
                       "disabled": disabled, "providerUserInfo": [{"providerId": provider}]}]}

class Response:
    def __init__(self, data=None, status=200, json_error=None):
        self.data = data
        self.status_code = status
        self.json_error = json_error
        self.json_calls = 0

    def json(self):
        self.json_calls += 1
        if self.json_error:
            raise self.json_error
        return self.data

class HTTP:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if not self.responses:
            raise AssertionError("Unexpected HTTP call in an isolated test")
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

class FirebaseClientTests(unittest.TestCase):
    def client(self, *responses):
        http = HTTP(*responses)
        return FirebaseClient(Config, http, now=lambda: NOW), http

    def test_verified_login_uses_fixed_endpoints_and_bounded_requests(self):
        client, http = self.client(Response(account_response()), Response(user_response()))
        result = client.sign_in(" PERSON@example.com ", "test-password")
        self.assertEqual(result["user"]["email"], "person@example.com")
        self.assertEqual(result["user"]["provider"], "email")
        self.assertTrue(result["user"]["email_verified"])
        self.assertEqual(datetime.fromisoformat(result["session"]["expires_at"]), NOW + timedelta(hours=1))
        self.assertEqual(http.calls[0][0], FirebaseClient.ACCOUNT_BASE + "signInWithPassword")
        self.assertEqual(http.calls[1][0], FirebaseClient.ACCOUNT_BASE + "lookup")
        self.assertEqual(http.calls[0][1]["json"]["email"], "person@example.com")
        for _, kwargs in http.calls:
            self.assertEqual(kwargs["timeout"], (5, 20))
            self.assertIs(kwargs["allow_redirects"], False)
            self.assertEqual(kwargs["params"], {"key": Config.API_KEY})

    def test_wrong_password_does_not_surface_remote_details(self):
        client, _ = self.client(Response({"error": {"message": "INVALID_PASSWORD : private-password-detail"}}, 400))
        with self.assertRaises(FirebaseAuthError) as caught:
            client.sign_in("person@example.com", "private-password-detail")
        self.assertEqual(caught.exception.message, "Email or password is incorrect.")
        self.assertNotIn("private-password-detail", str(caught.exception))
        self.assertEqual(caught.exception.status_code, 400)

    def test_unverified_login_is_verification_only(self):
        pending_token = token(verified=False)
        client, _ = self.client(Response(account_response(pending_token)), Response(user_response(verified=False)))
        with self.assertRaises(EmailNotVerified) as caught:
            client.sign_in("person@example.com", "test-password")
        self.assertFalse(caught.exception.user["email_verified"])
        self.assertEqual(caught.exception.pending_session["access_token"], pending_token)
        self.assertEqual(caught.exception.code, "EMAIL_NOT_VERIFIED")

    def test_default_lookup_rejects_unverified_user(self):
        client, _ = self.client(Response(user_response(verified=False)))
        with self.assertRaises(EmailNotVerified):
            client.lookup(token(verified=False))

    def test_google_tokens_are_authenticated_by_lookup(self):
        google_token = token(provider="google.com")
        client, http = self.client(Response(user_response(provider="google.com")))
        result = client.session_from_tokens(google_token, "google-refresh-token", "3600")
        self.assertEqual(result["user"]["provider"], "google")
        self.assertEqual(http.calls[0][1]["json"], {"idToken": google_token})

    def test_foreign_project_is_rejected_before_http(self):
        client, http = self.client()
        with self.assertRaises(FirebaseAuthError) as caught:
            client.lookup(token(project="foreign-project"))
        self.assertEqual(caught.exception.code, "INVALID_ID_TOKEN")
        self.assertEqual(http.calls, [])

    def test_lookup_identity_must_match_authenticated_token_subject(self):
        client, _ = self.client(Response(user_response(uid="different-user")))
        with self.assertRaises(FirebaseAuthError) as caught:
            client.lookup(token())
        self.assertEqual(caught.exception.code, "INVALID_ID_TOKEN")

    def test_anonymous_identity_cannot_become_account_session(self):
        client, _ = self.client(Response(user_response(provider="anonymous")))
        with self.assertRaises(FirebaseAuthError) as caught:
            client.lookup(token(provider="anonymous"))
        self.assertEqual(caught.exception.code, "UNSUPPORTED_PROVIDER")

    def test_disabled_user_is_rejected(self):
        client, _ = self.client(Response(user_response(disabled=True)))
        with self.assertRaises(FirebaseAuthError) as caught:
            client.lookup(token())
        self.assertEqual(caught.exception.code, "USER_DISABLED")

    def test_missing_remote_user_is_rejected(self):
        client, _ = self.client(Response({"users": []}))
        with self.assertRaises(FirebaseAuthError) as caught:
            client.lookup(token())
        self.assertEqual(caught.exception.code, "USER_NOT_FOUND")

    def test_expired_token_does_not_make_lookup_request(self):
        client, http = self.client()
        with self.assertRaises(FirebaseAuthError) as caught:
            client.lookup(token(expires=int(NOW.timestamp()) - 1))
        self.assertEqual(caught.exception.code, "TOKEN_EXPIRED")
        self.assertEqual(http.calls, [])

    def test_refresh_uses_form_endpoint_and_validates_new_session(self):
        new_token = token()
        refresh = {"id_token": new_token, "refresh_token": "rotated-refresh-token",
                   "expires_in": "3600", "user_id": "test-user"}
        client, http = self.client(Response(refresh), Response(user_response()))
        result = client.refresh("old-refresh-token")
        self.assertEqual(result["session"]["refresh_token"], "rotated-refresh-token")
        self.assertEqual(http.calls[0][0], FirebaseClient.REFRESH_URL)
        self.assertEqual(http.calls[0][1]["data"], {"grant_type": "refresh_token", "refresh_token": "old-refresh-token"})
        self.assertNotIn("json", http.calls[0][1])

    def test_refresh_never_promotes_unverified_identity(self):
        refresh = {"id_token": token(verified=False), "refresh_token": "rotated-refresh-token",
                   "expires_in": "3600", "user_id": "test-user"}
        client, _ = self.client(Response(refresh), Response(user_response(verified=False)))
        with self.assertRaises(EmailNotVerified) as caught:
            client.refresh("old-refresh-token")
        self.assertEqual(caught.exception.pending_session["refresh_token"], "rotated-refresh-token")

    def test_refresh_response_identity_must_match(self):
        refresh = {"id_token": token(), "refresh_token": "rotated-refresh-token",
                   "expires_in": "3600", "user_id": "other-user"}
        client, _ = self.client(Response(refresh), Response(user_response()))
        with self.assertRaises(FirebaseAuthError) as caught:
            client.refresh("old-refresh-token")
        self.assertEqual(caught.exception.code, "INVALID_ID_TOKEN")

    def test_malformed_and_oversized_tokens_are_rejected_without_http(self):
        for invalid in (None, "not-a-token", "a.b.c", "a" * 16385, token(exp=True), token(exp=float("nan"))):
            with self.subTest(kind=type(invalid).__name__):
                client, http = self.client()
                with self.assertRaises(FirebaseAuthError) as caught:
                    client.lookup(invalid)
                self.assertEqual(caught.exception.code, "INVALID_ID_TOKEN")
                self.assertEqual(http.calls, [])
        client, http = self.client()
        with self.assertRaises(FirebaseAuthError):
            client.refresh("unsafe refresh token")
        self.assertEqual(http.calls, [])

    def test_invalid_session_expiry_is_rejected(self):
        client, http = self.client()
        with self.assertRaises(FirebaseAuthError) as caught:
            client.session_from_tokens(token(), "refresh-test-token", "not-a-duration")
        self.assertEqual(caught.exception.code, "SERVICE_RESPONSE")
        self.assertEqual(http.calls, [])

    def test_redirect_is_rejected_without_reading_response_body(self):
        response = Response({"private": "detail"}, 307)
        client, http = self.client(response)
        with self.assertRaises(FirebaseAuthError) as caught:
            client.sign_in("person@example.com", "test-password")
        self.assertEqual(caught.exception.code, "SERVICE_REDIRECT")
        self.assertEqual(response.json_calls, 0)
        self.assertIs(http.calls[0][1]["allow_redirects"], False)

    def test_unreadable_response_is_sanitized(self):
        client, _ = self.client(Response(status=502, json_error=ValueError("private-response-token")))
        with self.assertRaises(FirebaseAuthError) as caught:
            client.sign_in("person@example.com", "test-password")
        self.assertEqual(caught.exception.code, "SERVICE_RESPONSE")
        self.assertNotIn("private-response-token", str(caught.exception))

    def test_unknown_error_code_does_not_echo_arbitrary_server_content(self):
        client, _ = self.client(Response({"error": {"message": "PRIVATE_TOKEN_DETAIL : extra"}}, 400))
        with self.assertRaises(FirebaseAuthError) as caught:
            client.sign_in("person@example.com", "test-password")
        self.assertEqual(caught.exception.code, "SERVICE_ERROR")
        self.assertNotIn("PRIVATE_TOKEN_DETAIL", str(caught.exception))

    def test_network_exception_does_not_leak_request_url_or_credentials(self):
        client, _ = self.client(requests.Timeout("private-refresh-token in URL"))
        with self.assertRaises(FirebaseAuthError) as caught:
            client.refresh("private-refresh-token")
        self.assertEqual(caught.exception.code, "NETWORK_ERROR")
        self.assertNotIn("private-refresh-token", str(caught.exception))

    def test_password_reset_does_not_disclose_account_existence(self):
        existing, http = self.client(Response({"email": "person@example.com"}))
        absent, _ = self.client(Response({"error": {"message": "EMAIL_NOT_FOUND"}}, 400))
        self.assertEqual(existing.send_password_reset("person@example.com"), absent.send_password_reset("person@example.com"))
        self.assertEqual(http.calls[0][1]["json"]["requestType"], "PASSWORD_RESET")

    def test_verification_email_uses_firebase_id_token(self):
        client, http = self.client(Response({"email": "person@example.com"}))
        pending_token = token(verified=False)
        client.send_verification(pending_token)
        self.assertEqual(http.calls[0][1]["json"], {"requestType": "VERIFY_EMAIL", "idToken": pending_token})

    def test_registration_updates_profile_but_returns_verification_only_session(self):
        pending_token = token(verified=False)
        client, http = self.client(Response(account_response(pending_token)),
                                   Response({"localId": "test-user"}), Response(user_response(verified=False)))
        result = client.sign_up(" Person ", "person@example.com", "test-password")
        self.assertFalse(result["user"]["email_verified"])
        self.assertEqual(http.calls[1][0], FirebaseClient.ACCOUNT_BASE + "update")
        self.assertEqual(http.calls[1][1]["json"]["displayName"], "Person")

    def test_registration_partial_failure_has_account_recovery_instructions(self):
        client, _ = self.client(Response(account_response(token(verified=False))), requests.Timeout("private-data"))
        with self.assertRaises(FirebaseAuthError) as caught:
            client.sign_up("Person", "person@example.com", "test-password")
        self.assertEqual(caught.exception.code, "ACCOUNT_CREATED_SETUP_INCOMPLETE")
        self.assertIn("Sign in", caught.exception.message)
        self.assertNotIn("private-data", caught.exception.message)

    def test_missing_public_config_allows_import_but_never_network(self):
        class Missing(Config):
            API_KEY = ""
        client = FirebaseClient(Missing, HTTP(), now=lambda: NOW)
        self.assertFalse(client.configured)
        with self.assertRaises(FirebaseAuthError) as caught:
            client.sign_in("person@example.com", "test-password")
        self.assertEqual(caught.exception.code, "NOT_CONFIGURED")

class EmailWrapperTests(unittest.TestCase):
    def test_unverified_login_returns_pending_data_without_success(self):
        pending_token = token(verified=False)
        client = FirebaseClient(Config, HTTP(Response(account_response(pending_token)),
                                            Response(user_response(verified=False))), now=lambda: NOW)
        with patch.object(email_auth, "_client", client):
            success, message, info = email_auth.login("person@example.com", "test-password")
        self.assertFalse(success)
        self.assertIn("verify", message)
        self.assertTrue(info["pending_verification"])
        self.assertFalse(info["email_verified"])

    def test_verification_checks_then_refreshes_to_issue_fresh_token(self):
        old_token = token(verified=False)
        new_token = token(verified=True)
        refresh = {"id_token": new_token, "refresh_token": "new-refresh-token",
                   "expires_in": "3600", "user_id": "test-user"}
        http = HTTP(Response(user_response()), Response(refresh), Response(user_response()))
        client = FirebaseClient(Config, http, now=lambda: NOW)
        with patch.object(email_auth, "_client", client):
            success, _, info = email_auth.check_verification(old_token, "old-refresh-token")
        self.assertTrue(success)
        self.assertEqual(info["session"]["access_token"], new_token)
        self.assertTrue(info["email_verified"])
        self.assertEqual(http.calls[1][0], FirebaseClient.REFRESH_URL)

    def test_unverified_poll_does_not_refresh_or_authenticate(self):
        http = HTTP(Response(user_response(verified=False)))
        client = FirebaseClient(Config, http, now=lambda: NOW)
        with patch.object(email_auth, "_client", client):
            success, _, info = email_auth.check_verification(token(verified=False), "old-refresh-token")
        self.assertFalse(success)
        self.assertIsNone(info)
        self.assertEqual(len(http.calls), 1)

    def test_email_failure_preserves_created_account_recovery(self):
        pending_token = token(verified=False)
        http = HTTP(Response(account_response(pending_token)), Response({}),
                    Response(user_response(verified=False)), requests.Timeout("private-detail"))
        client = FirebaseClient(Config, http, now=lambda: NOW)
        with patch.object(email_auth, "_client", client):
            success, message, info = email_auth.register("Person", "person@example.com", "test-password")
        self.assertFalse(success)
        self.assertTrue(info["pending_verification"])
        self.assertIn("Resend", message)
        self.assertNotIn("private-detail", message)

class PublicConfigurationTests(unittest.TestCase):
    def test_import_reads_only_public_settings_without_dotenv(self):
        dotenv = types.ModuleType("dotenv")
        dotenv.load_dotenv = lambda *args, **kwargs: self.fail("Desktop configuration loaded dotenv")
        values = {"OPENCIVIL_FIREBASE_API_KEY": "public-test-api-key",
                  "OPENCIVIL_FIREBASE_PROJECT_ID": "test-project",
                  "MONGO_URI": "private-test-db-setting",
                  "GMAIL_APP_PASS": "private-test-mail-setting"}
        spec = importlib.util.spec_from_file_location("isolated_firebase_settings", AUTH_PATH / "config.py")
        module = importlib.util.module_from_spec(spec)
        with patch.dict(os.environ, values), patch.dict(sys.modules, {"dotenv": dotenv}), patch.object(Path, "is_file", return_value=False):
            spec.loader.exec_module(module)
        self.assertTrue(module.FirebaseAuthConfig.validate())
        self.assertFalse(hasattr(module.FirebaseAuthConfig, "CLIENT_SECRET"))
        self.assertEqual(module.GoogleAuthConfig, module.FirebaseAuthConfig)

    def test_browser_helper_requires_trusted_https_host(self):
        self.assertTrue(Config.google_sign_in_available())
        for unsafe in ("http://test-project.web.app/login", "https://attacker.example/login",
                       "https://test-project.web.app:8443/login", "https://user@test-project.web.app/login"):
            with self.subTest(url=unsafe):
                class Unsafe(Config):
                    GOOGLE_SIGN_IN_URL = unsafe
                self.assertFalse(Unsafe.google_sign_in_available())

if __name__ == "__main__":
    unittest.main()
