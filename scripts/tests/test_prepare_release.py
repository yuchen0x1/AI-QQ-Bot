"""Canonical per-version release bodies preserve the published template format."""

from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from prepare_release import prepare  # noqa: E402


class PrepareReleaseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.write("backend/app/core/version.py", 'APP_VERSION = "1.6.0"\n')
        self.write("frontend/package.json", '{"version":"1.6.0"}')
        self.write("frontend/package-lock.json", json.dumps({"version": "1.6.0", "packages": {"": {"version": "1.6.0"}}}))
        self.write("docs/releases/release-notes.md", "# History\n\n## v1.6.0（2026-11-25）\n\n- Legacy notes.\n")

    def write(self, name, content):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    def test_dedicated_body_has_priority_and_does_not_leak_index_title(self):
        notes = "## 📢 版本概述\n\n修复版本发现。\n\n## 🐛 问题修复\n\n- 更新提醒到期恢复。\n"
        self.write("docs/releases/v1.6.0.md", notes)
        self.assertEqual(prepare(self.root, "v1.6.0"), notes)
        self.assertNotIn("## v1.6.0", prepare(self.root, "v1.6.0"))
        self.assertNotIn("QBot AI v1.6.0", prepare(self.root, "v1.6.0"))

    def test_legacy_history_extraction_remains_when_dedicated_body_is_absent(self):
        self.assertEqual(prepare(self.root, "v1.6.0"), "## v1.6.0（2026-11-25）\n\n- Legacy notes.\n")

    def test_empty_or_blank_bullet_template_never_falls_back_to_history(self):
        for notes in ("", "## 📢 版本概述\n", "## 📢 版本概述\n\n-   \n"):
            with self.subTest(notes=notes):
                self.write("docs/releases/v1.6.0.md", notes)
                with self.assertRaisesRegex(ValueError, "start with|empty"):
                    prepare(self.root, "v1.6.0")

    def test_duplicate_title_and_version_headings_are_rejected(self):
        for title in ("# QBot AI v1.6.0", "## v1.6.0", "## QBot AI v1.6.0", "QBot AI v1.6.0"):
            with self.subTest(title=title):
                self.write("docs/releases/v1.6.0.md", f"## 📢 版本概述\n\n{title}\n\n- Fixed.\n")
                with self.assertRaisesRegex(ValueError, "must not repeat"):
                    prepare(self.root, "v1.6.0")

    def test_unfilled_template_is_rejected(self):
        self.write("docs/releases/v1.6.0.md", "## 📢 版本概述\n\n- [问题表现]：请填写。\n")
        with self.assertRaisesRegex(ValueError, "unfilled placeholders"):
            prepare(self.root, "v1.6.0")

    def test_dedicated_notes_do_not_bypass_source_version_gate(self):
        self.write("docs/releases/v1.6.0.md", "## 📢 版本概述\n\n- Fixed.\n")
        self.write("frontend/package.json", '{"version":"1.5.3"}')
        with self.assertRaisesRegex(ValueError, "does not match"):
            prepare(self.root, "v1.6.0")


if __name__ == "__main__":
    unittest.main()
