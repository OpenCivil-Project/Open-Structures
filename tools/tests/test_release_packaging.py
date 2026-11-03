"""Evaluate the release recipe with inert PyInstaller stubs; never build/import app."""

from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]

class PackagingSafetyTests(unittest.TestCase):
    def test_recipe_only_copies_public_assets_and_excludes_operator_modules(self):
        hooks = ModuleType("PyInstaller.utils.hooks")
        hooks.collect_all = lambda _: ([], [], [])
        hooks.collect_dynamic_libs = lambda _: []
        recorded = {}

        def analysis(scripts, **kwargs):
            recorded.update(kwargs)
            return SimpleNamespace(pure=[], scripts=[], binaries=[], datas=[])

        namespace = {"SPECPATH": str(ROOT), "Analysis": analysis,
                     "PYZ": lambda *_: None, "EXE": lambda *_, **__: None,
                     "COLLECT": lambda *_, **__: None}
        with patch.dict(sys.modules, {"PyInstaller.utils.hooks": hooks}):
            exec(compile((ROOT / "OpenStructures.spec").read_text(encoding="utf-8-sig"),
                         "OpenStructures.spec", "exec"), namespace)
        paths = [Path(source) for source, _ in recorded["datas"]]
        self.assertTrue(any(path.name == "logo.ico" for path in paths))
        self.assertTrue(any(path.name == "font_atlas.json" for path in paths))
        self.assertTrue(any(path.name.endswith(".xlsx") for path in paths))
        self.assertFalse(any(path.suffix in {".py", ".bin", ".env", ".pem", ".key"}
                             for path in paths))
        self.assertFalse(any("auth" in path.parts or "auth_web" in path.parts
                             or "tools" in path.parts for path in paths))
        self.assertIn("firebase_admin", recorded["excludes"])
        self.assertIn("pymongo", recorded["excludes"])
        self.assertNotIn("app.auth.encrypt_secrets", recorded["hiddenimports"])
        self.assertNotIn("app.auth.db", recorded["hiddenimports"])

if __name__ == "__main__":
    unittest.main()
