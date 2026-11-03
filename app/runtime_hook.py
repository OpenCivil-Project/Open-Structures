"""Frozen resource/import paths only; authentication secrets are never bundled.

Firebase public configuration is read by app.auth.config. The desktop does not
load .env files, decrypt credential bundles, or receive database/SMTP passwords.
"""

from pathlib import Path
import sys

if getattr(sys, "frozen", False):
    bundle_root = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
                                                                                
    for location in (
        bundle_root,
        bundle_root / "app",
        bundle_root / "core" / "solver",
        bundle_root / "core" / "solver" / "linear_static",
    ):
        if str(location) not in sys.path:
            sys.path.append(str(location))
