"""Create a release once, verify every uploaded asset by release ID, then publish it."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from typing import Any, Callable
from urllib.parse import quote


EXPECTED_ASSETS = (
    "qbot-ai-{version}-native.tar.gz",
    "qbot-ai-{version}.tar.gz",
    "qbot-ai-{version}.zip",
    "SHA256SUMS",
    "provenance.sigstore.json",
)


class ReleaseError(RuntimeError):
    """Raised when release creation or verification cannot safely continue."""


def repository_path() -> str:
    value = os.environ.get("GH_REPO", "")
    parts = value.split("/")
    if len(parts) == 3:
        host, owner, repo = parts
        if host != os.environ.get("GH_HOST", "github.com"):
            raise ReleaseError("GH_REPO host does not match GH_HOST")
    elif len(parts) == 2:
        owner, repo = parts
    else:
        raise ReleaseError("GH_REPO must identify owner/repository")
    if not all(re.fullmatch(r"[A-Za-z0-9_.-]+", part) for part in (owner, repo)):
        raise ReleaseError("GH_REPO contains an invalid owner or repository")
    return f"repos/{owner}/{repo}"


def github_api(
    endpoint: str,
    *,
    method: str = "GET",
    payload: dict[str, Any] | None = None,
    data: bytes | None = None,
    content_type: str | None = None,
    paginate: bool = False,
) -> Any:
    """Call gh api without a shell; credentials are inherited, never printed."""
    command = ["gh", "api", "--hostname", os.environ.get("GH_HOST", "github.com")]
    if method != "GET":
        command.extend(["--method", method])
    if paginate:
        command.extend(["--paginate", "--slurp"])
    if content_type:
        command.extend(["--header", f"Content-Type: {content_type}"])
    input_data = None
    body_path: str | None = None
    if payload is not None:
        command.extend(["--input", "-"])
        input_data = json.dumps(payload).encode("utf-8")
    elif data is not None:
        with tempfile.NamedTemporaryFile(prefix="qbot-release-", delete=False) as body:
            body.write(data)
            body_path = body.name
        command.extend(["--input", body_path])
    command.append(endpoint)
    try:
        result = subprocess.run(command, input=input_data, capture_output=True, check=False)
    finally:
        if body_path is not None:
            try:
                os.unlink(body_path)
            except FileNotFoundError:
                pass
    if result.returncode:
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        raise ReleaseError(f"GitHub API request failed ({method} {endpoint}): {detail}")
    try:
        response = json.loads(result.stdout)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ReleaseError(f"GitHub API returned invalid JSON for {endpoint}") from exc
    if paginate:
        if not isinstance(response, list) or any(not isinstance(page, list) for page in response):
            raise ReleaseError(f"GitHub API returned invalid pages for {endpoint}")
        return [item for page in response for item in page]
    return response


def expected_assets(tag: str, assets_dir: Path) -> dict[str, dict[str, Any]]:
    version = tag[1:]
    names = {pattern.format(version=version) for pattern in EXPECTED_ASSETS}
    expected_files = names | {"notes.md"}
    actual_paths = list(assets_dir.iterdir()) if assets_dir.is_dir() else []
    actual_names = {path.name for path in actual_paths}
    if actual_names != expected_files or any(path.is_symlink() for path in actual_paths):
        missing = sorted(expected_files - actual_names)
        unexpected = sorted(actual_names - expected_files)
        raise ReleaseError(f"Release input files are not exact (missing={missing}, unexpected={unexpected})")
    if any(not (assets_dir / name).is_file() for name in expected_files):
        raise ReleaseError("Release input contains a non-file asset")

    assets: dict[str, dict[str, Any]] = {}
    for name in sorted(names):
        path = assets_dir / name
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        assets[name] = {"path": path, "size": path.stat().st_size, "digest": f"sha256:{digest}"}
    return assets


def assert_release_identity(release: Any, tag: str, release_id: int | None = None) -> int:
    if not isinstance(release, dict) or release.get("tag_name") != tag:
        raise ReleaseError(f"GitHub returned a release that does not match {tag}")
    identifier = release.get("id")
    if not isinstance(identifier, int) or isinstance(identifier, bool) or identifier <= 0:
        raise ReleaseError("GitHub returned an invalid release ID")
    if release_id is not None and identifier != release_id:
        raise ReleaseError(f"GitHub returned release ID {identifier}, expected {release_id}")
    return identifier


def verify_release_assets(
    release: Any,
    tag: str,
    release_id: int,
    assets: dict[str, dict[str, Any]],
    *,
    draft: bool,
) -> None:
    assert_release_identity(release, tag, release_id)
    if release.get("draft") is not draft:
        raise ReleaseError(f"Release {release_id} has an unexpected draft state")
    actual = release.get("assets")
    if not isinstance(actual, list) or len(actual) != len(assets):
        count = len(actual) if isinstance(actual, list) else "invalid"
        raise ReleaseError(f"Release {release_id} has {count} assets; expected exactly {len(assets)}")
    by_name = {item.get("name"): item for item in actual if isinstance(item, dict)}
    if len(by_name) != len(actual) or set(by_name) != set(assets):
        raise ReleaseError(f"Release {release_id} asset names do not match the expected set")
    for name, expected in assets.items():
        item = by_name[name]
        if item.get("size") != expected["size"]:
            raise ReleaseError(f"Release {release_id} asset {name} has an unexpected size")
        if item.get("digest") != expected["digest"]:
            raise ReleaseError(f"Release {release_id} asset {name} has an unexpected SHA-256 digest")
        if item.get("state") != "uploaded":
            raise ReleaseError(f"Release {release_id} asset {name} is not fully uploaded")


def run(tag: str, assets_dir: Path, api_call: Callable[..., Any] = github_api) -> dict[str, Any]:
    if not re.fullmatch(r"v(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)", tag):
        raise ReleaseError("Tag must match vMAJOR.MINOR.PATCH")
    assets = expected_assets(tag, assets_dir)
    base = repository_path()

    tag_ref = api_call(f"{base}/git/ref/tags/{quote(tag, safe='')}")
    if not isinstance(tag_ref, dict) or tag_ref.get("ref") != f"refs/tags/{tag}":
        raise ReleaseError(f"GitHub tag {tag} does not exist; refusing to create a release")
    tag_object = tag_ref.get("object")
    if not isinstance(tag_object, dict) or not isinstance(tag_object.get("sha"), str):
        raise ReleaseError(f"GitHub returned an invalid ref for {tag}")

    releases = api_call(f"{base}/releases?per_page=100", paginate=True)
    if not isinstance(releases, list):
        raise ReleaseError("GitHub returned an invalid release list")
    existing = [release for release in releases if isinstance(release, dict) and release.get("tag_name") == tag]
    if existing:
        identifiers = ", ".join(str(release.get("id", "unknown")) for release in existing)
        raise ReleaseError(f"Release already exists for {tag} (release IDs: {identifiers}); refusing to create another")

    notes = (assets_dir / "notes.md").read_text(encoding="utf-8")
    created = api_call(
        f"{base}/releases",
        method="POST",
        payload={"tag_name": tag, "name": f"QBot AI {tag}", "body": notes, "draft": True, "prerelease": False},
    )
    release_id = assert_release_identity(created, tag)
    if created.get("draft") is not True:
        raise ReleaseError(f"New release {release_id} was not created as a draft")
    upload_url = created.get("upload_url")
    expected_upload_url = f"https://uploads.github.com/{base}/releases/{release_id}/assets{{?name,label}}"
    if upload_url != expected_upload_url:
        raise ReleaseError(f"New release {release_id} returned an unexpected asset upload URL")

    for name, expected in assets.items():
        endpoint = f"https://uploads.github.com/{base}/releases/{release_id}/assets?name={quote(name, safe='')}"
        api_call(endpoint, method="POST", data=expected["path"].read_bytes(), content_type="application/octet-stream")

    release_endpoint = f"{base}/releases/{release_id}"
    uploaded = api_call(release_endpoint)
    verify_release_assets(uploaded, tag, release_id, assets, draft=True)

    api_call(release_endpoint, method="PATCH", payload={"draft": False, "make_latest": "true"})
    published = api_call(release_endpoint)
    verify_release_assets(published, tag, release_id, assets, draft=False)
    return {"id": release_id, "html_url": published.get("html_url"), "tag_name": tag}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--assets-dir", required=True, type=Path)
    args = parser.parse_args()
    try:
        release = run(args.tag, args.assets_dir)
    except (OSError, ReleaseError) as exc:
        print(f"Release stopped safely: {exc}", file=sys.stderr)
        return 1
    print(f"Published {release['tag_name']} as release ID {release['id']}: {release['html_url']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
