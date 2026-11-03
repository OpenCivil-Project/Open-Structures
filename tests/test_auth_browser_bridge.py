"""Security and lifecycle checks for the desktop/browser handoff."""
import base64
import copy
import http.client
import json
from pathlib import Path
import shutil
import subprocess
import threading
import unittest
from urllib.parse import parse_qs, urlsplit

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.auth.browser_bridge import BrowserSignInBridge, BrowserSignInError, _encode

def envelope(bridge, result=None):
    result = result or {"id_token": "fake-firebase-token", "refresh_token": "fake-refresh-token",
                        "expires_in": 3600}
    key = AESGCM.generate_key(bit_length=256)
    iv = bytes(range(12))
    wrapped = bridge._private_key.public_key().encrypt(key, padding.OAEP(
        mgf=padding.MGF1(hashes.SHA256()), algorithm=hashes.SHA256(), label=None))
    data = AESGCM(key).encrypt(iv, json.dumps(result).encode(), bridge.state.encode())
    return {"state": bridge.state, "key": _encode(wrapped), "iv": _encode(iv), "data": _encode(data)}

class BridgeTests(unittest.TestCase):
    def test_roundtrip_and_single_use(self):
        bridge = BrowserSignInBridge()
        data = envelope(bridge)
        bridge.accept(data)
        self.assertEqual(bridge._result["refresh_token"], "fake-refresh-token")
        with self.assertRaises(BrowserSignInError):
            bridge.accept(data)

    def test_tamper_state_key_data_and_expiry(self):
        for field in ("state", "key", "data"):
            with self.subTest(field=field):
                bridge = BrowserSignInBridge()
                data = envelope(bridge)
                data[field] = "A" + data[field][1:] if data[field][0] != "A" else "B" + data[field][1:]
                with self.assertRaises(BrowserSignInError):
                    bridge.accept(data)
        bridge = BrowserSignInBridge()
        with self.assertRaises(BrowserSignInError):
            bridge.accept(envelope(bridge, {"id_token":"id", "refresh_token":"refresh", "expires_in":0}))

    def test_another_process_key_cannot_decrypt(self):
        source, target = BrowserSignInBridge(), BrowserSignInBridge()
        target.state = source.state
        with self.assertRaises(BrowserSignInError):
            target.accept(envelope(source))

    def test_cancel_timeout_and_loopback_binding(self):
        with BrowserSignInBridge() as bridge:
            self.assertEqual(bridge._server.server_address[0], "127.0.0.1")
            cancel = threading.Event()
            cancel.set()
            with self.assertRaisesRegex(BrowserSignInError, "cancelled"):
                bridge.wait(cancel)
            with self.assertRaisesRegex(BrowserSignInError, "timed out"):
                bridge.wait(threading.Event(), timeout=0)

    def test_browser_url_contains_only_public_challenge(self):
        with BrowserSignInBridge() as bridge:
            url = bridge.browser_url("https://sample-project.web.app/google-sign-in.html")
            parameters = parse_qs(urlsplit(url).fragment)
            self.assertEqual(set(parameters), {"state", "port", "public_key"})
            self.assertNotIn("private", url)
            for invalid in ("http://example.com/", "https://user:password@example.com/",
                            "https://example.com/?redirect=bad"):
                with self.assertRaises(BrowserSignInError):
                    bridge.browser_url(invalid)

    def test_http_callback_rejects_cross_origin_then_accepts_local(self):
        with BrowserSignInBridge() as bridge:
            cancel = threading.Event()
            results = []
            worker = threading.Thread(target=lambda: results.append(bridge.wait(cancel, timeout=5)))
            worker.start()
            connection = http.client.HTTPConnection("127.0.0.1", bridge.port, timeout=3)
            payload = json.dumps(envelope(bridge))
            connection.request("POST", "/complete", payload,
                               {"Content-Type":"application/json", "Origin":"https://evil.example"})
            response = connection.getresponse()
            self.assertEqual(response.status, 403)
            response.read()
            connection.close()
            connection = http.client.HTTPConnection("127.0.0.1", bridge.port, timeout=3)
            connection.request("GET", "/callback")
            response = connection.getresponse()
            page = response.read().decode()
            self.assertIn("history.replaceState", page)
            self.assertIn("sha256-", response.getheader("Content-Security-Policy"))
            self.assertEqual(response.getheader("Cache-Control"), "no-store")
            connection.close()
            connection = http.client.HTTPConnection("127.0.0.1", bridge.port, timeout=3)
            connection.request("POST", "/complete", payload,
                               {"Content-Type":"application/json",
                                "Origin":f"http://127.0.0.1:{bridge.port}"})
            response = connection.getresponse()
            self.assertEqual(response.status, 200)
            self.assertNotIn("fake-refresh-token", response.read().decode())
            connection.close()
            worker.join(5)
            self.assertFalse(worker.is_alive())
            self.assertEqual(results[0]["id_token"], "fake-firebase-token")

    @unittest.skipUnless(shutil.which("node"), "Node.js is needed to check WebCrypto interoperability")
    def test_browser_webcrypto_matches_python_decryption(self):
        with BrowserSignInBridge() as bridge:
            public_key = parse_qs(urlsplit(bridge.browser_url("https://sample-project.web.app/google-sign-in.html")).fragment)["public_key"][0]
            script = """
const {webcrypto} = require('node:crypto');
(async () => {
const crypto = webcrypto, state=process.argv[2];
const publicKey=await crypto.subtle.importKey('spki',Buffer.from(process.argv[1],'base64url'),
{name:'RSA-OAEP',hash:'SHA-256'},false,['encrypt']);
const key=await crypto.subtle.generateKey({name:'AES-GCM',length:256},true,['encrypt']);
const iv=crypto.getRandomValues(new Uint8Array(12));
const data=await crypto.subtle.encrypt({name:'AES-GCM',iv,additionalData:Buffer.from(state)},key,
Buffer.from(JSON.stringify({id_token:'fake-firebase-token',refresh_token:'fake-refresh-token',expires_in:3600})));
const wrapped=await crypto.subtle.encrypt({name:'RSA-OAEP'},publicKey,await crypto.subtle.exportKey('raw',key));
console.log(JSON.stringify({state,key:Buffer.from(wrapped).toString('base64url'),
iv:Buffer.from(iv).toString('base64url'),data:Buffer.from(data).toString('base64url')}));
})().catch(()=>process.exit(1));
"""
            result = subprocess.run(["node", "-e", script, public_key, bridge.state],
                                    check=True, capture_output=True, text=True, timeout=10)
            bridge.accept(json.loads(result.stdout))
            self.assertEqual(bridge._result["expires_in"], 3600)

    def test_hosting_csp_allows_firebase_google_popup_loader(self):
        root = Path(__file__).resolve().parents[1]
        headers = json.loads((root / "auth_web/firebase.json").read_text())["hosting"]["headers"][0]["headers"]
        csp = next(item["value"] for item in headers if item["key"] == "Content-Security-Policy")
        self.assertIn("https://apis.google.com", csp)
        self.assertIn("frame-ancestors 'none'", csp)

if __name__ == "__main__":
    unittest.main()
