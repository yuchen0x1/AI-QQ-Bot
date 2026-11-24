"""Tests for the release metadata consistency checker."""

from __future__ import annotations

import io
import json
import sys
import tempfile
import textwrap
import unittest
from contextlib import redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import check_release_consistency as checker

REPO = "yuchen0x1/AI-QQ-Bot"
VERSION = "1.5.2"
RELEASE_DATE = "2026-11-24"


class ReleaseConsistencyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.write("backend/app/core/version.py", 'APP_VERSION = "1.5.2"\n')
        self.write("frontend/package.json", '{"name": "qbot-admin", "version": "1.5.2"}\n')
        self.write(
            "frontend/package-lock.json",
            json.dumps(
                {
                    "name": "qbot-admin",
                    "version": "1.5.2",
                    "packages": {"": {"name": "qbot-admin", "version": "1.5.2"}},
                }
            ),
        )
        self.write("README.md", self.readme())
        self.write("docs/releases/release-notes.md", self.release_notes())
        self.write("CHANGELOG.md", self.changelog())
        self.write(
            ".github/workflows/release.yml",
            textwrap.dedent(
                """\
                name: Release
                on:
                  push:
                    tags: ['v*.*.*']
                jobs:
                  package:
                    env:
                      VERSION: ${{ github.ref_name }}
                    steps:
                      - run: python3 scripts/prepare_release.py --tag "$VERSION" --notes-output notes.md
                """
            ),
        )
        self.write(
            "TEST_REPORT_2026-11-24.md",
            "# TEST_REPORT（v1.5.2，2026-11-24）\n\n本地验证记录。\n",
        )
        self.release_json = self.root / "latest-release.json"
        self.write_json("latest-release.json", self.release_payload())

    def write(self, relative: str, text: str) -> None:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def write_json(self, relative: str, payload: object) -> None:
        self.write(relative, json.dumps(payload))

    def readme(self, *, version: str = VERSION, repo: str = REPO) -> str:
        return (
            "# Test README\n\n"
            "<!-- github-release:start -->\n\n"
            f"**[v{version}](https://github.com/{repo}/releases/tag/v{version})** "
            f"· {RELEASE_DATE}\n\n"
            "本版本包含已发布的修复。\n\n"
            f"[全部发行记录](https://github.com/{repo}/releases)\n\n"
            "<!-- github-release:end -->\n"
        )

    def release_notes(self, *, version: str = VERSION) -> str:
        return (
            "# 更新历史\n\n"
            f"## v{version}（{RELEASE_DATE}）\n\n"
            "### 版本概述\n\n"
            "- 修复测试问题。\n\n"
            "## v1.5.0（2026-11-23）\n\n"
            "- 历史版本。\n"
        )

    def changelog(self, *, version: str = VERSION) -> str:
        return (
            "# CHANGELOG\n\n"
            f"## {RELEASE_DATE} · v{version}\n\n"
            "- 修复测试问题。\n\n"
            "## 2026-11-23 · v1.5.0\n\n"
            "- 历史版本。\n"
        )

    def release_payload(self, **overrides: object) -> dict[str, object]:
        payload: dict[str, object] = {
            "tag_name": f"v{VERSION}",
            "draft": False,
            "prerelease": False,
            "published_at": "2026-11-24T05:50:07Z",
            "html_url": f"https://github.com/{REPO}/releases/tag/v{VERSION}",
            "assets": [
                {"name": name, "size": 100, "state": "uploaded"}
                for name in (
                    "SHA256SUMS",
                    "provenance.sigstore.json",
                    "qbot-ai-1.5.2-native.tar.gz",
                    "qbot-ai-1.5.2.tar.gz",
                    "qbot-ai-1.5.2.zip",
                )
            ],
        }
        payload.update(overrides)
        return payload

    def build(self, **kwargs: object) -> checker.Report:
        return checker.build_report(self.root, REPO, **kwargs)  # type: ignore[arg-type]

    def assert_error(self, report: checker.Report, text: str) -> None:
        self.assertTrue(
            any(text.lower() in error.lower() for error in report.errors),
            report.errors,
        )

    def test_valid_local_repo_passes_and_warns_that_remote_is_unchecked(self):
        report = self.build()

        self.assertFalse(report.errors, report.errors)
        self.assertTrue(
            any("was not checked" in warning for warning in report.warnings),
            report.warnings,
        )

    def test_version_source_mismatch_fails(self):
        self.write("frontend/package.json", '{"version": "1.5.1"}\n')

        report = self.build()

        self.assert_error(report, "version sources disagree")

    def test_source_ahead_of_readme_is_allowed_with_warning(self):
        self.set_source_version("1.5.3")

        report = self.build()

        self.assertFalse(report.errors, report.errors)
        self.assertTrue(
            any("ahead of README" in warning for warning in report.warnings),
            report.warnings,
        )

    def write_version_source(self, relative: str, version: str) -> str:
        if relative.endswith("version.py"):
            return f'APP_VERSION = "{version}"\n'
        if relative.endswith("package.json"):
            return json.dumps({"name": "qbot-admin", "version": version})
        return json.dumps(
            {
                "name": "qbot-admin",
                "version": version,
                "packages": {"": {"name": "qbot-admin", "version": version}},
            }
        )

    def set_source_version(self, version: str) -> None:
        for relative in (
            "backend/app/core/version.py",
            "frontend/package.json",
            "frontend/package-lock.json",
        ):
            self.write(relative, self.write_version_source(relative, version))

    def test_readme_newer_than_source_fails(self):
        self.write("README.md", self.readme(version="1.5.3"))
        self.write("docs/releases/release-notes.md", self.release_notes(version="1.5.3"))
        self.write("CHANGELOG.md", self.changelog(version="1.5.3"))

        report = self.build()

        self.assert_error(report, "unreleased version must not be described as current")

    def test_wrong_readme_release_repository_fails(self):
        self.write("README.md", self.readme(repo="other/repo"))

        report = self.build()

        self.assert_error(report, "expected yuchen0x1/AI-QQ-Bot")

    def test_missing_canonical_release_notes_fails(self):
        (self.root / "docs/releases/release-notes.md").unlink()

        report = self.build()

        self.assert_error(report, "cannot read")

    def test_empty_canonical_release_notes_fail(self):
        self.write(
            "docs/releases/release-notes.md",
            f"# 更新历史\n\n## v{VERSION}（{RELEASE_DATE}）\n\n### 版本概述\n\n",
        )

        report = self.build()

        self.assert_error(report, "no non-empty bullet")

    def test_missing_changelog_entry_fails(self):
        self.write("CHANGELOG.md", "# CHANGELOG\n\n## 2026-11-23 · v1.5.0\n\n- old\n")

        report = self.build()

        self.assert_error(report, "CHANGELOG.md entry for v1.5.2 is missing or duplicated")

    def test_release_workflow_hardcoded_tag_fails(self):
        self.write(
            ".github/workflows/release.yml",
            textwrap.dedent(
                """\
                name: Release
                on:
                  push:
                    tags: ['v*.*.*']
                jobs:
                  package:
                    steps:
                      - run: python3 scripts/prepare_release.py --tag v1.5.2 --notes-output notes.md
                """
            ),
        )

        report = self.build()

        self.assert_error(report, "hardcodes a version tag")

    def test_remote_stable_release_passes(self):
        report = self.build(release_json=self.release_json, require_remote=True)

        self.assertFalse(report.errors, report.errors)
        self.assertFalse(
            any("was not checked" in warning for warning in report.warnings),
            report.warnings,
        )
        self.assertTrue(
            any("remote Release v1.5.2 is stable" in ok for ok in report.oks),
            report.oks,
        )

    def test_remote_draft_fails(self):
        self.write_json("latest-release.json", self.release_payload(draft=True))

        report = self.build(release_json=self.release_json, require_remote=True)

        self.assert_error(report, "is a Draft")

    def test_remote_prerelease_fails(self):
        self.write_json("latest-release.json", self.release_payload(prerelease=True))

        report = self.build(release_json=self.release_json, require_remote=True)

        self.assert_error(report, "is a pre-release")

    def test_remote_missing_asset_fails(self):
        payload = self.release_payload()
        payload["assets"] = [
            asset
            for asset in payload["assets"]  # type: ignore[union-attr]
            if asset["name"] != "SHA256SUMS"
        ]
        self.write_json("latest-release.json", payload)

        report = self.build(release_json=self.release_json, require_remote=True)

        self.assert_error(report, "missing assets")

    def test_remote_date_mismatch_fails(self):
        self.write_json(
            "latest-release.json",
            self.release_payload(published_at="2026-11-23T05:50:07Z"),
        )

        report = self.build(release_json=self.release_json, require_remote=True)

        self.assert_error(report, "does not match remote published_at")

    def test_remote_tag_mismatch_fails(self):
        self.write_json("latest-release.json", self.release_payload(tag_name="v1.5.1"))

        report = self.build(release_json=self.release_json, require_remote=True)

        self.assert_error(report, "does not match README")

    def test_remote_url_mismatch_fails(self):
        self.write_json(
            "latest-release.json",
            self.release_payload(
                html_url=f"https://github.com/{REPO}/releases/tag/v1.5.1"
            ),
        )

        report = self.build(release_json=self.release_json, require_remote=True)

        self.assert_error(report, "remote Release URL is not")

    def test_require_remote_without_json_fails(self):
        report = self.build(require_remote=True)

        self.assert_error(report, "--require-remote was set")

    def test_tag_mode_validates_target_and_allows_readme_behind(self):
        self.set_source_version("1.5.3")
        self.write("docs/releases/release-notes.md", self.release_notes(version="1.5.3"))
        self.write("CHANGELOG.md", self.changelog(version="1.5.3"))

        report = self.build(tag="v1.5.3")

        self.assertFalse(report.errors, report.errors)
        self.assertTrue(
            any("README still advertises" in warning for warning in report.warnings),
            report.warnings,
        )

    def test_tag_mode_rejects_source_mismatch(self):
        self.write("docs/releases/release-notes.md", self.release_notes(version="1.5.3"))
        self.write("CHANGELOG.md", self.changelog(version="1.5.3"))

        report = self.build(tag="v1.5.3")

        self.assert_error(report, "does not match source version")

    def test_tag_mode_requires_target_changelog_entry(self):
        self.write("CHANGELOG.md", "# CHANGELOG\n\n## 2026-11-23 · v1.5.0\n\n- old\n")

        report = self.build(tag="v1.5.2")

        self.assert_error(report, "CHANGELOG.md entry for v1.5.2")

    def test_tag_and_remote_require_are_rejected_together(self):
        report = self.build(tag="v1.5.2", require_remote=True)

        self.assert_error(report, "cannot be used with --tag")

    def test_duplicate_release_note_heading_fails(self):
        self.write(
            "docs/releases/release-notes.md",
            self.release_notes() + f"\n## v{VERSION}（{RELEASE_DATE}）\n\n- duplicate\n",
        )

        report = self.build()

        self.assert_error(report, "missing or duplicated")

    def test_duplicate_backend_version_assignment_fails(self):
        self.write(
            "backend/app/core/version.py",
            'APP_VERSION = "1.5.2"\nAPP_VERSION = "1.5.2"\n',
        )

        report = self.build()

        self.assert_error(report, "defines APP_VERSION more than once")

    def test_required_asset_names_are_the_literal_published_set(self):
        self.assertEqual(
            checker.required_asset_names(VERSION),
            {
                "SHA256SUMS",
                "provenance.sigstore.json",
                "qbot-ai-1.5.2-native.tar.gz",
                "qbot-ai-1.5.2.tar.gz",
                "qbot-ai-1.5.2.zip",
            },
        )

    def test_stale_test_report_claims_warn(self):
        self.write(
            "TEST_REPORT_2026-11-24.md",
            textwrap.dedent(
                f"""\
                # TEST_REPORT（v{VERSION}，{RELEASE_DATE}）

                | PASS | `python scripts/prepare_release.py --tag v1.5.0 --notes-output <temp>` | ok |
                当前分支尚未合并、打标签或发布。
                首次误建 v1.5.1，草稿和标签已撤回。
                v1.5.2 已正式发布。
                """
            ),
        )

        report = self.build()

        self.assertFalse(report.errors, report.errors)
        warnings = "\n".join(report.warnings)
        self.assertIn("PASS table references --tag v1.5.0", warnings)
        self.assertIn("has not been merged", warnings)
        self.assertIn("draft/tag was withdrawn", warnings)
        self.assertIn("formal-release claim", warnings)

    def test_old_test_report_sections_are_not_flagged(self):
        self.write(
            "TEST_REPORT.md",
            textwrap.dedent(
                f"""\
                # TEST_REPORT

                ## v{VERSION} 发布：{RELEASE_DATE}

                - 当前版本记录。

                ## v1.4.7 发布：2026-11-15

                | PASS | `python scripts/prepare_release.py --tag v1.4.7` | 历史记录 |
                """
            ),
        )

        report = self.build()

        self.assertFalse(report.errors, report.errors)
        self.assertFalse(
            any("v1.4.7" in warning for warning in report.warnings),
            report.warnings,
        )

    def test_cli_returns_nonzero_when_remote_is_required_but_missing(self):
        output = io.StringIO()
        with redirect_stdout(output):
            code = checker.main(
                ["--root", str(self.root), "--repo", REPO, "--require-remote"]
            )

        self.assertEqual(code, 1)
        self.assertIn("ERROR", output.getvalue())


if __name__ == "__main__":
    unittest.main()
