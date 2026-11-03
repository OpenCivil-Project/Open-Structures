"""Email account actions backed by Firebase, preserving the dialog tuple API."""

from .firebase_client import FirebaseClient, FirebaseAuthError, EmailNotVerified

_client = None

def _get_client():
    global _client
    if _client is None:
        _client = FirebaseClient()
    return _client

def _ok(data=None):
    return True, "", data

def _err(message, data=None):
    return False, message, data

def _user_info(result, *, pending=False):
    info = dict(result["user"])
    info["session"] = dict(result["session"])
    if pending:
        info["pending_verification"] = True
    return info

def register(name, email, password):
    """Create an account and send a verification link, without authenticating it."""
    client = _get_client()
    try:
        result = client.sign_up(name, email, password)
        pending = _user_info(result, pending=True)
        try:
            client.send_verification(result["session"]["access_token"])
        except FirebaseAuthError:
            return _err(
                "Your account was created, but the verification email could not be sent. "
                "Use Resend on the verification screen, or sign in again to resend the link.",
                pending,
            )
        return _ok(pending)
    except FirebaseAuthError as exc:
        return _err(exc.message)

def login(email, password):
    """Only verified Firebase accounts become authenticated desktop sessions."""
    try:
        return _ok(_user_info(_get_client().sign_in(email, password)))
    except EmailNotVerified as exc:
        pending = None
        if exc.user is not None and exc.pending_session is not None:
            pending = _user_info({"user": exc.user, "session": exc.pending_session}, pending=True)
        return _err(exc.message, pending)
    except FirebaseAuthError as exc:
        return _err(exc.message)

def resend_verification(id_token):
    try:
        return _ok(_get_client().send_verification(id_token))
    except FirebaseAuthError as exc:
        return _err(exc.message)

def check_verification(id_token, refresh_token=None):
    """Poll the server; refresh after verification so token claims are current."""
    client = _get_client()
    try:
        user = client.lookup(id_token, require_verified=False)
        if not user["email_verified"]:
            return _err("Please open the verification link in your inbox, then check again.")
        if refresh_token:
            result = client.refresh(refresh_token)
            if result["user"]["uid"] != user["uid"]:
                return _err("This session is no longer valid. Please sign in again.")
            return _ok(_user_info(result))
                                                                                  
        return _err("Your email is verified. Please sign in again to continue.")
    except FirebaseAuthError as exc:
        return _err(exc.message)

def send_forgot_password(email):
    try:
        return _ok(_get_client().send_password_reset(email))
    except FirebaseAuthError as exc:
        return _err(exc.message)
