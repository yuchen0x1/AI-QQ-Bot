"""Validate release metadata consistency without requiring network access.

Local checks always run. When ``--release-json`` is supplied with a GitHub
``releases/latest`` response, the checker also verifies the remote tag, stable
flags, publish date, URL and required assets. Without that file the remote
state is reported as a warning instead of being treated as verified.
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from publish_release import EXPECTED_ASSETS

SEMVER = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")
DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
README_BLOCK = re.compile(
    r"<!--\s*github-release:start\s*-->(.*?)<!--\s*github-release:end\s*-->",
    re.DOTALL,
)
README_RELEASE = re.compile(
    r"\[v(?P<version>(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*))"
    r"\]\((?P<url>https://github\.com/(?P<repo>[^/\s)]+/[^/\s)]+)/releases/tag/v(?P=version))\)"
    r"\s*\**\s*·\s*(?P<date>\d{4}-\d{2}-\d{2})"
)


@dataclass(frozen=True)
class ReleaseInfo:
    version: str
    release_date: date
    url: str


@dataclass
class Report:
    oks: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def ok(self, message: str) -> None:
        self.oks.append(message)

    def warn(self, message: str) -> None:
        self.warnings.append(message)

    def error(self, message: str) -> None:
        self.errors.append(message)


def parse_semver(value: Any) -> tuple[int, int, int] | None:
    if not isinstance(value, str) or not SEMVER.fullmatch(value):
        return None
    major, minor, patch = value.split(".")
    return int(major), int(minor), int(patch)


def required_asset_names(version: str) -> set[str]:
    return {pattern.format(version=version) for pattern in EXPECTED_ASSETS}


def _read_text(path: Path, report: Report) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        report.error(f"cannot read {path}: {exc}")
        return None


def _read_json(path: Path, report: Report) -> Any | None:
    text = _read_text(path, report)
    if text is None:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        report.error(f"invalid JSON in {path}: {exc}")
        return None


def _backend_version(root: Path, report: Report) -> str | None:
    path = root / "backend/app/core/version.py"
    text = _read_text(path, report)
    if text is None:
        return None
    try:
        tree = ast.parse(text)
    except SyntaxError as exc:
        report.error(f"cannot parse {path}: {exc}")
        return None
    found: list[str] = []
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if not any(
            isinstance(target, ast.Name) and target.id == "APP_VERSION"
            for target in node.targets
        ):
            continue
        try:
            value = ast.literal_eval(node.value)
        except (ValueError, SyntaxError):
            report.error(f"{path} APP_VERSION is not a literal string")
            return None
        if not isinstance(value, str):
            report.error(f"{path} APP_VERSION is not a string")
            return None
        found.append(value)
    if not found:
        report.error(f"{path} does not define APP_VERSION")
        return None
    if len(found) > 1:
        report.error(f"{path} defines APP_VERSION more than once")
        return None
    return found[0]


def collect_source_versions(root: Path, report: Report) -> str | None:
    package_path = root / "frontend/package.json"
    lock_path = root / "frontend/package-lock.json"
    package = _read_json(package_path, report)
    lock = _read_json(lock_path, report)
    versions: dict[str, Any] = {
        "backend": _backend_version(root, report),
        "frontend": package.get("version") if isinstance(package, dict) else None,
        "lockfile": lock.get("version") if isinstance(lock, dict) else None,
        "lockfile root": (
            lock.get("packages", {}).get("", {}).get("version")
            if isinstance(lock, dict) and isinstance(lock.get("packages"), dict)
            else None
        ),
    }
    valid = True
    for source, version in versions.items():
        if parse_semver(version) is None:
            report.error(f"{source} version is missing or not SemVer: {version!r}")
            valid = False
    unique = {version for version in versions.values() if isinstance(version, str)}
    if len(unique) != 1:
        report.error(
            "version sources disagree: "
            + ", ".join(f"{source}={version!r}" for source, version in versions.items())
        )
        return next(
            (version for version in versions.values() if parse_semver(version)),
            None,
        )
    version = next(iter(unique))
    if valid:
        report.ok(f"version sources agree on {version}")
    return version


def parse_readme_release(root: Path, repo: str, report: Report) -> ReleaseInfo | None:
    readme = _read_text(root / "README.md", report)
    if readme is None:
        return None
    blocks = README_BLOCK.findall(readme)
    if len(blocks) != 1:
        report.error(
            "README.md must contain exactly one github-release:start/end block; "
            f"found {len(blocks)}"
        )
        return None
    matches = list(README_RELEASE.finditer(blocks[0]))
    if len(matches) != 1:
        report.error(
            "README release block must contain exactly one vMAJOR.MINOR.PATCH "
            "link with a matching GitHub release URL and a YYYY-MM-DD date; "
            f"found {len(matches)}"
        )
        return None
    match = matches[0]
    version = match.group("version")
    release_date_text = match.group("date")
    try:
        release_date = date.fromisoformat(release_date_text)
    except ValueError:
        report.error(f"README release date is invalid: {release_date_text}")
        return None
    expected_path = f"/{repo}/releases/tag/v{version}"
    parsed = urlparse(match.group("url"))
    if (
        parsed.scheme != "https"
        or parsed.netloc.lower() != "github.com"
        or parsed.path.rstrip("/").lower() != expected_path.lower()
    ):
        report.error(
            f"README release URL does not point to {repo} tag v{version}: "
            f"{match.group('url')}"
        )
    if match.group("repo").lower() != repo.lower():
        report.error(
            f"README release URL uses repository {match.group('repo')}, expected {repo}"
        )
    report.ok(f"README release block: v{version} ({release_date.isoformat()})")
    return ReleaseInfo(version, release_date, match.group("url"))


def _version_section(lines: list[str], version: str) -> tuple[int, int] | None:
    pattern = rf"(?<![\d.])v{re.escape(version)}(?![\d.])"
    starts = [
        index
        for index, line in enumerate(lines)
        if line.startswith("## ") and re.search(pattern, line)
    ]
    if len(starts) != 1:
        return None
    start = starts[0]
    end = next(
        (index for index in range(start + 1, len(lines)) if lines[index].startswith("## ")),
        len(lines),
    )
    return start, end


def check_release_notes(
    root: Path,
    version: str,
    expected_date: date | None,
    report: Report,
) -> date | None:
    path = root / "docs/releases/release-notes.md"
    text = _read_text(path, report)
    if text is None:
        return None
    lines = text.splitlines()
    section_range = _version_section(lines, version)
    if section_range is None:
        report.error(
            f"canonical release notes for v{version} are missing or duplicated"
        )
        return None
    start, end = section_range
    section = lines[start:end]
    if not any(re.match(r"^\s*-\s+\S", line) for line in section[1:]):
        report.error(f"release notes for v{version} contain no non-empty bullet")
        return None
    header_date = DATE.search(section[0])
    parsed_date = None
    if header_date is None:
        report.warn(f"release notes for v{version} do not show a release date")
    else:
        raw_date = header_date.group(0)
        try:
            parsed_date = date.fromisoformat(raw_date)
        except ValueError:
            report.error(f"release notes date is invalid: {raw_date}")
        if expected_date is not None and raw_date != expected_date.isoformat():
            report.error(
                f"release notes date {raw_date} does not match README "
                f"date {expected_date.isoformat()}"
            )
    report.ok(f"canonical release notes exist for v{version}")
    return parsed_date


def check_changelog(
    root: Path,
    version: str,
    expected_date: date | None,
    report: Report,
    *,
    warn_newer: bool = True,
) -> None:
    path = root / "CHANGELOG.md"
    text = _read_text(path, report)
    if text is None:
        return
    lines = text.splitlines()
    section_range = _version_section(lines, version)
    if section_range is None:
        report.error(f"CHANGELOG.md entry for v{version} is missing or duplicated")
        return
    start, end = section_range
    section = lines[start:end]
    heading_date = DATE.search(section[0])
    if heading_date is None:
        report.warn(f"CHANGELOG entry for v{version} has no release date")
    elif expected_date is not None and heading_date.group(0) != expected_date.isoformat():
        report.error(
            f"CHANGELOG date {heading_date.group(0)} does not match README "
            f"date {expected_date.isoformat()}"
        )
    if not any(re.match(r"^\s*-\s+\S", line) for line in section[1:]):
        report.warn(f"CHANGELOG entry for v{version} has no bullet list")
    if warn_newer:
        versions = []
        for line in lines:
            if line.startswith("## "):
                versions.extend(
                    tuple(int(part) for part in match.groups())
                    for match in re.finditer(r"v(\d+)\.(\d+)\.(\d+)", line)
                )
        current = parse_semver(version)
        if current is not None and versions and max(versions) > current:
            report.warn(
                f"CHANGELOG.md contains a version newer than README's v{version}; "
                "keep it clearly marked as unreleased until the Release exists"
            )
    report.ok(f"CHANGELOG.md contains v{version}")


def check_readme_vs_source(
    info: ReleaseInfo, source_version: str | None, report: Report
) -> None:
    if source_version is None:
        return
    released = parse_semver(info.version)
    source = parse_semver(source_version)
    if released is None or source is None:
        return
    if released > source:
        report.error(
            f"README advertises v{info.version} but the source tree is "
            f"v{source_version}; an unreleased version must not be described as current"
        )
    elif source > released:
        report.warn(
            f"source version v{source_version} is ahead of README's latest release "
            f"v{info.version}; allowed before publishing, but update README after release"
        )
    else:
        report.ok("README latest release matches the source version")


def check_release_workflow(root: Path, report: Report) -> None:
    path = root / ".github/workflows/release.yml"
    text = _read_text(path, report)
    if text is None:
        return
    if re.search(r"prepare_release\.py\s+--tag\s+v\d+\.\d+\.\d+", text):
        report.error("release workflow hardcodes a version tag; use github.ref_name")
    elif "prepare_release.py" not in text:
        report.warn("release workflow does not call prepare_release.py")
    if "github.ref_name" not in text:
        report.warn("release workflow does not reference github.ref_name")
    if "prepare_release.py" in text and "github.ref_name" in text:
        report.ok("release workflow uses the pushed tag dynamically")


def _test_report_scope(text: str, version: str) -> str:
    version_pattern = rf"(?<![\d.])v{re.escape(version)}(?![\d.])"
    lines = text.splitlines()
    headings = [
        (index, line) for index, line in enumerate(lines) if line.startswith("## ")
    ]
    if headings:
        sections = []
        for position, (start, line) in enumerate(headings):
            end = headings[position + 1][0] if position + 1 < len(headings) else len(lines)
            if re.search(version_pattern, line):
                sections.append("\n".join(lines[start:end]))
        if sections:
            return "\n".join(sections)
    prefix = "\n".join(lines[:20])
    return text if re.search(version_pattern, prefix) else ""


def check_test_reports(root: Path, version: str, report: Report) -> None:
    for path in sorted(root.glob("TEST_REPORT*.md")):
        text = _read_text(path, report)
        if text is None:
            continue
        scoped = _test_report_scope(text, version)
        if not scoped:
            continue
        warnings: set[str] = set()
        for line in scoped.splitlines():
            if line.lstrip().startswith("|") and "prepare_release.py" in line:
                match = re.search(r"--tag\s+v(\d+\.\d+\.\d+)", line)
                if match and match.group(1) != version:
                    warnings.add(
                        f"{path.name}: PASS table references --tag v{match.group(1)} "
                        f"but README release is v{version}"
                    )
        if "当前分支尚未合并、打标签或发布" in scoped:
            warnings.add(
                f"{path.name}: still says the branch has not been merged, tagged or released"
            )
        if "草稿和标签已撤回" in scoped or "标签已撤回" in scoped:
            warnings.add(
                f"{path.name}: claims a draft/tag was withdrawn; verify remote drafts "
                "and tags manually"
            )
        if re.search(r"正式版本|已正式发布", scoped) and re.search(
            r"尚未.{0,12}发布", scoped
        ):
            warnings.add(
                f"{path.name}: contains both a formal-release claim and a not-yet-released claim"
            )
        for warning in sorted(warnings):
            report.warn(warning)


def _pick(data: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in data:
            return data[key]
    return None


def _published_dates(value: Any) -> set[date]:
    if not isinstance(value, str):
        return set()
    try:
        moment = datetime.fromisoformat(value)
    except ValueError:
        return set()
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return {
        moment.date(),
        moment.astimezone(timezone(timedelta(hours=8))).date(),
    }


def check_remote_release(
    release_path: Path,
    repo: str,
    info: ReleaseInfo | None,
    source_version: str | None,
    report: Report,
) -> None:
    data = _read_json(release_path, report)
    if not isinstance(data, dict):
        if data is not None:
            report.error(f"{release_path} does not contain a JSON object")
        return
    if info is None:
        report.error("cannot verify remote Release because the README block is invalid")
        return
    tag = _pick(data, "tag_name", "tagName")
    if tag != f"v{info.version}":
        report.error(
            f"remote latest Release tag {tag!r} does not match README "
            f"v{info.version}"
        )
    draft = _pick(data, "draft", "isDraft")
    if draft is None:
        report.error("remote Release JSON is missing the draft flag")
    elif draft:
        report.error("remote latest Release is a Draft")
    prerelease = _pick(data, "prerelease", "isPrerelease")
    if prerelease is None:
        report.error("remote Release JSON is missing the prerelease flag")
    elif prerelease:
        report.error("remote latest Release is a pre-release")
    published_at = _pick(data, "published_at", "publishedAt")
    published_dates = _published_dates(published_at)
    if not published_dates:
        report.error("remote Release JSON has no valid published_at timestamp")
    elif info.release_date not in published_dates:
        report.error(
            f"README date {info.release_date.isoformat()} does not match remote "
            f"published_at {published_at}"
        )
    url = _pick(data, "html_url", "url")
    expected_path = f"/{repo}/releases/tag/v{info.version}"
    parsed = urlparse(url) if isinstance(url, str) else None
    if (
        parsed is None
        or parsed.scheme != "https"
        or parsed.netloc.lower() != "github.com"
        or parsed.path.rstrip("/").lower() != expected_path.lower()
    ):
        report.error(f"remote Release URL is not {repo} tag v{info.version}: {url!r}")
    assets = data.get("assets")
    if not isinstance(assets, list):
        report.error("remote Release JSON has no assets list")
        assets = []
    by_name: dict[str, dict[str, Any]] = {}
    for asset in assets:
        if isinstance(asset, dict) and isinstance(asset.get("name"), str):
            by_name[asset["name"]] = asset
    required = required_asset_names(info.version)
    missing = sorted(required - set(by_name))
    if missing:
        report.error("remote Release is missing assets: " + ", ".join(missing))
    for name in sorted(required & set(by_name)):
        asset = by_name[name]
        if asset.get("state") != "uploaded":
            report.error(f"remote asset {name} is not uploaded")
        size = asset.get("size")
        if not isinstance(size, int) or size <= 0:
            report.error(f"remote asset {name} has no positive size")
    extras = sorted(set(by_name) - required)
    if extras:
        report.warn("remote Release has extra assets: " + ", ".join(extras))
    remote_version = tag[1:] if isinstance(tag, str) and tag.startswith("v") else None
    remote_semver = parse_semver(remote_version)
    source_semver = parse_semver(source_version)
    if remote_semver is not None and source_semver is not None and remote_semver > source_semver:
        report.error(
            f"remote Release v{remote_version} is newer than the source tree "
            f"v{source_version}"
        )
    if not missing and draft is False and prerelease is False:
        report.ok(
            f"remote Release v{info.version} is stable and contains all "
            f"{len(required)} required assets"
        )


def check_tag_target(root: Path, tag: str, repo: str, report: Report) -> None:
    match = re.fullmatch(r"v(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)", tag)
    if match is None:
        report.error("--tag must match vMAJOR.MINOR.PATCH")
        return
    version = tag[1:]
    source_version = collect_source_versions(root, report)
    if source_version is not None:
        if source_version != version:
            report.error(
                f"tag {tag} does not match source version v{source_version}"
            )
        else:
            report.ok(f"tag {tag} matches the source version")
    notes_date = check_release_notes(root, version, None, report)
    check_changelog(root, version, notes_date, report, warn_newer=False)
    info = parse_readme_release(root, repo, report)
    if info is not None:
        readme_version = parse_semver(info.version)
        target_version = parse_semver(version)
        if readme_version is not None and target_version is not None:
            if readme_version > target_version:
                report.error(
                    f"README advertises v{info.version}, which is newer than tag {tag}"
                )
            elif readme_version < target_version:
                report.warn(
                    f"README still advertises v{info.version}; update it after "
                    f"publishing {tag}"
                )
            else:
                report.ok(f"README already advertises tag {tag}")
    check_test_reports(root, version, report)


def build_report(
    root: Path,
    repo: str,
    *,
    tag: str | None = None,
    release_json: Path | None = None,
    require_remote: bool = False,
) -> Report:
    report = Report()
    check_release_workflow(root, report)
    if tag is not None:
        if release_json is not None:
            report.error("--tag and --release-json cannot be combined")
        if require_remote:
            report.error("--require-remote cannot be used with --tag")
        check_tag_target(root, tag, repo, report)
        return report
    source_version = collect_source_versions(root, report)
    info = parse_readme_release(root, repo, report)
    if info is not None:
        check_release_notes(root, info.version, info.release_date, report)
        check_changelog(root, info.version, info.release_date, report)
        check_readme_vs_source(info, source_version, report)
        check_test_reports(root, info.version, report)
    if release_json is not None:
        check_remote_release(release_json, repo, info, source_version, report)
    elif require_remote:
        report.error(
            "--require-remote was set but --release-json was not provided; "
            "remote release state is unverified"
        )
    else:
        report.warn(
            "GitHub latest release was not checked; pass --release-json to verify "
            "tag, stable flags, date, URL and assets"
        )
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="repository root (default: this script's repository)",
    )
    parser.add_argument(
        "--repo",
        default="yuchen0x1/AI-QQ-Bot",
        help="expected GitHub owner/repository",
    )
    parser.add_argument(
        "--tag",
        help="validate a pushed release tag and its target notes instead of README",
    )
    parser.add_argument(
        "--release-json",
        type=Path,
        help="GitHub API releases/latest JSON response",
    )
    parser.add_argument(
        "--require-remote",
        action="store_true",
        help="fail instead of warning when --release-json is absent",
    )
    args = parser.parse_args(argv)
    report = build_report(
        args.root,
        args.repo,
        tag=args.tag,
        release_json=args.release_json,
        require_remote=args.require_remote,
    )
    for message in report.oks:
        print(f"OK {message}")
    for message in report.warnings:
        print(f"WARNING {message}")
    for message in report.errors:
        print(f"ERROR {message}")
    print(
        f"{len(report.oks)} passed, {len(report.warnings)} warning(s), "
        f"{len(report.errors)} error(s)"
    )
    return 1 if report.errors else 0


if __name__ == "__main__":
    sys.exit(main())
