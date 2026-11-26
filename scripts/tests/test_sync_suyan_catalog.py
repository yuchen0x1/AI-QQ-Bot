"""Offline regression tests for the Suyan public documentation cataloger."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import sync_suyan_catalog as sync

HOMEPAGE = """<!doctype html>
<html><body>
  <div class="tool-card">
    <a href="doc/bb.php">
      <div class="tool-header"><span>宝</span> <span>宝贝回家</span>
        <span>累计调用：3831次</span></div>
      <p class="tool-description">素颜API</p>
      <div class="tool-meta">运行中 点击查看</div>
    </a>
  </div>
  <div class="tool-card">
    <a href="https://60s.suyanw.cn/"><div class="tool-header">6 60s秒读世界</div>
      <p class="tool-description">素颜API</p><div class="tool-meta">运行中</div></a>
  </div>
  <div class="tool-card">
    <a href="api/xjj"><div class="tool-header">美 美女视频②</div>
      <p class="tool-description">素颜API</p><div class="tool-meta">运行中</div></a>
  </div>
</body></html>""".encode()

DOCUMENT = """<!doctype html><html><head><title>Demo API - Suyan</title>
  <script>this is page data, not executable by the cataloger</script>
</head><body>
  <p class="simpleTable"><span>接口地址：</span>
    <span class="url">https://api.suyanw.cn/api/demo.php</span></p>
  <p class="simpleTable"><span>返回格式：</span><span>JSON</span></p>
  <p class="simpleTable"><span>请求方式：</span><span>GET/POST</span></p>
  <p class="simpleTable"><span>请求示例：</span><span>https://api.suyanw.cn/api/demo.php?q=hi</span></p>
  <p class="linep">请求参数说明：</p>
  <table><tbody>
    <tr><th>名称</th><th>必填</th><th>说明</th><th>默认值</th><th>示例</th></tr>
    <tr><td>q</td><td>是</td><td>查询内容</td><td></td><td>hello</td></tr>
    <tr><td>format</td><td>否</td><td>输出格式</td><td>json</td><td>xml</td></tr>
  </tbody></table>
  <p class="linep">系统级错误：</p>
  <table><tr><th>名称</th><th>说明</th></tr><tr><td>403</td><td>拒绝</td></tr></table>
