"""One-use encrypted browser callback for Firebase Google sign-in.

Only ciphertext crosses browser URL fragments. The private key stays in the
desktop process; callback requests are local, same-origin, and never logged.
"""
import base64
import hashlib
import hmac
import json
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlencode, urlsplit

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

class BrowserSignInError(Exception):
    pass

def _encode(value):
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")

def _decode(value, max_size):
    if not isinstance(value, str) or not value or len(value) > max_size * 2:
        raise BrowserSignInError("Invalid sign-in response.")
    try:
        result = base64.b64decode(value + "=" * (-len(value) % 4),
                                  altchars=b"-_", validate=True)
    except (ValueError, TypeError) as exc:
        raise BrowserSignInError("Invalid sign-in response.") from exc
    if len(result) > max_size:
        raise BrowserSignInError("Invalid sign-in response.")
    return result

_CALLBACK_SCRIPT = """const payload = Object.fromEntries(new URLSearchParams(location.hash.slice(1)));
history.replaceState(null, '', '/callback');
fetch('/complete', {method:'POST', headers:{'Content-Type':'application/json'},
body:JSON.stringify(payload), credentials:'same-origin'}).then(async response => {
document.getElementById('message').textContent = await response.text();
}).catch(() => { document.getElementById('message').textContent =
'Return to OpenStructures and try sign-in again.'; });"""
_SCRIPT_HASH = base64.b64encode(hashlib.sha256(_CALLBACK_SCRIPT.encode()).digest()).decode()
_CALLBACK_HTML = ("<!doctype html><html><head><meta charset='utf-8'>"
                  "<meta name='referrer' content='no-referrer'>"
                  "<title>OpenStructures sign-in</title></head><body>"
                  "<h1>OpenStructures</h1><p id='message'>Completing sign-in…</p>"
                  "<script>" + _CALLBACK_SCRIPT + "</script></body></html>").encode()

class BrowserSignInBridge:
    def __init__(self):
        self.state = secrets.token_urlsafe(32)
        self._private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self._result = None
        self._complete = threading.Event()
        self._server = None

    def __enter__(self):
        bridge = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args):
                pass

            def _reply(self, status, body, content_type="text/plain; charset=utf-8"):
                body = body.encode() if isinstance(body, str) else body
                self.send_response(status)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("Referrer-Policy", "no-referrer")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.send_header("Content-Security-Policy", "default-src 'none'; "
                                 f"script-src 'sha256-{_SCRIPT_HASH}'; "
                                 "connect-src 'self'; base-uri 'none'; "
                                 "form-action 'none'; frame-ancestors 'none'")
                self.end_headers()
                self.wfile.write(body)

            def _valid_host(self):
                return self.headers.get("Host") == f"127.0.0.1:{bridge.port}"

            def do_GET(self):
                if not self._valid_host() or self.path != "/callback":
                    self._reply(404, "Not found.")
                    return
                self._reply(200, _CALLBACK_HTML, "text/html; charset=utf-8")

            def do_POST(self):
                expected_origin = f"http://127.0.0.1:{bridge.port}"
                if (not self._valid_host() or self.path != "/complete" or
                        self.headers.get("Origin") != expected_origin or
                        self.headers.get("Content-Type", "").split(";")[0] != "application/json"):
                    self._reply(403, "Sign-in response rejected.")
                    return
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                    if not 0 < length <= 32768:
                        raise ValueError("Invalid size")
                    payload = json.loads(self.rfile.read(length))
                    bridge.accept(payload)
                except (ValueError, TypeError, BrowserSignInError):
                    self._reply(400, "Sign-in response rejected. Return to OpenStructures.")
                    return
                self._reply(200, "Sign-in received. Return to OpenStructures; you can close this tab.")

        class LocalServer(HTTPServer):
            def get_request(self):
                connection, address = super().get_request()
                connection.settimeout(2)
                return connection, address

            def handle_error(self, *_args):
                pass

        self._server = LocalServer(("127.0.0.1", 0), Handler)
        self._server.timeout = 0.2
        return self

    @property
    def port(self):
        if self._server is None:
            raise BrowserSignInError("Sign-in listener is not running.")
        return self._server.server_address[1]

    def browser_url(self, helper_url):
        parsed = urlsplit(helper_url)
        if (parsed.scheme != "https" or not parsed.hostname or parsed.username or
                parsed.password or parsed.query or parsed.fragment):
            raise BrowserSignInError("Google sign-in page is not configured correctly.")
        public_key = self._private_key.public_key().public_bytes(
            serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
        fragment = urlencode({"state": self.state, "port": self.port,
                              "public_key": _encode(public_key)})
        return helper_url + "#" + fragment

    def accept(self, payload):
        if self._complete.is_set() or not isinstance(payload, dict):
            raise BrowserSignInError("Sign-in response already used or invalid.")
        if not isinstance(payload.get("state"), str) or not hmac.compare_digest(payload["state"], self.state):
            raise BrowserSignInError("Sign-in response rejected.")
        try:
            wrapped_key = _decode(payload.get("key"), 256)
            iv = _decode(payload.get("iv"), 12)
            ciphertext = _decode(payload.get("data"), 16384)
            if len(wrapped_key) != 256 or len(iv) != 12:
                raise ValueError("Invalid encryption envelope")
            key = self._private_key.decrypt(wrapped_key, padding.OAEP(
                mgf=padding.MGF1(hashes.SHA256()), algorithm=hashes.SHA256(), label=None))
            if len(key) != 32:
                raise ValueError("Invalid key")
            result = json.loads(AESGCM(key).decrypt(iv, ciphertext, self.state.encode()))
            if not isinstance(result, dict):
                raise ValueError("Invalid response")
            for field in ("id_token", "refresh_token"):
                value = result.get(field)
                if not isinstance(value, str) or not 1 <= len(value) <= 12000:
                    raise ValueError("Invalid token")
            expires = int(result.get("expires_in", 0))
            if not 0 < expires <= 3600:
                raise ValueError("Invalid expiry")
            result = {"id_token": result["id_token"], "refresh_token": result["refresh_token"],
                      "expires_in": expires}
        except Exception as exc:
            raise BrowserSignInError("Sign-in response could not be validated.") from exc
        self._result = result
        self._complete.set()

    def wait(self, cancelled, timeout=180):
        deadline = time.monotonic() + timeout
        while not self._complete.is_set():
            if cancelled.is_set():
                raise BrowserSignInError("cancelled")
            if time.monotonic() >= deadline:
                raise BrowserSignInError("Sign-in timed out. Please try again.")
            self._server.handle_request()
        if cancelled.is_set():
            raise BrowserSignInError("cancelled")
        return self._result

    def __exit__(self, *_args):
        if self._server is not None:
            self._server.server_close()
            self._server = None
        self._result = None
        self._private_key = None
