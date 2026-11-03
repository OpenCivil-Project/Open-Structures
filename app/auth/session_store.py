"""User-scoped storage for remembered desktop sessions.

Account tokens are encrypted by Windows DPAPI, using the current user's key.
Platforms without this store can remember guest mode, but never account tokens.
"""

import ctypes
import json
import os
from pathlib import Path
import tempfile

_PROTECTED_MAGIC = b"OCSESSION\x01"
_GUEST_MAGIC = b"OCGUEST\x01"
_ENTROPY = b"OpenCivil remembered session v1"
_MAX_FILE_BYTES = 128 * 1024

class SessionStoreError(Exception):
    """The session could not be safely stored or read."""

def _dpapi(data: bytes, *, decrypt: bool = False) -> bytes:
    if os.name != "nt":
        raise SessionStoreError("Secure account storage requires Windows DPAPI.")
    from ctypes import wintypes

    class DataBlob(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_ubyte))]

    def make_blob(value):
        buffer = ctypes.create_string_buffer(value)
        blob = DataBlob(len(value), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
        return blob, buffer

    input_blob, input_buffer = make_blob(data)
    entropy_blob, entropy_buffer = make_blob(_ENTROPY)
    output_blob = DataBlob()
    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p
    operation = crypt32.CryptUnprotectData if decrypt else crypt32.CryptProtectData
    operation.argtypes = [
        ctypes.POINTER(DataBlob), ctypes.c_void_p if decrypt else wintypes.LPCWSTR,
        ctypes.POINTER(DataBlob), ctypes.c_void_p, ctypes.c_void_p,
        wintypes.DWORD, ctypes.POINTER(DataBlob),
    ]
    operation.restype = wintypes.BOOL
    success = operation(
        ctypes.byref(input_blob), None if decrypt else "OpenStructures remembered session",
        ctypes.byref(entropy_blob), None, None,
        0x01,                                                              
        ctypes.byref(output_blob),
    )
    try:
        if not success:
            raise SessionStoreError("Windows could not protect or unlock this session.")
        return ctypes.string_at(output_blob.pbData, output_blob.cbData)
    finally:
        if output_blob.pbData:
            kernel32.LocalFree(ctypes.cast(output_blob.pbData, ctypes.c_void_p))

def _restrict_file(path: Path) -> None:
    """Grant file access only to its owner and Windows SYSTEM."""
    if os.name != "nt":
        os.chmod(path, 0o600)
        return
    from ctypes import wintypes
    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    descriptor = ctypes.c_void_p()
    convert = advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW
    convert.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p]
    convert.restype = wintypes.BOOL
    set_security = advapi32.SetFileSecurityW
    set_security.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, ctypes.c_void_p]
    set_security.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p
    if not convert("D:P(A;;FA;;;SY)(A;;FA;;;OW)", 1, ctypes.byref(descriptor), None):
        raise SessionStoreError("Windows could not restrict session file access.")
    try:
        if not set_security(str(path), 0x80000004, descriptor):
            raise SessionStoreError("Windows could not restrict session file access.")
    finally:
        kernel32.LocalFree(descriptor)

class SessionStore:
    def __init__(self, path):
        self.path = Path(path)

    def save(self, payload: dict) -> None:
        if not isinstance(payload, dict):
            raise SessionStoreError("Invalid session data.")
        try:
            raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        except (TypeError, ValueError) as exc:
            raise SessionStoreError("Invalid session data.") from exc
        if len(raw) > _MAX_FILE_BYTES // 2:
            raise SessionStoreError("Session data is too large.")
        if os.name == "nt":
            encoded = _PROTECTED_MAGIC + _dpapi(raw)
        else:
            user = payload.get("user_info")
            if (not isinstance(user, dict) or user.get("provider") != "guest"
                    or payload.get("session") or payload.get("credentials")):
                raise SessionStoreError("Secure account storage is unavailable on this platform.")
                                                                               
            guest_payload = {
                "version": 1, "remember_me": True,
                "user_info": {"name": "Guest", "email": "", "picture": "", "provider": "guest"},
            }
            encoded = _GUEST_MAGIC + json.dumps(guest_payload).encode("utf-8")
        temporary_path = None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            fd, filename = tempfile.mkstemp(prefix=".session-", suffix=".tmp", dir=self.path.parent)
            temporary_path = Path(filename)
            with os.fdopen(fd, "wb") as stream:
                stream.write(encoded)
                stream.flush()
                os.fsync(stream.fileno())
            _restrict_file(temporary_path)
            os.replace(temporary_path, self.path)
        except (OSError, SessionStoreError) as exc:
            raise SessionStoreError("The remembered session could not be saved securely.") from exc
        finally:
            if temporary_path is not None:
                try:
                    temporary_path.unlink(missing_ok=True)
                except OSError:
                                                                             
                    pass

    def load(self):
        if not self.path.exists():
            return None
        try:
            with self.path.open("rb") as stream:
                encoded = stream.read(_MAX_FILE_BYTES + 1)
            if len(encoded) > _MAX_FILE_BYTES:
                raise SessionStoreError("Session file is too large.")
            if encoded.startswith(_PROTECTED_MAGIC):
                raw = _dpapi(encoded[len(_PROTECTED_MAGIC):], decrypt=True)
            elif encoded.startswith(_GUEST_MAGIC):
                raw = encoded[len(_GUEST_MAGIC):]
            else:
                raise SessionStoreError("Unrecognized session file.")
            payload = json.loads(raw.decode("utf-8"))
            if not isinstance(payload, dict):
                raise SessionStoreError("Invalid remembered session.")
            if encoded.startswith(_GUEST_MAGIC):
                user = payload.get("user_info")
                if (not isinstance(user, dict) or user.get("provider") != "guest"
                        or payload.get("session") or payload.get("credentials")):
                    raise SessionStoreError("Guest metadata cannot contain account credentials.")
            return payload
        except (OSError, ValueError, UnicodeError) as exc:
            raise SessionStoreError("The remembered session could not be read.") from exc

    def remove(self) -> None:
        try:
            self.path.unlink(missing_ok=True)
        except OSError as exc:
            raise SessionStoreError("The remembered session could not be removed.") from exc
