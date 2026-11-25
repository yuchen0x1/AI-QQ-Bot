"""Native update setup preserves custom code without loading it or overwriting data."""

from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "updater"))
from plugin_storage import persist_custom_plugins  # noqa: E402


class PluginStorageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "releases/old/backend/plugins"
        self.source.mkdir(parents=True)
        self.destination = self.root / "data/plugins"

    def plugin(self, folder, identifier="custom", **overrides):
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "plugin.json").write_text(json.dumps({"id": identifier, "permissions": ["message:reply"], **overrides}))
        (folder / "main.py").write_text("raise RuntimeError('Plugin code must never execute during migration')\n")

    def test_custom_plugin_is_copied_but_builtins_remain_versioned(self):
        self.plugin(self.source / "custom")
        self.plugin(self.source / "dice", "dice", builtin=True)
        result = persist_custom_plugins(self.source, self.destination)
        self.assertEqual(result, {"copied": ["custom"], "preserved": []})
        self.assertTrue((self.destination / "custom/main.py").is_file())
        self.assertFalse((self.destination / "dice").exists())
        self.assertTrue((self.source / "custom/main.py").is_file())

    def test_existing_newer_custom_code_is_never_overwritten(self):
        self.plugin(self.source / "custom")
        self.plugin(self.destination / "custom")
        (self.destination / "custom/main.py").write_text("# user's newer persistent implementation\n")
        result = persist_custom_plugins(self.source, self.destination)
        self.assertEqual(result["preserved"], ["custom"])
        self.assertIn("newer persistent", (self.destination / "custom/main.py").read_text())

    def test_manifest_is_validated_before_code_or_files_are_copied(self):
        self.plugin(self.source / "custom", permissions=["admin:all"])
        with self.assertRaisesRegex(ValueError, "permission"):
            persist_custom_plugins(self.source, self.destination)
        self.assertFalse((self.destination / "custom").exists())

    def test_unsafe_identifier_and_duplicate_ids_are_refused(self):
        self.plugin(self.source / "one", "../escape")
        with self.assertRaisesRegex(ValueError, "identifier"):
            persist_custom_plugins(self.source, self.destination)
        self.plugin(self.source / "one", "same")
        self.plugin(self.source / "two", "same")
        with self.assertRaisesRegex(ValueError, "same identifier"):
            persist_custom_plugins(self.source, self.destination)

    def test_nonstandard_plugin_claiming_builtin_is_still_preserved(self):
        self.plugin(self.source / "custom", builtin=True)
        result = persist_custom_plugins(self.source, self.destination)
        self.assertEqual(result["copied"], ["custom"])

    def test_legacy_manifest_without_id_keeps_its_directory_identifier(self):
        self.plugin(self.source / "legacy")
        manifest = self.source / "legacy/plugin.json"
        manifest.write_text(json.dumps({"permissions": ["message:reply"]}))
        result = persist_custom_plugins(self.source, self.destination)
        self.assertEqual(result["copied"], ["legacy"])
        self.assertTrue((self.destination / "legacy/main.py").is_file())

    def test_symlinks_cannot_pull_external_files_into_extensions(self):
        self.plugin(self.source / "custom")
        try:
            (self.source / "custom/link.py").symlink_to(self.source / "custom/main.py")
        except OSError:
            self.skipTest("OS does not permit unprivileged symlinks")
        with self.assertRaisesRegex(ValueError, "regular files"):
            persist_custom_plugins(self.source, self.destination)


if __name__ == "__main__":
    unittest.main()
