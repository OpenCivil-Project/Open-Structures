# Firebase accounts and desktop releases

OpenStructures continues to model, analyse and run as a guest without internet.
Firebase Authentication supplies account registration, sign-in, verification and
password reset. The desktop no longer needs MongoDB or SMTP credentials, a
Google desktop client secret, or an encrypted shared-secret bundle. Firebase
manages the online account service; no custom Python server is required.

This source change does not create a Firebase project, deploy Hosting, migrate
accounts, rotate credentials or publish a desktop release.

## 1. Configure the Firebase project

### Preserve an already verified Google sign-in brand

An existing verified Google OAuth project can supply the Google Web OAuth
client for the current Firebase project. This avoids moving Firebase accounts
just to reuse existing published branding. A GitHub Pages homepage or privacy
policy is separate from the Google OAuth client registration.

For this installation, the verified Cloud project is `opencivil`
(`250654468779`), while Firebase accounts are in `openstructures-b3f46`.
The provider repair was applied and tested interactively on 2026-11-01 using
Web client `250654468779-nnui7r5l2m33apb6o87oru6m4vga5k3s.apps.googleusercontent.com`.
The original published OpenCivil name and logo are in use. Reusing that
published brand is independent of the new Firebase project's branding review.
The existing `opencivil` Desktop OAuth client cannot replace Firebase's Web
OAuth client. Create or reuse a **Web application** client in `opencivil`.
Keep the existing published Branding, Audience, and scope settings in place.

Set these authorized JavaScript origins on the Web client:

```
https://openstructures-b3f46.web.app
https://openstructures-b3f46.firebaseapp.com
```

Set this exact authorized redirect URI:

```
https://openstructures-b3f46.firebaseapp.com/__/auth/handler
```

Download the Web client's JSON outside the repository. Its client secret is
an operator credential and belongs only in Firebase's server-side Google
provider configuration. Never put it in `auth_config.json`, source code,
Hosting public files, or a desktop release.

The operator repair tool defaults to a preview and rejects Desktop clients,
clients from a different project, and a missing callback URI:

```powershell
node tools/reuse_verified_google_provider.cjs --check
node tools/reuse_verified_google_provider.cjs --credentials "C:\path\web-oauth.json"
```

After reviewing the preview, apply with a new absolute rollback-file path
outside the repository:

```powershell
node tools/reuse_verified_google_provider.cjs --credentials "C:\path\web-oauth.json" --apply --backup "C:\path\provider-rollback.dpapi"
```

The backup is encrypted for the current Windows account with DPAPI and its
file permissions are restricted. The tool verifies the server configuration
after updating it and restores the previous configuration if verification
fails and the provider is still the one it changed. It does not move users,
alter email/password sign-in, or change application session settings.

Then test Google sign-in from the desktop in a real system browser. Branding
and provider changes can propagate; a successful configuration readback is
not proof of a completed interactive sign-in. Rollback, if necessary:

```powershell
node tools/reuse_verified_google_provider.cjs --rollback "C:\path\provider-rollback.dpapi" --apply
```

