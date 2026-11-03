"""Build from the repository root: python -m PyInstaller --clean OpenStructures.spec.

Only public desktop assets are data. Python is analysed as code, never copied as
an auth directory. Firebase Admin and migration utilities are release-excluded.
"""

from pathlib import Path
from PyInstaller.utils.hooks import collect_all, collect_dynamic_libs


ROOT = Path(SPECPATH)
APP = ROOT / "app"
EXCLUDED_LOCAL = {
    "app.auth.db",
    "app.auth.email_service",
    "app.auth.encrypt_secrets",
    "auth.db",
    "auth.email_service",
    "auth.encrypt_secrets",
}


def local_modules(directory, prefix):
    """Find module names without importing application code at build time."""
    modules = []
    for source in directory.rglob("*.py"):
        if "__pycache__" in source.parts:
            continue
        relative = source.relative_to(directory).with_suffix("")
        parts = list(relative.parts)
        if parts[-1] == "__init__":
            parts.pop()
        module = ".".join([prefix, *parts])
        if module not in EXCLUDED_LOCAL:
            modules.append(module)
    return modules


datas = []
RESOURCE_EXTENSIONS = {
    ".svg", ".png", ".jpg", ".jpeg", ".ico", ".gif", ".wav", ".mp3",
    ".mp4", ".ttf", ".otf", ".xlsx", ".csv", ".dat",
}
for relative, destinations in (
    ("graphic", ("app/graphic", "graphic")),
    ("ui", ("app/ui", "ui")),
    ("resources", ("app/resources", "resources")),
):
    directory = APP / relative
    for source in directory.rglob("*"):
        if not source.is_file() or "__pycache__" in source.parts:
            continue
        if source.suffix.lower() not in RESOURCE_EXTENSIONS:
            # The font atlas is a known public JSON asset, not arbitrary JSON.
            if source != APP / "graphic" / "font_atlas.json":
                continue
        for destination in destinations:
            parent = source.relative_to(directory).parent
            datas.append((str(source), str(Path(destination) / parent)))

# Optional, deliberately public Firebase client configuration; not an .env.
public_config = APP / "resources" / "auth_config.json"
if public_config.exists():
    import json
    config = json.loads(public_config.read_text(encoding="utf-8"))
    public_keys = {"api_key", "project_id", "auth_domain", "google_sign_in_url"}
    if not isinstance(config, dict) or set(config) - public_keys:
        raise ValueError("auth_config.json must contain only public Firebase client fields")
    datas.append((str(public_config), "app/resources"))
datas.append((str(ROOT / "LICENSE"), "."))

hiddenimports = []
for package in ("app", "core", "opencivil"):
    hiddenimports.extend(local_modules(ROOT / package, package))
for alias in ("graphic", "ui", "section_designer", "resources"):
    hiddenimports.extend(local_modules(APP / alias, alias))
for solver in ("linear_static", "RSA", "modal", "LTHA", "solid_elements", "buckling"):
    hiddenimports.extend(local_modules(ROOT / "core" / "solver" / solver, solver))

binaries = []
for package in ("pyqtgraph", "qtawesome", "gmsh", "meshio", "numba"):
    package_data, package_binaries, package_imports = collect_all(package)
    datas.extend(package_data)
    binaries.extend(package_binaries)
    hiddenimports.extend(package_imports)
binaries.extend(collect_dynamic_libs("PyQt6"))
hiddenimports.extend([
    "requests", "PyQt6.QtNetwork", "PyQt6.QtMultimedia",
    "PyQt6.QtMultimediaWidgets", "scipy.spatial",
    "scipy.spatial.transform._rotation_groups", "scipy.special.cython_special",
    "matplotlib.backends.backend_qtagg", "openpyxl.cell._writer", "pandas",
    "hinge_loader",
])

a = Analysis(
    [str(APP / "main.py")],
    pathex=[str(ROOT), str(APP), str(ROOT / "core" / "solver"),
            *[str(path) for path in (ROOT / "core" / "solver").iterdir()
              if path.is_dir() and path.name != "__pycache__"]],
    binaries=binaries,
    datas=datas,
    hiddenimports=sorted(set(hiddenimports)),
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[str(APP / "runtime_hook.py")],
    excludes=["torch", "tkinter", "wx", "pymongo", "bcrypt", "dotenv",
              "firebase_admin", "server", "tools.migrate_firebase_users",
              *sorted(EXCLUDED_LOCAL)],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [], exclude_binaries=True,
    name="OpenStructures", debug=False, bootloader_ignore_signals=False,
    strip=False, upx=False, console=False,
    icon=str(APP / "graphic" / "logo.ico"),
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False,
               name="OpenStructures")
