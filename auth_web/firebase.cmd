@echo off
setlocal
rem Operator-only launcher; this file is not part of the desktop release or Hosting public directory.
rem MSIX apps can redirect npm's Roaming installation into their private LocalCache.
set "OPENCIVIL_FIREBASE_CLI=%LOCALAPPDATA%\Packages\OpenAI.Codex_2p2nqsd0c76g0\LocalCache\Roaming\npm\firebase.cmd"
if not exist "%OPENCIVIL_FIREBASE_CLI%" set "OPENCIVIL_FIREBASE_CLI=%APPDATA%\npm\firebase.cmd"
if not exist "%OPENCIVIL_FIREBASE_CLI%" (
  echo Firebase CLI was not found. Run npm.cmd install -g firebase-tools in your own PowerShell.
  exit /b 1
)
call "%OPENCIVIL_FIREBASE_CLI%" %*
exit /b %errorlevel%