1. Create or select a project in the [Firebase Console](https://console.firebase.google.com/).
   A Spark project can be used initially, subject to Firebase's current quotas
   and provider availability. SMS/phone authentication is not used here.
2. Open **Authentication > Sign-in method** and enable **Email/Password** and
   **Google**. Set the Google provider's project support email. No existing
   installed-app Google OAuth secret is copied into the desktop.
3. Register a **Web app** in Project settings. Its Firebase `apiKey`, `projectId`
   and `authDomain` are public client settings; they are not Admin credentials.
4. In Authentication settings, confirm the Hosting domain is authorized. Edit
   the verification and password-reset email templates, sender display name
   and action URL as needed. The action URL must be an authorized domain.
5. Enable Firebase email enumeration protection where available, and review
   authentication quotas and abuse controls. The desktop does not bypass
   Firebase's verification or provider checks.

The web API key must allow the Firebase Authentication APIs used by the app:
Identity Toolkit (`identitytoolkit.googleapis.com`) and Secure Token
(`securetoken.googleapis.com`). Preserve additional Firebase API restrictions
needed by Hosting/web sign-in. HTTP-referrer-only restrictions can break the
desktop's REST calls, because they are not browser requests. Use a separate key
if different clients need different restrictions. API key secrecy is not an
authorization boundary; Firebase ID tokens and security rules are.

No Firestore or Storage access is added by this account change. If those products
are enabled later, configure rules that enforce each signed-in user's access;
do not use an allow-all rule because the client API key is public.

## 2. Add public desktop configuration

Copy `app/resources/auth_config.example.json` to
`app/resources/auth_config.json`, replacing every placeholder:

```json
{
  "api_key": "YOUR_FIREBASE_WEB_API_KEY",
  "project_id": "YOUR_FIREBASE_PROJECT_ID",
  "auth_domain": "YOUR_FIREBASE_PROJECT_ID.firebaseapp.com",
  "google_sign_in_url": "https://YOUR_FIREBASE_PROJECT_ID.web.app/google-sign-in.html"
}
```

The local file is ignored by Git but deliberately included by the desktop spec.
It must contain only these four public fields. No `.env`, Mongo URI, mail
password, Admin private key or service-account JSON belongs in this file.
The corresponding `OPENCIVIL_FIREBASE_*` environment overrides may be used for
development; see `app/auth/config.py` for their exact names.

Without configured account services, guest mode remains available. Existing
local projects and offline solvers do not need a Firebase account. A cached
offline profile is local convenience, not authorization for an online service.

## 3. Host the Google sign-in helper

The desktop opens the system browser to the small static page in `auth_web`.
Firebase performs Google sign-in there. The helper obtains public project
configuration from Firebase Hosting's reserved `/__/firebase/init.json`
endpoint; Admin credentials are never put into JavaScript.

Install the Firebase CLI as an operator tool, sign in to the intended project,
and deploy only the static Hosting site:

```powershell
npm.cmd install -g firebase-tools
# Use the installed file directly so a missing/stale PATH does not block setup.
$firebaseCli = Join-Path (npm.cmd prefix -g) 'firebase.cmd'
& $firebaseCli --version
& $firebaseCli login
Set-Location auth_web
& $firebaseCli deploy --only hosting --project YOUR_FIREBASE_PROJECT_ID
```

Run these from the repository root. The Hosting files are already prepared;
`firebase init` is not needed and can replace the existing configuration.

On Windows, `auth_web/firebase.cmd` is also an operator-only launcher. It finds
the normal npm installation or the physical Codex MSIX cache when Windows has
redirected an installation made from Codex. From `auth_web`, use:

```powershell
.\firebase.cmd login
.\firebase.cmd deploy --only hosting --project YOUR_FIREBASE_PROJECT_ID
```

The launcher is outside Hosting's `public` folder and is never bundled with the
desktop application.

Set `google_sign_in_url` to the resulting HTTPS
`/google-sign-in.html` URL. The helper's desktop return flow uses a random state
value and encrypted data delivered to a local loopback callback. Keep its CSP
and callback validation in place. Test Google sign-in in a real system browser
before distributing the configured release. This command does not deploy a
Python backend, MongoDB or an email server.

## 4. Import existing accounts, if needed

The operator-only `tools/migrate_firebase_users.py` reads the existing MongoDB
collection and can import compatible users into Firebase. It never updates
MongoDB. Its default mode only previews aggregate counts and makes no Firebase
writes. Do not bundle the script, its dependencies or Admin credentials.

Use a separate operator environment with `tools/migration-requirements.txt`.
Provide the source URI through an environment variable, not a command-line URI
or checked-in file. A read-only MongoDB account is sufficient. Store Firebase
Admin JSON outside this repository, or use authorized Application Default
Credentials. Do not place Admin JSON under `app`, `auth_web` or `dist`.

```powershell
# Set MONGO_URI securely in this operator session; its value is not shown here.
python tools/migrate_firebase_users.py

# Only after reviewing the aggregate preview and checking the destination:
python tools/migrate_firebase_users.py --apply `
  --firebase-project-id YOUR_FIREBASE_PROJECT_ID `
  --admin-key-file C:\Secure\firebase-admin.json
```

Before applying, take an operator-controlled backup and review the destination
project. Pause account creation/import activity during the import to avoid
concurrent identity collisions. Admin import is privileged and not a
transactional migration; review aggregate results after each run. The script
checks existing Firebase UID, email and Google provider identities and skips
collisions. Failed imports are counted without printing individual users,
password hashes, tokens or SDK exceptions that could expose source details.

Existing email/password users keep the string form of Mongo `_id` as Firebase
UID. Bcrypt password hashes are imported using Firebase's bcrypt import mode;
the `verified` flag maps to `email_verified`. Passwords are not decrypted or
requested. Test one representative migrated account before a broad rollout.

Google accounts are imported as linked Google identities only if the source
contains a trusted `google_sub` or `google_subject`. An email address alone does
not prove the Google subject. Records without that subject are skipped and
counted. Users can sign in through Firebase Google after setup, but an existing
email/password account with the same email may require explicit provider
linking/account recovery; do not silently merge accounts by email.

## 5. Build and review the desktop package

Use the PowerShell recipe in `installer.txt` and the maintained
`OpenStructures.spec`. The recipe uses one interpreter for dependency install,
editable development install and PyInstaller. A new build environment avoids
destroying an existing development environment.

The current `requirements.txt` has not been validated as a Python 3.13 build
lock: NumPy 1.26.4 does not support Python 3.13, and the newer scientific pins
may conflict with that NumPy version. Resolve and test one compatible set,
record the successful versions, and run `python -m pip check` before building.
This authentication change does not silently alter scientific dependencies.

The spec keeps the existing `onedir` distribution, Qt/scientific dependencies,
graphics and solver subprocess mode. It explicitly includes public assets and
optional public Firebase settings. It excludes legacy database/email modules,
secret bundles, Firebase Admin, operator tools, `.env` files and copied auth
source directories. It does not claim code encryption.

Check the release folder and PyInstaller archive for unexpected credentials or
operator files. On clean Windows without Python installed, test guest startup
while disconnected, model loading, 3D graphics, each supported analysis mode,
results/export, email sign-in, verification/reset, Google sign-in, logout and
remembered/offline sessions. Account actions may report unavailable internet;
local analysis must continue.

Compile `OpenStructures_Setup.iss` after the desktop build. It uses relative
paths, a modern per-user installer, an optional desktop shortcut and an
in-place replacement of the managed `_internal` runtime and legacy copied auth
directories to remove stale bundle files. The complete `dist/OpenStructures`
folder is also usable; its executable
alone is not a complete installation. Sign the executable/installer when an
actual code-signing certificate is available; no signature is fabricated here.

## 6. Retire distributed shared credentials

Publish and validate the compatible Firebase release and complete any needed
account migration before retiring the old direct-database account path. Then
rotate/revoke the old bundled MongoDB and email credentials and restrict the
old database account. Existing distributed bundles should be treated as able
to reveal those credentials. Rotation is an operator action; this change does
not perform it automatically or delete the source database.

Guest mode and local structural analysis remain independent of that transition.