</body></html>""".encode()

CATALOG_DOCUMENT = DOCUMENT.replace(
    b"Demo API - Suyan",
    "宝贝回家API - Suyan".encode(),
)


class ParseHomepageTests(unittest.TestCase):
    def test_extracts_cards_without_call_statistics_or_generic_description(self):
        entries = sync.parse_homepage(HOMEPAGE)

        self.assertEqual(len(entries), 3)
        self.assertEqual(entries[0]["id"], "bb")
        self.assertEqual(entries[0]["name"], "宝贝回家")
        self.assertEqual(entries[0]["description"], "")
        self.assertEqual(entries[0]["source_status"], "运行中")
        self.assertNotIn("3831", entries[0]["name"])
        self.assertEqual(entries[1]["id"], "60s")
        self.assertEqual(entries[1]["entry_url"], "https://60s.suyanw.cn/")
        self.assertIsNone(entries[1]["doc_url"])
        self.assertEqual(entries[2]["id"], "xjj")
        self.assertEqual(entries[2]["entry_url"], "https://api.suyanw.cn/api/xjj")

    def test_rejects_homepage_without_actual_tool_cards(self):
        with self.assertRaises(sync.CatalogError):
            sync.parse_homepage(b"<html><body><a href='/ad'>advertisement</a></body></html>")

    def test_keeps_document_slug_ids_stable_and_unique(self):
        duplicated = HOMEPAGE.replace(
            b"</body>",
            b'<div class="tool-card"><a href="doc/bb.php"><div class="tool-header">B B</div></a></div></body>',
        )

        entries = sync.parse_homepage(duplicated)

        self.assertEqual(entries[0]["id"], "bb")
        self.assertEqual(entries[-1]["id"], "bb-2")


class ParseDocumentTests(unittest.TestCase):
    def test_extracts_endpoint_method_response_and_separate_default_example(self):
        parsed = sync.parse_document(DOCUMENT)

        self.assertEqual(parsed["title"], "Demo API - Suyan")
        self.assertEqual(parsed["endpoint"], "https://api.suyanw.cn/api/demo.php")
        self.assertEqual(parsed["method"], "GET/POST")
        self.assertEqual(parsed["response_type"], "JSON")
        self.assertEqual(
            parsed["params"],
            [
                {
                    "name": "q",
                    "required": True,
                    "description": "查询内容",
                    "example": "hello",
                },
                {
                    "name": "format",
                    "required": False,
                    "description": "输出格式",
                    "default": "json",
                    "example": "xml",
                },
            ],
        )
        self.assertTrue(parsed["has_params_section"])

    def test_does_not_guess_missing_required_default_or_example_values(self):
        html = """<html><body>
          <p class="simpleTable">接口地址： /api/no-flags.php</p>
          <p class="simpleTable">返回格式： JSON</p>
          <p class="simpleTable">请求方式： GET</p>
          <p class="linep">请求参数说明：</p>
          <table><tr><th>名称</th><th>说明</th></tr>
            <tr><td>token</td><td>令牌</td></tr></table>
        </body></html>""".encode()

        parsed = sync.parse_document(html)

        self.assertEqual(parsed["params"], [{"name": "token", "required": None, "description": "令牌"}])

    def test_empty_parameter_table_is_distinct_from_missing_section(self):
        html = """<html><body>
          <p class="simpleTable">接口地址： https://api.suyanw.cn/api/empty.php</p>
          <p class="simpleTable">返回格式： 请看返回示例</p>
          <p class="simpleTable">请求方式： GET</p>
          <p class="linep">请求参数说明：</p>
          <table><tr><th>名称</th><th>必填</th><th>说明</th></tr></table>
        </body></html>""".encode()

        parsed = sync.parse_document(html)

        self.assertEqual(parsed["params"], [])
        self.assertTrue(parsed["has_params_section"])
        self.assertEqual(parsed["response_type"], "请看返回示例")

    def test_document_endpoint_is_parsed_but_never_treated_as_a_fetch_target(self):
        parsed = sync.parse_document(DOCUMENT)

        self.assertEqual(parsed["endpoint"], "https://api.suyanw.cn/api/demo.php")
        with self.assertRaises(sync.FetchError):
            sync._validate_fetch_url(parsed["endpoint"], kind="document")

    def test_document_html_size_is_bounded(self):
        with self.assertRaises(sync.CatalogError):
            sync.parse_document(b" " * (sync.MAX_DOCUMENT_BYTES + 1))


class OfflineCacheTests(unittest.TestCase):
    def test_transient_tls_failure_retries_the_document(self):
        doc_url = "https://api.suyanw.cn/doc/bb.php"
        with (
            tempfile.TemporaryDirectory(prefix="suyan_retry_test_") as temp_dir,
            mock.patch.object(sync, "REQUEST_START_INTERVAL_SECONDS", 0),
            mock.patch.object(
                sync,
                "_fetch_html",
                side_effect=[sync.FetchError("network error (SSLEOFError)"), (DOCUMENT, doc_url)],
            ) as fetch,
            mock.patch.object(sync.time, "sleep"),
        ):
            results, manifest = sync._fetch_document_set([doc_url], Path(temp_dir))

        self.assertEqual(fetch.call_count, 2)
        self.assertEqual(results[doc_url]["html"], DOCUMENT)
        self.assertIsNone(results[doc_url]["error"])
        self.assertEqual(manifest[0]["file"], "document-0001.html")

    def test_transient_http_5xx_retries_the_document(self):
        doc_url = "https://api.suyanw.cn/doc/bb.php"
        with (
            tempfile.TemporaryDirectory(prefix="suyan_retry_test_") as temp_dir,
            mock.patch.object(sync, "REQUEST_START_INTERVAL_SECONDS", 0),
            mock.patch.object(
                sync,
                "_fetch_html",
                side_effect=[sync.FetchError("HTTP 503"), (CATALOG_DOCUMENT, doc_url)],
            ) as fetch,
            mock.patch.object(sync.time, "sleep"),
        ):
            results, _ = sync._fetch_document_set([doc_url], Path(temp_dir))

        self.assertEqual(fetch.call_count, 2)
        self.assertEqual(results[doc_url]["html"], CATALOG_DOCUMENT)

    def test_previous_download_cache_rebuilds_without_network(self):
        with tempfile.TemporaryDirectory(prefix="suyan_test_cache_") as temp_dir:
            cache = Path(temp_dir)
            doc_url = "https://api.suyanw.cn/doc/bb.php"
            (cache / "homepage.html").write_bytes(HOMEPAGE)
            (cache / "document-0001.html").write_bytes(CATALOG_DOCUMENT)
            (cache / "manifest.json").write_text(
                json.dumps(
                    {
                        "source_url": "https://api.suyanw.cn/",
                        "fetched_at": "2026-11-26T00:00:00Z",
                        "documents": [
                            {
                                "url": doc_url,
                                "file": "document-0001.html",
                                "final_url": doc_url,
                                "error": None,
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            homepage, document_results, fetched_at = sync._load_offline_cache(cache)
            catalog = sync.build_catalog(
                homepage,
                document_results,
                fetched_at=fetched_at,
            )

        self.assertEqual(catalog["fetched_at"], "2026-11-26T00:00:00Z")
        self.assertEqual(catalog["entries"][0]["endpoint"], "https://api.suyanw.cn/api/demo.php")
        self.assertEqual(catalog["entries"][0]["parse_status"], "complete")


class CatalogSafetyTests(unittest.TestCase):
    def test_unrelated_template_footer_does_not_block_a_safe_documented_entry(self):
        doc_url = "https://api.suyanw.cn/doc/bb.php"
        unrelated_footer = (
            "<footer>IP信息查询 QQ空间说说评论 skey</footer>".encode()
        )
        html = CATALOG_DOCUMENT.replace(b"</body>", unrelated_footer + b"</body>")
        catalog = sync.build_catalog(HOMEPAGE, {doc_url: {"html": html}})

        self.assertEqual(catalog["entries"][0]["status"], "catalog_only")
        self.assertEqual(catalog["entries"][0]["availability"], "documented")

    def test_mismatched_document_title_is_catalog_only_and_not_used_for_safety(self):
        homepage = HOMEPAGE.replace(b"doc/bb.php", b"doc/kugouring.php").replace(
            "<span>宝</span> <span>宝贝回家</span>".encode(),
            "<span>酷</span> <span>酷狗铃声</span>".encode(),
        )
        wrong_title_document = CATALOG_DOCUMENT.replace(
            "宝贝回家API - Suyan".encode(),
            "QQ昵称查询API - Suyan".encode(),
        )
        doc_url = "https://api.suyanw.cn/doc/kugouring.php"
        catalog = sync.build_catalog(homepage, {doc_url: {"html": wrong_title_document}})

        self.assertEqual(catalog["entries"][0]["document_title"], "QQ昵称查询API - Suyan")
        self.assertEqual(catalog["entries"][0]["status"], "catalog_only")
        self.assertEqual(catalog["entries"][0]["parse_status"], "partial")
        self.assertEqual(catalog["entries"][0]["availability"], "document_incomplete")
        self.assertIn("名称不一致", catalog["entries"][0]["reason"])

    def test_sms_abuse_is_preserved_but_marked_blocked(self):
        unsafe_homepage = HOMEPAGE.replace(b"doc/bb.php", b"doc/sms.php").replace(
            "宝贝回家".encode(), "短信验证码轰炸".encode()
        )
        doc_url = "https://api.suyanw.cn/doc/sms.php"
        catalog = sync.build_catalog(
            unsafe_homepage,
            {doc_url: {"html": DOCUMENT}},
        )

        self.assertEqual(catalog["entries"][0]["id"], "sms")
        self.assertEqual(catalog["entries"][0]["status"], "blocked")
        self.assertEqual(catalog["entries"][0]["availability"], "blocked")
        self.assertIn("禁止执行", catalog["entries"][0]["reason"])

    def test_catalog_keeps_off_site_and_undocumented_entries_without_calling_them(self):
        doc_url = "https://api.suyanw.cn/doc/bb.php"
        catalog = sync.build_catalog(
            HOMEPAGE,
            {doc_url: {"html": CATALOG_DOCUMENT}},
            fetched_at="2026-11-26T00:00:00Z",
        )

        self.assertEqual(catalog["source_count"], 3)
        self.assertEqual(catalog["summary"]["homepage_entries"], 3)
        self.assertEqual(catalog["summary"]["unique_document_links"], 1)
        self.assertEqual(catalog["summary"]["documents_fetched"], 1)
        self.assertEqual(catalog["entries"][0]["availability"], "documented")
        self.assertEqual(catalog["entries"][0]["status"], "catalog_only")
        self.assertEqual(catalog["entries"][1]["availability"], "off_site")
        self.assertEqual(catalog["entries"][1]["parse_status"], "not_applicable")
        self.assertEqual(catalog["entries"][2]["availability"], "missing_documentation")
        json.dumps(catalog, ensure_ascii=False)

    def test_unavailable_document_is_explicit_and_does_not_drop_its_entry(self):
        doc_url = "https://api.suyanw.cn/doc/bb.php"
        catalog = sync.build_catalog(
            HOMEPAGE,
            {doc_url: {"html": None, "error": "HTTP 404"}},
        )

        self.assertEqual(len(catalog["entries"]), 3)
        self.assertEqual(catalog["entries"][0]["availability"], "document_unavailable")
        self.assertEqual(catalog["entries"][0]["parse_status"], "unavailable")
        self.assertIn("HTTP 404", catalog["entries"][0]["reason"])
        self.assertEqual(catalog["summary"]["documents_failed"], 1)

    def test_known_sms_qq_abuse_and_sensitive_queries_are_blocked(self):
        self.assertIn("禁止执行", sync._blocked_reason("短信验证码轰炸", "", None, "") or "")
        self.assertIn("禁止执行", sync._blocked_reason("QQ 群聊刷屏", "", None, "") or "")
        self.assertIn("社交写入", sync._blocked_reason("QQ亲密关系邀请", "", None, "") or "")
        self.assertIn("社交写入", sync._blocked_reason("QQ空间说说评论", "", None, "") or "")
        self.assertIn("会话密钥", sync._blocked_reason("QQ群列表", "", None, "required skey and pskey") or "")
        self.assertIn("目标 IP", sync._blocked_reason("IP实际地址查询", "", None, "") or "")
        self.assertIn("扫描", sync._blocked_reason("端口扫描", "", None, "") or "")
        self.assertIn("强制或批量", sync._blocked_reason("QQ强制加群", "", None, "") or "")
        self.assertIn("探测", sync._blocked_reason("网站状态码查询", "", None, "") or "")
        self.assertIn("敏感信息", sync._blocked_reason("手机号估价", "", None, "需要查询的手机号") or "")
        self.assertIn("账号资料", sync._blocked_reason("QQ昵称查询", "", None, "") or "")
        self.assertIn("敏感信息", sync._blocked_reason("身份证号码查询", "", None, "") or "")
        self.assertIsNone(sync._blocked_reason("天气查询", "", None, ""))

    def test_fetch_rules_reject_functional_endpoints_and_off_site_urls(self):
        blocked_urls = (
            "https://api.suyanw.cn/api/bb.php",
            "https://api.suyanw.cn/meinv",
            "https://evil.example/doc/x.php",
            "http://api.suyanw.cn/doc/bb.php",
            "https://api.suyanw.cn.evil.example/doc/bb.php",
            "https://api.suyanw.cn/doc/../api/action.php",
            "https://api.suyanw.cn/doc/%2e%2e/api/action.php",
            "https://api.suyanw.cn/doc/%252e%252e/api/action.php",
            "https://api.suyanw.cn/doc//action.php",
            "https://api.suyanw.cn/doc/action.php?next=/api/action.php",
        )
        for url in blocked_urls:
            with self.subTest(url=url), self.assertRaises(sync.FetchError):
                sync._validate_fetch_url(url, kind="document")
        self.assertEqual(
            sync._validate_fetch_url("https://api.suyanw.cn/doc/bb.php", kind="document"),
            "https://api.suyanw.cn/doc/bb.php",
        )

    def test_same_site_functional_routes_are_not_document_pages(self):
        self.assertFalse(sync._is_document_url("https://api.suyanw.cn/api/xjj"))
        self.assertFalse(sync._is_document_url("https://60s.suyanw.cn/"))


if __name__ == "__main__":
    unittest.main()
