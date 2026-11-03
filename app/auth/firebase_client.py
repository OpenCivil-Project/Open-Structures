"""Bounded Firebase Authentication REST calls for the desktop application.

Firebase validates credentials and tokens. No Admin SDK, MongoDB connection,
email password, service-account key, or application secret belongs here.
"""

import base64
import json
import math
import re
from datetime import datetime, timezone, timedelta

import requests

from .config import FirebaseAuthConfig

class FirebaseAuthError(Exception):
    def __init__(self, message, code, status_code=None):
        super().__init__(message)
        self.message = message
        self.code = code
        self.status_code = status_code

class EmailNotVerified(FirebaseAuthError):
    """A verification-only session must never be accepted as an account login."""

    def __init__(self, pending_session=None, user=None):
        super().__init__("Please verify your email using the link in your inbox, then try again.",
                         "EMAIL_NOT_VERIFIED")
        self.pending_session = pending_session
        self.user = user

_ERROR_MESSAGES = {
    "INVALID_LOGIN_CREDENTIALS": "Email or password is incorrect.",
    "INVALID_PASSWORD": "Email or password is incorrect.",
    "EMAIL_NOT_FOUND": "Email or password is incorrect.",
    "INVALID_EMAIL": "Please enter a valid email address.",
    "EMAIL_EXISTS": "An account already uses this email. Sign in or reset your password.",
    "WEAK_PASSWORD": "Choose a stronger password with at least eight characters.",
    "PASSWORD_DOES_NOT_MEET_REQUIREMENTS": "This password does not meet the account password policy.",
    "USER_DISABLED": "This account is disabled. Please contact the project administrator.",
    "USER_NOT_FOUND": "This session is no longer available. Please sign in again.",
    "INVALID_ID_TOKEN": "This session is no longer valid. Please sign in again.",
    "TOKEN_EXPIRED": "Your session has expired. Please sign in again.",
    "INVALID_REFRESH_TOKEN": "This session is no longer valid. Please sign in again.",
    "INVALID_GRANT": "This session is no longer valid. Please sign in again.",
    "CREDENTIAL_TOO_OLD_LOGIN_AGAIN": "Please sign in again before changing your account.",
    "TOO_MANY_ATTEMPTS_TRY_LATER": "Too many attempts. Please wait before trying again.",
    "QUOTA_EXCEEDED": "The account service is temporarily busy. Please try again later.",
    "OPERATION_NOT_ALLOWED": "This sign-in method is not enabled for this application.",
    "API_KEY_INVALID": "Accounts are not configured correctly for this application. Guest mode is available.",
    "PROJECT_NOT_FOUND": "Accounts are not configured correctly for this application. Guest mode is available.",
    "CONFIGURATION_NOT_FOUND": "Accounts are not configured correctly for this application. Guest mode is available.",
    "INVALID_OOB_CODE": "This email link is invalid. Please request a new one.",
    "EXPIRED_OOB_CODE": "This email link has expired. Please request a new one.",
}

