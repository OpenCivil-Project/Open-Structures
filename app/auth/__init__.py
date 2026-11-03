"""Desktop authentication. Database and email administration stay off the client.

Keep GUI imports lazy so configuration and account clients can also be used by
non-GUI tools and tests without starting Qt.
"""

from importlib import import_module

_EXPORTS = {
    "GoogleAuthManager": (".manager", "GoogleAuthManager"),
    "LoginDialog": (".dialog", "LoginDialog"),
    "GoogleAuthConfig": (".config", "GoogleAuthConfig"),
    "FirebaseAuthConfig": (".config", "FirebaseAuthConfig"),
    "UserProfileWidget": (".user_widget", "UserProfileWidget"),
}
__all__ = [*_EXPORTS, "email_auth"]

def __getattr__(name):
    if name == "email_auth":
        value = import_module(".email_auth", __name__)
    elif name in _EXPORTS:
        module, attribute = _EXPORTS[name]
        value = getattr(import_module(module, __name__), attribute)
    else:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    globals()[name] = value
    return value
