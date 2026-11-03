import { initializeApp } from "https://www.gstatic.com/firebasejs/12.4.0/firebase-app.js";
import { getAuth, GoogleAuthProvider, signInWithPopup, setPersistence,
  inMemoryPersistence, signOut } from "https://www.gstatic.com/firebasejs/12.4.0/firebase-auth.js";

const button = document.getElementById("signin");
const status = document.getElementById("status");
const parameters = new URLSearchParams(location.hash.slice(1));
history.replaceState(null, "", location.pathname);
const state = parameters.get("state");
const port = Number(parameters.get("port"));
const publicKeyText = parameters.get("public_key");
const encoder = new TextEncoder();
let auth, publicKey;

function decode(value) {
  const normalized = value.replace(/-/g, "+").replace(/_/g, "/");
  return Uint8Array.from(atob(normalized), c => c.charCodeAt(0));
}
function encode(value) {
  return btoa(String.fromCharCode(...new Uint8Array(value)))
    .replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

async function prepare() {
  if (location.protocol !== "https:" || !/^[A-Za-z0-9_-]{43}$/.test(state || "") ||
      !Number.isInteger(port) || port < 1024 || port > 65535 ||
      !/^[A-Za-z0-9_-]{100,800}$/.test(publicKeyText || "")) {
    throw new Error("INVALID_LAUNCH");
  }
  publicKey = await crypto.subtle.importKey("spki", decode(publicKeyText),
    {name:"RSA-OAEP", hash:"SHA-256"}, false, ["encrypt"]);
  const response = await fetch("/__/firebase/init.json", {cache:"no-store"});
  if (!response.ok) throw new Error("CONFIGURATION");
  const config = await response.json();
  auth = getAuth(initializeApp(config));
  await setPersistence(auth, inMemoryPersistence);
  button.disabled = false;
  status.textContent = "Choose your Google account to continue.";
}

button.addEventListener("click", async () => {
  button.disabled = true;
  status.textContent = "Waiting for Google sign-in…";
  try {
    const provider = new GoogleAuthProvider();
    provider.setCustomParameters({prompt:"select_account"});
    const result = await signInWithPopup(auth, provider);
    if (!result.user.emailVerified ||
        !result.user.providerData.some(provider => provider.providerId === "google.com")) {
      throw new Error("INVALID_PROVIDER");
    }
    const token = await result.user.getIdTokenResult(true);
    const expiresIn = Math.min(3600, Math.floor((Date.parse(token.expirationTime) - Date.now()) / 1000));
    if (expiresIn <= 0) throw new Error("EXPIRED_TOKEN");
    const payload = encoder.encode(JSON.stringify({id_token:token.token,
      refresh_token:result.user.refreshToken, expires_in:expiresIn}));
    const key = await crypto.subtle.generateKey({name:"AES-GCM", length:256}, true, ["encrypt"]);
    const iv = crypto.getRandomValues(new Uint8Array(12));
    const data = await crypto.subtle.encrypt({name:"AES-GCM", iv,
      additionalData:encoder.encode(state)}, key, payload);
    const wrapped = await crypto.subtle.encrypt({name:"RSA-OAEP"}, publicKey,
      await crypto.subtle.exportKey("raw", key));
    await signOut(auth);
    const fragment = new URLSearchParams({state, key:encode(wrapped), iv:encode(iv), data:encode(data)});
    status.textContent = "Returning to OpenStructures…";
    location.replace("http://127.0.0.1:" + port + "/callback#" + fragment.toString());
  } catch (error) {
    const messages = {
      "auth/popup-closed-by-user":"Sign-in was cancelled. You can try again.",
      "auth/popup-blocked":"Your browser blocked the Google window. Allow popups and try again.",
      "auth/account-exists-with-different-credential":"This email already has another sign-in method. Use that method in OpenStructures.",
      "auth/unauthorized-domain":"Google sign-in is not configured for this page yet.",
      "auth/operation-not-allowed":"Google sign-in has not been enabled for this project.",
      "auth/invalid-oauth-client-id":"The Google Web OAuth client needs configuration. Contact OpenStructures support.",
      "auth/invalid-credential":"Google could not validate this sign-in. Please try again; contact support if it keeps happening.",
      "auth/invalid-api-key":"The account service configuration needs correction. Contact OpenStructures support.",
      "auth/network-request-failed":"Check your internet connection and try again."
    };
    status.textContent = messages[error.code] || "Sign-in could not finish. Return to OpenStructures and try again.";
    try { if (auth) await signOut(auth); } catch (_) {}
    button.disabled = false;
  }
});
prepare().catch(() => {
  status.textContent = "Start Google sign-in from OpenStructures. If you already did, the account service needs configuration.";
});
