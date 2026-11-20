"""Mock tests for the release-ID publishing guardrail."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import publish_release  # noqa: E402


TAG = "v1.4.12"
RELEASE_ID = 42
BASE = "repos/yuchen0x1/AI-QQ-Bot"
UPLOAD_URL = f"https://uploads.github.com/{BASE}/releases/{RELEASE_ID}/assets{{?name,label}}"


class MockGitHub:
    def __init__(self, assets_dir: Path, *, existing=None, damage=None):
        self.assets_dir = assets_dir
        self.releases = list(existing or [])
        self.damage = damage
        self.draft = True
        self.uploaded = {}
        self.calls = []

    def __call__(self, endpoint, *, method="GET", payload=None, data=None, content_type=None, paginate=False):
        self.calls.append((method, endpoint))
        if endpoint == f"{BASE}/git/ref/tags/{TAG}":
            return {"ref": f"refs/tags/{TAG}", "object": {"sha": "a" * 40, "type": "commit"}}
        if endpoint == f"{BASE}/releases?per_page=100":
            return list(self.releases)
        if endpoint == f"{BASE}/releases":
            release = {
                "id": RELEASE_ID,
                "tag_name": payload["tag_name"],
                "draft": True,
                "upload_url": UPLOAD_URL,
            }
            self.releases.append(release)
            return release
        if endpoint.startswith(f"https://uploads.github.com/{BASE}/releases/{RELEASE_ID}/assets?"):
            name = parse_qs(urlparse(endpoint).query)["name"][0]
            self.uploaded[name] = data
            return {"name": name}
        if endpoint == f"{BASE}/releases/{RELEASE_ID}" and method == "GET":
            assets = [
                {
                    "name": name,
                    "size": len(content),
                    "digest": f"sha256:{hashlib.sha256(content).hexdigest()}",
                    "state": "uploaded",
                }
                for name, content in self.uploaded.items()
            ]
            if self.damage == "digest" and assets:
                assets[0]["digest"] = "sha256:" + "0" * 64
            elif self.damage == "count":
                assets.append({"name": "unexpected", "size": 1, "digest": "sha256:" + "0" * 64, "state": "uploaded"})
            elif self.damage == "name" and assets:
                assets[0]["name"] = "unexpected"
            elif self.damage == "size" and assets:
                assets[0]["size"] += 1
            return {
                "id": RELEASE_ID,
                "tag_name": TAG,
                "draft": self.draft,
                "assets": assets,
                "html_url": f"https://github.com/yuchen0x1/AI-QQ-Bot/releases/{RELEASE_ID}",
            }
        if endpoint == f"{BASE}/releases/{RELEASE_ID}" and method == "PATCH":
            self.draft = payload["draft"]
            return {"id": RELEASE_ID, "tag_name": TAG, "draft": self.draft}
        raise AssertionError(f"Unexpected mock request: {method} {endpoint}")


class PublishReleaseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.assets_dir = Path(self.temp.name)
        version = TAG[1:]
        names = [
            f"qbot-ai-{version}-native.tar.gz",
            f"qbot-ai-{version}.tar.gz",
            f"qbot-ai-{version}.zip",
            "SHA256SUMS",
            "provenance.sigstore.json",
            "notes.md",
        ]
        for name in names:
            (self.assets_dir / name).write_bytes(f"test asset: {name}".encode())
        self.env = patch.dict(os.environ, {"GH_HOST": "github.com", "GH_REPO": "github.com/yuchen0x1/AI-QQ-Bot"})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.addCleanup(self.temp.cleanup)

    def test_success_uploads_exact_assets_by_created_release_id_before_publish(self):
        api = MockGitHub(self.assets_dir)

        result = publish_release.run(TAG, self.assets_dir, api_call=api)

        self.assertEqual(result["id"], RELEASE_ID)
        self.assertFalse(api.draft)
        upload_calls = [endpoint for method, endpoint in api.calls if method == "POST" and "/assets?" in endpoint]
        self.assertEqual(len(upload_calls), 5)
        self.assertTrue(all(f"/releases/{RELEASE_ID}/assets?" in endpoint for endpoint in upload_calls))
        pre_publish = next(i for i, call in enumerate(api.calls) if call == ("PATCH", f"{BASE}/releases/{RELEASE_ID}"))
        verify = api.calls.index(("GET", f"{BASE}/releases/{RELEASE_ID}"))
        self.assertLess(verify, pre_publish)

    def test_existing_same_tag_drafts_block_retry_without_creating_another(self):
        api = MockGitHub(
            self.assets_dir,
            existing=[
                {"id": 7, "tag_name": TAG, "draft": True},
                {"id": 8, "tag_name": TAG, "draft": True},
            ],
        )

        with self.assertRaisesRegex(publish_release.ReleaseError, r"already exists.*7, 8"):
            publish_release.run(TAG, self.assets_dir, api_call=api)

        self.assertFalse(any(method == "POST" for method, _ in api.calls))

    def test_failed_asset_verification_leaves_draft_and_retry_refuses_duplicate(self):
        api = MockGitHub(self.assets_dir, damage="digest")

        with self.assertRaisesRegex(publish_release.ReleaseError, "unexpected SHA-256 digest"):
            publish_release.run(TAG, self.assets_dir, api_call=api)

        self.assertTrue(api.draft)
        self.assertFalse(any(method == "PATCH" for method, _ in api.calls))
        create_count = sum(method == "POST" and endpoint == f"{BASE}/releases" for method, endpoint in api.calls)
        self.assertEqual(create_count, 1)
        with self.assertRaisesRegex(publish_release.ReleaseError, "already exists"):
            publish_release.run(TAG, self.assets_dir, api_call=api)
        self.assertEqual(
            sum(method == "POST" and endpoint == f"{BASE}/releases" for method, endpoint in api.calls),
            1,
        )

    def test_unexpected_asset_metadata_fails_before_publishing(self):
        for damage, message in (
            ("count", "expected exactly 5"),
            ("name", "asset names do not match"),
            ("size", "unexpected size"),
        ):
            with self.subTest(damage=damage):
                api = MockGitHub(self.assets_dir, damage=damage)

                with self.assertRaisesRegex(publish_release.ReleaseError, message):
                    publish_release.run(TAG, self.assets_dir, api_call=api)

                self.assertTrue(api.draft)
                self.assertFalse(any(method == "PATCH" for method, _ in api.calls))


if __name__ == "__main__":
    unittest.main()
