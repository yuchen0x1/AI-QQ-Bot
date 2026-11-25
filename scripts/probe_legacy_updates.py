"""Run the unmodified update checkers from released Git tags, in isolated processes.

Fixture mode verifies compatibility before release. --live queries the real
GitHub release source afterwards; it never changes an old checker's APP_VERSION.
The optional gh credential is held only in child process memory and never logged.
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

TAGS = ("v1.4.12", "v1.5.2", "v1.5.3")
SOURCES = (
    "app/core/config.py",
    "app/core/version.py",
    "app/core/http.py",
    "app/services/github/client.py",
    "app/services/update_checker.py",
)
FIXTURE_SCENARIOS = ("anonymous", "valid-token", "invalid-token", "forbidden", "rate-limited", "offline-recovery")
LIVE_SCENARIOS = ("anonymous", "invalid-token")


def git(repo: Path, *args: str) -> bytes:
    return subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True).stdout


async def child_probe(args: argparse.Namespace) -> dict:
    import httpx

    repo = args.repo.resolve()
    commit = git(repo, "rev-parse", args.child_tag + "^{commit}").decode().strip()
    with tempfile.TemporaryDirectory(prefix="qbot-released-checker-") as directory:
        root = Path(directory)
        hashes = {}
        for source in SOURCES:
            content = git(repo, "show", args.child_tag + ":backend/" + source)
            hashes[source] = hashlib.sha256(content).hexdigest()
            target = root / source
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
        for package in ("app", "app/core", "app/services", "app/services/github"):
            (root / package / "__init__.py").write_text("", encoding="utf-8")
        os.environ.update({
            "ENV": "development", "DATABASE_URL": "sqlite+aiosqlite:///" + (root / "test.db").as_posix(),
            "DATA_DIR": str(root / "data"), "BACKUP_DIR": str(root / "backups"),
            "GITHUB_API_BASE": "https://api.github.com", "UPDATE_REPOSITORY": args.repository,
            "UPDATE_CHANNEL": "stable", "GITHUB_TOKEN": "",
        })
        sys.path.insert(0, str(root))
        from app.core.config import settings
        from app.core.http import set_transport
        from app.core.version import APP_VERSION
        from app.services.update_checker import check_for_update, compare_versions

        release = {
            "tag_name": "v" + args.candidate_version,
            "html_url": f"https://github.com/{args.repository}/releases/tag/v{args.candidate_version}",
            "body": "Controlled compatibility fixture; not a production release observation.",
            "prerelease": False, "draft": False,
            "published_at": "2026-11-25T00:00:00Z",
            "assets": [{
                "name": f"qbot-ai-{args.candidate_version}-native.tar.gz", "size": 42,
                "browser_download_url": f"https://github.com/{args.repository}/releases/download/"
                    f"v{args.candidate_version}/qbot-ai-{args.candidate_version}-native.tar.gz",
                "digest": "sha256:" + "a" * 64,
            }],
        }
        scenarios = list(LIVE_SCENARIOS if args.live else FIXTURE_SCENARIOS)
        live_token = None
        if args.live and args.use_gh_token:
            live_token = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True, check=True).stdout.strip()
            scenarios.insert(1, "valid-token")
        results = []
        for scenario in scenarios:
            requests = []
            recovery = False
            settings.github_token = (live_token if args.live else "fixture-valid-token") if scenario == "valid-token" else (
                "qbot-intentionally-invalid-compatibility-probe" if scenario == "invalid-token" else None
            )

            def handler(request):
                requests.append({"authenticated": "authorization" in request.headers, "path": request.url.path})
                if scenario == "invalid-token" and "authorization" in request.headers:
                    return httpx.Response(401, json={"message": "Bad credentials"})
                if scenario in ("forbidden", "rate-limited"):
                    return httpx.Response(403 if scenario == "forbidden" else 429,
                                          headers={"Retry-After": "120"}, json={"message": "fixture denied"})
                if scenario == "offline-recovery" and not recovery:
                    raise httpx.ConnectError("controlled offline fixture")
                return httpx.Response(200, json=release)

            set_transport(None if args.live else httpx.MockTransport(handler))
            result = await check_for_update()
            first_ok = result["ok"]
            if scenario == "offline-recovery":
                recovery = True
                result = await check_for_update()
            discovery = bool(result["ok"] and result["update_available"]
                             and result["latest_version"] == args.candidate_version)
            known_legacy_limit = args.child_tag == "v1.4.12" and scenario == "invalid-token"
            if known_legacy_limit:
                verified = not result["ok"] and not result["update_available"]
            elif scenario in ("forbidden", "rate-limited"):
                verified = not result["ok"] and not result["update_available"]
            else:
                verified = bool(result["ok"] and result["latest_version"] == args.candidate_version
                                and result["update_available"] == (compare_versions(args.candidate_version, APP_VERSION) > 0)
                                and (scenario != "offline-recovery" or not first_ok))
            results.append({
                "scenario": scenario,
                "ok": result["ok"], "update_available": result["update_available"],
                "latest_version": result["latest_version"], "discovered_candidate": discovery,
                "asset_names": [asset["name"] for asset in result.get("assets", [])],
                "error": result["error"], "fixture_requests": requests if not args.live else None,
                "verified_expected_behavior": verified,
                "known_legacy_limit": "invalid token prevents anonymous retry; clear token and restart" if known_legacy_limit else None,
                **({"initial_offline_ok": first_ok} if scenario == "offline-recovery" else {}),
            })
        set_transport(None)
        return {"tag": args.child_tag, "commit": commit, "installed_version": APP_VERSION,
                "source_sha256": hashes, "cases": results}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--repository", default="yuchen0x1/AI-QQ-Bot")
    parser.add_argument("--candidate-version", required=True)
    parser.add_argument("--live", action="store_true", help="Query real GitHub release metadata, without a mock transport")
    parser.add_argument("--use-gh-token", action="store_true", help="Also check a valid token from the existing gh credential store")
    parser.add_argument("--report", type=Path)
    parser.add_argument("--child-tag", choices=TAGS, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.child_tag:
        print(json.dumps(asyncio.run(child_probe(args)), ensure_ascii=False))
        return 0
    versions = []
    for tag in TAGS:
        command = [sys.executable, str(Path(__file__).resolve()), "--repo", str(args.repo),
                   "--repository", args.repository, "--candidate-version", args.candidate_version, "--child-tag", tag]
        if args.live:
            command.append("--live")
        if args.use_gh_token:
            command.append("--use-gh-token")
        completed = subprocess.run(command, capture_output=True, text=True, encoding="utf-8",
                                   env={**os.environ, "PYTHONIOENCODING": "utf-8"})
        if completed.returncode:
            # Child stderr may include transport exceptions. Do not copy secrets or URLs into the report.
            versions.append({"tag": tag, "probe_error": "isolated child process failed", "exit_code": completed.returncode})
        else:
            versions.append(json.loads(completed.stdout))
    report = {"mode": "live-github" if args.live else "controlled-fixture",
              "observed_at": datetime.now(timezone.utc).isoformat(),
              "repository": args.repository, "candidate_version": args.candidate_version,
              "meaning": "Actual released checker/client/config/version source, unmodified; no QQ or install validation.",
              "versions": versions}
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if all("probe_error" not in version and all(case["verified_expected_behavior"] for case in version["cases"])
                    for version in versions) else 1


if __name__ == "__main__":
    raise SystemExit(main())
