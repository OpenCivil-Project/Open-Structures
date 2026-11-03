"""Security checks for session storage; no application import or network use."""

import importlib.util
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

_SOURCE = Path(__file__).resolve().parents[1] / "app" / "auth" / "session_store.py"
_SPEC = importlib.util.spec_from_file_location("opencivil_session_store_test", _SOURCE)
store_module = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(store_module)

class SessionStoreTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "session.dat"
        self.store = store_module.SessionStore(self.path)
        self.guest = {
            "version": 1, "remember_me": True,
            "user_info": {"name": "Guest", "provider": "guest", "email": "", "picture": ""},
        }
        self.account = {
            "version": 1, "remember_me": True,
            "user_info": {"uid": "test-user", "provider": "email", "email": "test@example.invalid"},
            "session": {"access_token": "test-access-token", "refresh_token": "test-refresh-token"},
        }

    @unittest.skipUnless(os.name == "nt", "Windows DPAPI check")
    def test_windows_account_roundtrip_is_encrypted_and_owner_only(self):
        self.store.save(self.account)
        encoded = self.path.read_bytes()
        self.assertTrue(encoded.startswith(store_module._PROTECTED_MAGIC))
        self.assertNotIn(b"test-access-token", encoded)
        self.assertNotIn(b"test-refresh-token", encoded)
        self.assertEqual(self.store.load(), self.account)
                                                                               
        import ctypes
        from ctypes import wintypes
        advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        size = wintypes.DWORD()
        get_security = advapi32.GetFileSecurityW
        get_security.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, ctypes.c_void_p,
                                 wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
        get_security.restype = wintypes.BOOL
        get_security(str(self.path), 4, None, 0, ctypes.byref(size))
        descriptor = ctypes.create_string_buffer(size.value)
        self.assertTrue(get_security(str(self.path), 4, descriptor, size.value, ctypes.byref(size)))
        as_sddl = advapi32.ConvertSecurityDescriptorToStringSecurityDescriptorW
        as_sddl.argtypes = [ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD,
                            ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p]
        as_sddl.restype = wintypes.BOOL
        text_pointer = ctypes.c_void_p()
        self.assertTrue(as_sddl(descriptor, 1, 4, ctypes.byref(text_pointer), None))
        try:
            sddl = ctypes.wstring_at(text_pointer)
            self.assertIn(";;;SY)", sddl)
            self.assertIn(";;;OW)", sddl)
            self.assertNotIn(";;;WD)", sddl)
            self.assertNotIn(";;;BU)", sddl)
        finally:
            kernel32.LocalFree.argtypes = [ctypes.c_void_p]
            kernel32.LocalFree.restype = ctypes.c_void_p
            kernel32.LocalFree(text_pointer)

    @unittest.skipUnless(os.name == "nt", "Windows DPAPI check")
    def test_windows_modified_ciphertext_cannot_restore(self):
        self.store.save(self.account)
        encoded = bytearray(self.path.read_bytes())
        encoded[-1] ^= 1
        self.path.write_bytes(encoded)
        with self.assertRaises(store_module.SessionStoreError):
            self.store.load()

    def test_guest_roundtrip(self):
        self.store.save(self.guest)
        self.assertEqual(self.store.load()["user_info"]["provider"], "guest")
        self.store.remove()
        self.assertIsNone(self.store.load())

    def test_plaintext_account_json_cannot_restore(self):
        self.path.write_text(json.dumps(self.account), encoding="utf-8")
        with self.assertRaises(store_module.SessionStoreError):
            self.store.load()

    def test_guest_file_cannot_smuggle_account_tokens(self):
        value = dict(self.guest, session={"refresh_token": "fake-token"})
        self.path.write_bytes(store_module._GUEST_MAGIC + json.dumps(value).encode())
        with self.assertRaises(store_module.SessionStoreError):
            self.store.load()

    def test_unwritable_store_directory_reports_safe_storage_error(self):
        blocked = self.path.parent / "not-a-directory"
        blocked.write_text("test", encoding="utf-8")
        store = store_module.SessionStore(blocked / "session.dat")
        with self.assertRaises(store_module.SessionStoreError):
            store.save(self.guest)

    def test_crypto_failure_never_writes_plaintext(self):
        if os.name != "nt":
            self.skipTest("Windows path needed to exercise DPAPI failure")
        with patch.object(store_module, "_dpapi", side_effect=store_module.SessionStoreError("unavailable")):
            with self.assertRaises(store_module.SessionStoreError):
                self.store.save(self.account)
        self.assertFalse(self.path.exists())
        self.assertEqual(list(self.path.parent.glob(".session-*.tmp")), [])

    def test_without_windows_accounts_are_not_persisted(self):
        platform = SimpleNamespace(
            name="posix", chmod=os.chmod, fdopen=os.fdopen, fsync=os.fsync, replace=os.replace,
        )
        with patch.object(store_module, "os", platform):
            with self.assertRaises(store_module.SessionStoreError):
                self.store.save(self.account)
            self.store.save(dict(self.guest, arbitrary_secret="must-not-persist"))
        encoded = self.path.read_bytes()
        self.assertNotIn(b"must-not-persist", encoded)
        self.assertEqual(self.store.load()["user_info"]["provider"], "guest")

if __name__ == "__main__":
    unittest.main()