class FirebaseClient:
    ACCOUNT_BASE = "https://identitytoolkit.googleapis.com/v1/accounts:"
    REFRESH_URL = "https://securetoken.googleapis.com/v1/token"
    TIMEOUT = (5, 20)
    MAX_ID_TOKEN = 16384
    MAX_REFRESH_TOKEN = 8192

    def __init__(self, config=FirebaseAuthConfig, session=None, now=None):
        self.config = config
        self._http = session if session is not None else requests.Session()
        self._now = now if now is not None else lambda: datetime.now(timezone.utc)

    @property
    def configured(self):
        return bool(self.config.validate())

    def _require_config(self):
        if not self.configured:
            raise FirebaseAuthError(
                "Accounts are not configured for this build. You can continue in guest mode.",
                "NOT_CONFIGURED",
            )

    def _request(self, operation, payload, *, refresh=False):
        self._require_config()
        url = self.REFRESH_URL if refresh else self.ACCOUNT_BASE + operation
        kwargs = {"params": {"key": self.config.API_KEY}, "timeout": self.TIMEOUT,
                  "allow_redirects": False, "headers": {"Accept": "application/json"}}
        kwargs["data" if refresh else "json"] = payload
        try:
            response = self._http.post(url, **kwargs)
        except requests.RequestException:
            raise FirebaseAuthError(
                "Cannot reach the account service. Check your internet connection or continue in guest mode.",
                "NETWORK_ERROR",
            ) from None
        status = response.status_code
        if 300 <= status < 400:
            raise FirebaseAuthError("The account service returned an unexpected redirect. Please try again later.",
                                    "SERVICE_REDIRECT", status)
        try:
            data = response.json()
        except (ValueError, TypeError):
            raise FirebaseAuthError("The account service returned an unreadable response. Please try again later.",
                                    "SERVICE_RESPONSE", status) from None
        if not isinstance(data, dict):
            raise FirebaseAuthError("The account service returned an unexpected response. Please try again later.",
                                    "SERVICE_RESPONSE", status)
        if status >= 400 or isinstance(data.get("error"), dict):
            error = data.get("error", {})
            raw_code = error.get("message", "") if isinstance(error, dict) else ""
            match = re.match(r"^([A-Z][A-Z0-9_]{1,80})(?:\s|:|$)", raw_code) if isinstance(raw_code, str) else None
            code = match.group(1) if match and match.group(1) in _ERROR_MESSAGES else "SERVICE_ERROR"
            if status == 429:
                message = "Too many attempts. Please wait before trying again."
            elif status >= 500:
                message = "The account service is temporarily unavailable. Please try again later."
            else:
                message = _ERROR_MESSAGES.get(code, "The account request could not be completed. Please try again.")
            raise FirebaseAuthError(message, code, status)
        return data

    @staticmethod
    def _uid(value):
        if (not isinstance(value, str) or not 1 <= len(value) <= 128
                or any(ord(char) < 33 for char in value)):
            raise FirebaseAuthError("The account service returned an invalid identity. Please sign in again.",
                                    "SERVICE_RESPONSE")
        return value

    def _id_claims(self, token):
        """Validate format/project/expiry; Firebase lookup performs authentication."""
        self._require_config()
        if (not isinstance(token, str) or len(token) > self.MAX_ID_TOKEN
                or not re.fullmatch(r"[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+", token)):
            raise FirebaseAuthError(_ERROR_MESSAGES["INVALID_ID_TOKEN"], "INVALID_ID_TOKEN")
        try:
            part = token.split(".")[1]
            claims = json.loads(base64.urlsafe_b64decode(part + "=" * (-len(part) % 4)).decode("utf-8"))
        except (ValueError, UnicodeError):
            raise FirebaseAuthError(_ERROR_MESSAGES["INVALID_ID_TOKEN"], "INVALID_ID_TOKEN") from None
        if not isinstance(claims, dict):
            raise FirebaseAuthError(_ERROR_MESSAGES["INVALID_ID_TOKEN"], "INVALID_ID_TOKEN")
        if (claims.get("aud") != self.config.PROJECT_ID
                or claims.get("iss") != f"https://securetoken.google.com/{self.config.PROJECT_ID}"):
            raise FirebaseAuthError(_ERROR_MESSAGES["INVALID_ID_TOKEN"], "INVALID_ID_TOKEN")
        try:
            self._uid(claims.get("sub"))
        except FirebaseAuthError:
            raise FirebaseAuthError(_ERROR_MESSAGES["INVALID_ID_TOKEN"], "INVALID_ID_TOKEN") from None
        expiry = claims.get("exp")
        if (isinstance(expiry, bool) or not isinstance(expiry, (int, float))
                or not math.isfinite(expiry) or expiry > self._now().timestamp() + 86400):
            raise FirebaseAuthError(_ERROR_MESSAGES["INVALID_ID_TOKEN"], "INVALID_ID_TOKEN")
        if expiry <= self._now().timestamp():
            raise FirebaseAuthError(_ERROR_MESSAGES["TOKEN_EXPIRED"], "TOKEN_EXPIRED")
        return claims

    def _refresh_value(self, token):
        if (not isinstance(token, str) or not 1 <= len(token) <= self.MAX_REFRESH_TOKEN
                or not re.fullmatch(r"[A-Za-z0-9._~+/=-]+", token)):
            raise FirebaseAuthError(_ERROR_MESSAGES["INVALID_REFRESH_TOKEN"], "INVALID_REFRESH_TOKEN")
        return token

    def _session(self, id_token, refresh_token, expires_in):
        claims = self._id_claims(id_token)
        self._refresh_value(refresh_token)
        if isinstance(expires_in, bool):
            raise FirebaseAuthError("The account service returned an invalid session. Please sign in again.",
                                    "SERVICE_RESPONSE")
        try:
            seconds = int(expires_in)
        except (TypeError, ValueError, OverflowError):
            raise FirebaseAuthError("The account service returned an invalid session. Please sign in again.",
                                    "SERVICE_RESPONSE") from None
        if not 1 <= seconds <= 86400:
            raise FirebaseAuthError("The account service returned an invalid session. Please sign in again.",
                                    "SERVICE_RESPONSE")
        expiry = min(self._now() + timedelta(seconds=seconds),
                     datetime.fromtimestamp(claims["exp"], timezone.utc))
        return {"access_token": id_token, "refresh_token": refresh_token,
                "expires_at": expiry.isoformat()}

    def lookup(self, id_token, *, require_verified=True):
        claims = self._id_claims(id_token)
        data = self._request("lookup", {"idToken": id_token})
        users = data.get("users")
        if not isinstance(users, list) or len(users) != 1 or not isinstance(users[0], dict):
            raise FirebaseAuthError(_ERROR_MESSAGES["USER_NOT_FOUND"], "USER_NOT_FOUND")
        record = users[0]
        uid = self._uid(record.get("localId"))
        if uid != claims["sub"]:
            raise FirebaseAuthError(_ERROR_MESSAGES["INVALID_ID_TOKEN"], "INVALID_ID_TOKEN")
        if record.get("disabled") is True:
            raise FirebaseAuthError(_ERROR_MESSAGES["USER_DISABLED"], "USER_DISABLED")
        providers = record.get("providerUserInfo", [])
        if not isinstance(providers, list):
            raise FirebaseAuthError("The account service returned an invalid identity. Please sign in again.",
                                    "SERVICE_RESPONSE")
        provider_ids = {item.get("providerId") for item in providers if isinstance(item, dict)
                        and isinstance(item.get("providerId"), str)}
        firebase = claims.get("firebase", {})
        sign_in_provider = firebase.get("sign_in_provider") if isinstance(firebase, dict) else None
        if sign_in_provider == "anonymous" or not provider_ids.intersection({"password", "google.com"}):
            raise FirebaseAuthError("Please sign in with an email or Google account. Guest mode is available separately.",
                                    "UNSUPPORTED_PROVIDER")
        if sign_in_provider is not None and sign_in_provider not in {"password", "google.com"}:
            raise FirebaseAuthError("This sign-in method is not supported by this application.",
                                    "UNSUPPORTED_PROVIDER")
        if sign_in_provider is not None and sign_in_provider not in provider_ids:
            raise FirebaseAuthError(_ERROR_MESSAGES["INVALID_ID_TOKEN"], "INVALID_ID_TOKEN")
        provider = "google" if sign_in_provider == "google.com" or (
            sign_in_provider is None and "google.com" in provider_ids) else "email"
        email = self._email(record.get("email"))
        name = record.get("displayName", "")
        picture = record.get("photoUrl", "")
        if not isinstance(name, str) or len(name) > 500 or not isinstance(picture, str) or len(picture) > 4096:
            raise FirebaseAuthError("The account service returned an invalid profile. Please sign in again.",
                                    "SERVICE_RESPONSE")
        user = {"uid": uid, "name": name.strip() or email.split("@", 1)[0], "email": email,
                "picture": picture, "provider": provider, "email_verified": record.get("emailVerified") is True}
        if require_verified and not user["email_verified"]:
            raise EmailNotVerified(user=user)
        return user

    def session_from_tokens(self, id_token, refresh_token, expires_in=3600):
        session = self._session(id_token, refresh_token, expires_in)
        user = self.lookup(id_token, require_verified=False)
        if not user["email_verified"]:
            raise EmailNotVerified(session, user)
        return {"user": user, "session": session}

    def _account_result(self, data, *, allow_unverified=False):
        session = self._session(data.get("idToken"), data.get("refreshToken"), data.get("expiresIn"))
        user = self.lookup(session["access_token"], require_verified=False)
        if self._uid(data.get("localId")) != user["uid"]:
            raise FirebaseAuthError(_ERROR_MESSAGES["INVALID_ID_TOKEN"], "INVALID_ID_TOKEN")
        if not allow_unverified and not user["email_verified"]:
            raise EmailNotVerified(session, user)
        return {"user": user, "session": session}

    @staticmethod
    def _email(email):
        if not isinstance(email, str):
            raise FirebaseAuthError(_ERROR_MESSAGES["INVALID_EMAIL"], "INVALID_EMAIL")
        email = email.strip().lower()
        if len(email) > 254 or not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
            raise FirebaseAuthError(_ERROR_MESSAGES["INVALID_EMAIL"], "INVALID_EMAIL")
        return email

    @staticmethod
    def _password(password, *, registering=False):
        if not isinstance(password, str) or not 1 <= len(password) <= 4096:
            raise FirebaseAuthError("Please enter your password.", "INVALID_PASSWORD")
        if registering and len(password) < 8:
            raise FirebaseAuthError(_ERROR_MESSAGES["WEAK_PASSWORD"], "WEAK_PASSWORD")
        return password

    def sign_up(self, name, email, password):
        email = self._email(email)
        password = self._password(password, registering=True)
        if not isinstance(name, str) or not 1 <= len(name.strip()) <= 200 or any(ord(char) < 32 for char in name):
            raise FirebaseAuthError("Please enter a name of up to 200 characters.", "INVALID_NAME")
        name = name.strip()
        data = self._request("signUp", {"email": email, "password": password, "returnSecureToken": True})
        session = self._session(data.get("idToken"), data.get("refreshToken"), data.get("expiresIn"))
        try:
            update = self._request("update", {"idToken": session["access_token"], "displayName": name,
                                               "returnSecureToken": True})
            if "idToken" in update or "refreshToken" in update:
                data = {"localId": update.get("localId", data.get("localId")),
                        "idToken": update.get("idToken", session["access_token"]),
                        "refreshToken": update.get("refreshToken", session["refresh_token"]),
                        "expiresIn": update.get("expiresIn", data.get("expiresIn"))}
            return self._account_result(data, allow_unverified=True)
        except FirebaseAuthError as exc:
            raise FirebaseAuthError(
                "Your account was created, but setup could not finish. Sign in with your email and password to resend the verification link.",
                "ACCOUNT_CREATED_SETUP_INCOMPLETE", exc.status_code,
            ) from None

    def sign_in(self, email, password):
        data = self._request("signInWithPassword", {"email": self._email(email),
                             "password": self._password(password), "returnSecureToken": True})
        return self._account_result(data)

    def send_verification(self, id_token):
        self._id_claims(id_token)
        self._request("sendOobCode", {"requestType": "VERIFY_EMAIL", "idToken": id_token})
        return {"message": "A verification link has been sent. Check your inbox and spam folder."}

    def send_password_reset(self, email):
        try:
            self._request("sendOobCode", {"requestType": "PASSWORD_RESET", "email": self._email(email)})
        except FirebaseAuthError as exc:
                                                                                          
            if exc.code not in {"EMAIL_NOT_FOUND", "USER_NOT_FOUND"}:
                raise
        return {"message": "If an account uses this email, a password reset link has been sent."}

    def refresh(self, refresh_token):
        data = self._request("", {"grant_type": "refresh_token",
                                 "refresh_token": self._refresh_value(refresh_token)}, refresh=True)
        info = self.session_from_tokens(data.get("id_token"), data.get("refresh_token"), data.get("expires_in"))
        if self._uid(data.get("user_id")) != info["user"]["uid"]:
            raise FirebaseAuthError(_ERROR_MESSAGES["INVALID_ID_TOKEN"], "INVALID_ID_TOKEN")
        return info
