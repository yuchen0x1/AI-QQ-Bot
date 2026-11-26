"""Behavioural/security tests for the isolated Suyan group-menu runtime."""

from __future__ import annotations

import asyncio
import json
import socket
import threading
from dataclasses import fields
from urllib.parse import parse_qs

import httpx
import pytest

from app.core import http as shared_http
from app.core.ssrf import OutboundTarget
from app.services import suyan
from app.services.bot_reply import BotReply
from app.services.suyan import SuyanService, _parameters

KEY = (1, 100, 200)


def api(identifier="echo", **overrides):
    value = {
        "id": identifier, "name": "文字查询", "description": "返回查询结果", "category": "工具",
        "doc_url": f"https://api.suyanw.cn/doc/{identifier}.html",
        "endpoint": f"https://api.suyanw.cn/api/{identifier}.php", "method": "GET",
        "executable": True, "verified": True, "parameters": [],
    }
    value.update(overrides)
    return value


@pytest.fixture
def runtime(tmp_path):
    instances = []

    def make(entries=None, **options):
        path = tmp_path / f"catalog-{len(instances)}.json"
        rows = entries if entries is not None else [api()]
        path.write_text(json.dumps({"apis": rows}, ensure_ascii=False), encoding="utf-8")
        approved = {}
        for row in rows:
            if row.get("executable") is not True or row.get("verified") is not True:
                continue
            request = row.get("request") if isinstance(row.get("request"), dict) else {}
            endpoint = request.get("url", request.get("endpoint", row.get("endpoint", row.get("api_url", ""))))
            doc_url = row.get("doc_url", row.get("documentation_url", row.get("detail_url", "")))
            method = str(request.get("method", row.get("method", "GET"))).upper()
            methods = set(__import__("re").split(r"\s*[/,|]\s*", method))
            if methods and methods <= {"GET", "POST"}:
                method = "GET" if "GET" in methods else "POST"
            params = request.get("parameters", request.get("params", row.get("parameters", row.get("params", []))))
            parsed_params, _ = _parameters(params)
            signature = tuple((item.name, item.required) for item in parsed_params)
            approved[str(row.get("id"))] = (doc_url, endpoint, method, signature)
        instance = SuyanService(path, reviewed_apis=options.pop("reviewed_apis", approved), **options)
        instances.append(instance)
        return instance

    yield make
    for instance in instances:
        for account in {key[0] for key in instance._sessions}:
            instance.clear_account(account)


@pytest.fixture(autouse=True)
def no_live_http():
    def unexpected(request):
        raise AssertionError(f"Unexpected outbound HTTP: {request.method} {request.url.host}")

    shared_http.set_transport(httpx.MockTransport(unexpected))
    yield
    shared_http.set_transport(None)


def transport(handler):
    shared_http.set_transport(httpx.MockTransport(handler))


def test_bot_reply_contract():
    result = BotReply("hello")
    assert [field.name for field in fields(result)] == ["text", "markdown", "keyboard"]
    assert result.text == "hello" and result.markdown is None and result.keyboard is None
    assert isinstance(suyan.suyan_service, SuyanService)


def test_full_catalogue_pagination_stable_ids_and_official_keyboard(runtime):
    service = runtime([api(f"tool-{i}", name=f"项目{i}") for i in range(19)])
    menu = service.build_menu(page=2, prefix="!")
    assert "第 2/3 页" in menu.text and "共 19 项" in menu.text
    rows = menu.keyboard["content"]["rows"]
    assert len(rows) == 5
    commands = []
    for row in rows:
        assert len(row["buttons"]) <= 5
        for button in row["buttons"]:
            action = button["action"]
            assert action["type"] == 2 and action["enter"] is True
            assert action["permission"] == {"type": 2}
            assert action["data"].startswith("!")
            commands.append(action["data"])
    assert commands[:8] == [f"!接口 tool-{i}" for i in range(8, 16)]
    assert "!菜单 1" in commands and "!菜单 3" in commands
    assert "9. 项目8" in menu.text and "16. 项目15" in menu.text
    assert menu.markdown["content"].startswith("## ")
    assert len(service.build_menu(99).keyboard["content"]["rows"][0]["buttons"]) == 2
    assert "第 1/3 页" in service.build_menu(-1).text


def test_search_is_case_insensitive_and_retains_global_numbering(runtime):
    service = runtime([api(f"x{i}", name=f"条目{i}") for i in range(8)] + [api("weather", name="城市天气 Weather")])
    menu = service.build_menu(query="WEATHER", prefix="/")
    assert "9. 城市天气" in menu.text and "当前匹配 1 项" in menu.text
    assert menu.keyboard["content"]["rows"][0]["buttons"][0]["action"]["data"] == "/接口 weather"
    assert "没有匹配" in service.build_menu(query="does not exist").text
    many = runtime([api(f"weather-{i}", name=f"天气{i}") for i in range(10)])
    navigation = many.build_menu(query="天气").keyboard["content"]["rows"][-1]["buttons"]
    assert "/菜单 2 天气" in [button["action"]["data"] for button in navigation]
    assert "下一页：/菜单 2 天气" in many.build_menu(query="天气").text


def test_search_page_commands_split_on_all_whitespace():
    from app.services.commands import _split_command

    assert _split_command("菜单 2 天气") == ("菜单", "2 天气")
    assert _split_command("菜单\t2\t天气") == ("菜单", "2\t天气")
    assert _split_command("菜单2") == ("菜单", "2")
    assert _split_command("功能菜单2") == ("功能菜单", "2")


@pytest.mark.parametrize("wrapper", [lambda rows: rows, lambda rows: {"entries": rows}, lambda rows: {"data": {"items": rows}}])
def test_compatible_catalogue_containers(runtime, wrapper):
    service = runtime()
    service.catalog_path.write_text(json.dumps(wrapper([api()])), encoding="utf-8")
    assert "文字查询" in service.build_menu().text


async def test_shipped_catalog_is_fail_closed_except_for_exact_reviewed_read_only_apis():
    service = SuyanService()
    assert "公开文档已解析" in (await service.execute("bb", "", KEY)).text
    assert "可调用" in service.build_menu(query="脑筋急转弯").text
    assert "仅文档（不可执行" in service.build_menu(query="宝贝回家").text


async def test_numeric_selection_and_stable_id_select_same_entry(runtime):
    calls = []

    def handle(request):
        calls.append(request.url.path)
        return httpx.Response(200, json={"result": "正常"})

    transport(handle)
    service = runtime([api("first"), api("weather", name="天气")])
    assert "正常" in (await service.execute("2", "", KEY)).text
    assert "正常" in (await service.execute("weather", "", KEY)).text
    assert calls == ["/api/weather.php", "/api/weather.php"]
    assert "不存在" in (await service.execute("0", "", KEY)).text
    assert "不存在" in (await service.execute("9999999999999999999999999", "", KEY)).text


@pytest.mark.parametrize("row,reason", [
    (api(name="短信轰炸", executable=True), "禁止执行"),
    (api(name="DDoS 测试", executable=True), "禁止执行"),
    (api(name="删除用户", method="GET"), "状态变更"),
    (api(side_effects=True), "状态变更"),
    (api(read_only=False), "状态变更"),
    (api(verified=False), "尚未通过本地安全审核"),
    (api(executable=False, blocked_reason="文档需要人工登录"), "人工登录"),
    (api(endpoint="https://evil.example/api/test.php"), "站外"),
    (api(endpoint="http://api.suyanw.cn/api/echo.php"), "站外"),
    (api(endpoint="https://api.suyanw.cn@evil.example/api/echo.php"), "站外"),
    (api(endpoint="https://api.suyanw.cn/api/%2e%2e/private"), "未验证"),
    (api(doc_url=""), "缺少接口文档"),
    (api(endpoint=""), "明确请求地址"),
    (api(method="DELETE"), "GET/POST"),
    (api(parameters=None), "缺少参数文档"),
    (api(parameters=[{"name": "api_key", "required": True}]), "凭据"),
    (api(parameters=[{"name": "host", "required": True}]), "覆盖请求目标"),
    (api(parameters=[{"name": "file", "type": "file"}]), "文件"),
])
async def test_unsafe_or_undocumented_entries_are_visible_but_never_requested(runtime, row, reason):
    service = runtime([row])
    assert "不可执行" in service.build_menu().text
    reply = await service.execute(row["id"], "", KEY)
    assert reason in reply.text
    assert "文档：" in reply.text
    if row["doc_url"]:
        assert row["doc_url"] in reply.text
    assert not service.has_session(KEY)


async def test_catalogue_reloads_fail_closed_and_does_not_keep_stale_permissions(runtime):
    service = runtime()
    assert "文字查询" in service.build_menu().text
    service.catalog_path.write_text("{broken-json", encoding="utf-8")
    assert "目录暂不可用" in service.build_menu().text
    assert "目录暂不可用" in (await service.execute("echo", "", KEY)).text
    service.catalog_path.write_text(json.dumps([api(executable=False)]), encoding="utf-8")
    assert "接口尚未通过本地安全审核" in service.build_menu().text
    assert "接口尚未通过本地安全审核" in (await service.execute("echo", "", KEY)).text
    assert not service.has_session(KEY)
    service.catalog_path.unlink()
    assert "目录暂不可用" in service.build_menu().text


async def test_shlex_named_positional_and_quoted_values(runtime):
    requests = []

    def handle(request):
        requests.append(request)
        return httpx.Response(200, text="ok", headers={"content-type": "text/plain"})

    transport(handle)
    service = runtime([api(parameters=[{"name": "q", "required": True}, {"name": "count", "type": "integer"}])])
    reply = await service.execute("echo", '"hello world" count=2', KEY)
    assert "ok" in reply.text
    assert dict(requests[-1].url.params) == {"q": "hello world", "count": "2"}
    assert "未记录" in (await service.execute("echo", "endpoint=https://evil.example", KEY)).text
    assert "重复" in (await service.execute("echo", "q=one q=two", KEY)).text
    assert "引号未闭合" in (await service.execute("echo", 'q="hello', KEY)).text
    assert "有效数字" in (await service.execute("echo", 'q=ok count=NaN', KEY)).text
    assert len(requests) == 1


async def test_required_parameters_are_prompted_one_at_a_time_and_natural_text_is_preserved(runtime):
    requests = []
    transport(lambda request: requests.append(request) or httpx.Response(200, json={"success": True}))
    service = runtime([api(parameters=[
        {"name": "city", "required": True, "description": "填写城市名称"},
        {"name": "days", "required": True, "type": "integer"},
    ])])
    first = await service.execute("echo", "", KEY, prefix="!")
    assert "参数 city" in first.text and "城市名称" in first.text and service.has_session(KEY)
    assert first.keyboard["content"]["rows"][0]["buttons"][0]["action"]["data"] == "!取消接口"
    second = await service.continue_session("New York", KEY)
    assert "参数 days" in second.text and not requests
    invalid = await service.continue_session("nonsense", KEY)
    assert "有效数字" in invalid.text and service.has_session(KEY)
    final = await service.continue_session("3", KEY)
    assert "success" in final.text and not service.has_session(KEY)
    assert dict(requests[0].url.params) == {"city": "New York", "days": "3"}
    assert await service.continue_session("later", KEY) is None


async def test_sessions_are_isolated_by_account_group_and_user(runtime):
    requests = []
    transport(lambda request: requests.append(request) or httpx.Response(200, text="done"))
    service = runtime([api(parameters=[{"name": "q", "required": True}])])
    keys = [KEY, (2, 100, 200), (1, 101, 200), (1, 100, 201)]
    for key in keys:
        assert "参数 q" in (await service.execute("echo", "", key)).text
    assert await service.continue_session("other", (9, 9, 9)) is None
    for i, key in enumerate(keys):
        assert "done" in (await service.continue_session(f"value-{i}", key)).text
    assert [request.url.params["q"] for request in requests] == [f"value-{i}" for i in range(4)]
    assert all(not service.has_session(key) for key in keys)


async def test_ttl_capacity_cancellation_and_account_cleanup(runtime):
    now = [100.0]
    service = runtime([api(parameters=[{"name": "q", "required": True}])], clock=lambda: now[0], session_ttl=10, max_sessions=2)
    one, two, three = KEY, (2, 100, 200), (1, 100, 201)
    await service.execute("echo", "", one)
    await service.execute("echo", "", two)
    assert "上限" in (await service.execute("echo", "", three)).text
    assert service.has_session(one) and service.has_session(two)
    assert "已取消" in service.cancel_session(one).text
    await service.execute("echo", "", three)
    service.clear_account(1)
    assert not service.has_session(three) and service.has_session(two)
    now[0] += 10
    assert not service.has_session(two)
    assert await service.continue_session("expired", two) is None
    assert "参数 q" in (await service.execute("echo", "", one)).text
    assert "已取消" in (await service.continue_session("/取消接口", one)).text
    assert not service.has_session(one)


async def test_session_rechecks_changed_catalogue(runtime):
    service = runtime([api(parameters=[{"name": "q", "required": True}])])
    await service.execute("echo", "", KEY)
    service.catalog_path.write_text(json.dumps([api(name="短信轰炸", parameters=[])]), encoding="utf-8")
    assert "目录已更新" in (await service.continue_session("hello", KEY)).text
    assert not service.has_session(KEY)


async def test_completed_new_selection_discards_older_pending_prompt(runtime):
    transport(lambda request: httpx.Response(200, text="ok"))
    service = runtime([api("pending", parameters=[{"name": "q", "required": True}]), api("ready")])
    await service.execute("pending", "", KEY)
    assert service.has_session(KEY)
    assert "ok" in (await service.execute("ready", "", KEY)).text
    assert not service.has_session(KEY)


async def test_parallel_requests_are_bounded_and_account_stop_cancels_inflight(runtime):
    entered = asyncio.Event()
    release = asyncio.Event()
    calls = []

    async def handle(request):
        calls.append(request)
        entered.set()
        await release.wait()
        return httpx.Response(200, text="finished")

    transport(handle)
    service = runtime(max_concurrent=1)
    task = asyncio.create_task(service.execute("echo", "", KEY))
    await asyncio.wait_for(entered.wait(), 1)
    assert service.has_session(KEY)
    assert "正在处理中" in (await service.execute("echo", "", KEY)).text
    assert "忙碌" in (await service.execute("echo", "", (2, 100, 200))).text
    service.clear_account(1)
    result = await asyncio.wait_for(task, 1)
    assert "已取消" in result.text and not service.has_session(KEY)
    release.set()
    assert "finished" in (await service.execute("echo", "", KEY)).text
    assert len(calls) == 2


async def test_total_timeout_releases_concurrency_and_never_retries(runtime):
    calls = []

    async def handle(request):
        calls.append(request)
        await asyncio.Event().wait()

    transport(handle)
    service = runtime(request_timeout=0.04, max_concurrent=1)
    assert "超时" in (await service.execute("echo", "", KEY)).text
    assert len(calls) == 1 and not service.has_session(KEY)
    transport(lambda request: httpx.Response(200, text="recovered"))
    assert "recovered" in (await service.execute("echo", "", KEY)).text


async def test_external_task_cancellation_is_propagated_and_releases_slot(runtime):
    entered = asyncio.Event()

    async def handle(request):
        entered.set()
        await asyncio.Event().wait()

    transport(handle)
    service = runtime(max_concurrent=1)
    task = asyncio.create_task(service.execute("echo", "", KEY))
    await asyncio.wait_for(entered.wait(), 1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert not service.has_session(KEY)


@pytest.mark.parametrize("url", [
    "http://127.0.0.1/admin", "http://169.254.169.254/latest/meta-data", "http://[::1]/", "http://2130706433/",
    "file:///etc/passwd", "gopher://127.0.0.1:6379/_x", "data:text/html,hello", "ftp://public.example/file",
    "https://user:password@public.example/image.png", "https%3A%2F%2F127.0.0.1%2Fsecret", "//127.0.0.1/path",
])
async def test_url_parameters_cannot_be_used_as_proxy_ssrf(runtime, url):
    service = runtime([api(parameters=[{"name": "url", "required": True, "type": "url"}])])
    result = await service.execute("echo", f"url={url}", KEY)
    assert "不安全" in result.text or "公开 HTTP(S)" in result.text
    assert not service.has_session(KEY)


async def test_url_parameter_rejects_mixed_public_and_private_dns_answers(runtime, monkeypatch):
    def resolve(host, port, *args, **kwargs):
        return [(socket.AF_INET, 1, 6, "", ("93.184.216.34", port)), (socket.AF_INET, 1, 6, "", ("10.1.2.3", port))]

    monkeypatch.setattr(socket, "getaddrinfo", resolve)
    service = runtime([api(parameters=[{"name": "url", "required": True, "type": "url"}])])
    assert "不安全" in (await service.execute("echo", "url=https://public.example/image.png", KEY)).text


@pytest.mark.parametrize("location", [
    "https://evil.example/api/echo.php", "http://api.suyanw.cn/api/echo.php", "http://127.0.0.1/x",
    "/api/other.php", "/api/%2e%2e/private", "https://user:secret@api.suyanw.cn/api/echo.php",
])
async def test_redirect_never_leaves_official_verified_path(runtime, location):
    calls = []
    transport(lambda request: calls.append(request) or httpx.Response(302, headers={"location": location}))
    service = runtime()
    result = await service.execute("echo", "", KEY)
    assert "站外" in result.text or "路径" in result.text
    assert len(calls) == 1


async def test_dns_rebinding_is_rechecked_at_every_redirect(runtime, monkeypatch):
    resolutions = []
    calls = []

    def resolve(host, port, *args, **kwargs):
        resolutions.append(host)
        ip = "93.184.216.34" if len(resolutions) == 1 else "127.0.0.1"
        return [(socket.AF_INET, 1, 6, "", (ip, port))]

    monkeypatch.setattr(socket, "getaddrinfo", resolve)
    transport(lambda request: calls.append(request) or httpx.Response(302, headers={"location": "/api/echo.php"}))
    result = await runtime().execute("echo", "", KEY)
    assert len(resolutions) == 2 and len(calls) == 1
    assert "不安全" in result.text


async def test_validated_target_is_passed_to_pinned_http_factory(runtime, monkeypatch):
    targets = []
    original = suyan.new_client

    def capture(**options):
        targets.append(options)
        return original(**options)

    monkeypatch.setattr(suyan, "new_client", capture)
    transport(lambda request: httpx.Response(200, text="ok"))
    assert "ok" in (await runtime().execute("echo", "", KEY)).text
    assert targets[0]["follow_redirects"] is False
    assert isinstance(targets[0]["target"], OutboundTarget)
    assert targets[0]["target"].host == "api.suyanw.cn"
    assert targets[0]["target"].addresses == ("93.184.216.34",)


async def test_redirect_limit_and_undocumented_redirect_parameters(runtime):
    calls = []
    transport(lambda request: calls.append(request) or httpx.Response(302, headers={"location": "/api/echo.php"}))
    result = await runtime(max_redirects=2).execute("echo", "", KEY)
    assert "次数超过" in result.text and len(calls) == 3
    transport(lambda request: httpx.Response(302, headers={"location": "/api/echo.php?url=http://127.0.0.1"}))
    assert "未记录" in (await runtime().execute("echo", "", KEY)).text


@pytest.mark.parametrize("body_format", ["form", "json"])
async def test_documented_post_is_encoded_correctly_without_automatic_retry(runtime, body_format):
    requests = []
    transport(lambda request: requests.append(request) or httpx.Response(200, json={"ok": True}))
    service = runtime([api(method="POST", body_format=body_format, parameters=[{"name": "q", "required": True}])])
    assert "true" in (await service.execute("echo", 'q="hello world"', KEY)).text
    request = requests[0]
    assert request.method == "POST" and not request.url.query
    if body_format == "json":
        assert json.loads(request.content) == {"q": "hello world"}
    else:
        assert parse_qs(request.content.decode()) == {"q": ["hello world"]}
    transport(lambda request: httpx.Response(302, headers={"location": "/api/echo.php"}))
    assert "重定向方式未经确认" in (await service.execute("echo", "q=hello", KEY)).text


class Stream(httpx.AsyncByteStream):
    def __init__(self, chunks):
        self.chunks = chunks
        self.closed = False
        self.read_count = 0

    async def __aiter__(self):
        for chunk in self.chunks:
            self.read_count += 1
            yield chunk

    async def aclose(self):
        self.closed = True


async def test_stream_size_limit_stops_reading_and_closes_response(runtime):
    stream = Stream([b"x" * 8192] * 20)
    transport(lambda request: httpx.Response(200, stream=stream, headers={"content-type": "text/plain"}))
    result = await runtime(max_response_bytes=100).execute("echo", "", KEY)
    assert "大小限制" in result.text
    assert stream.closed and stream.read_count < 20


async def test_content_length_rejected_before_body_read(runtime):
    stream = Stream([b"hello"])
    transport(lambda request: httpx.Response(200, stream=stream, headers={"content-length": "999999", "content-type": "text/plain"}))
    assert "大小限制" in (await runtime(max_response_bytes=100).execute("echo", "", KEY)).text
    assert stream.closed and stream.read_count == 0


@pytest.mark.parametrize("content_type,body", [
    ("text/html", b"<html><script>alert(1)</script></html>"),
    ("text/plain", b"<script>alert(1)</script>"),
    ("application/json", b'{"result":"<img src=x onerror=alert(1)>"}'),
    ("image/svg+xml", b"<svg onload=alert(1)></svg>"),
    ("application/octet-stream", b"\x00binary"),
])
async def test_html_executable_content_and_unknown_binary_are_not_rendered(runtime, content_type, body):
    transport(lambda request: httpx.Response(200, content=body, headers={"content-type": content_type}))
    reply = await runtime().execute("echo", "", KEY)
    assert "隐藏" in reply.text or "不支持" in reply.text
    assert "alert(1)" not in reply.text and "<script>" not in json.dumps(reply.markdown)


async def test_json_media_links_are_validated_and_credentials_redacted(runtime):
    transport(lambda request: httpx.Response(200, json={
        "data": {"image": "https://images.example/a.png", "video": "https://video.example/movie.mp4"},
        "private": "http://169.254.169.254/latest", "token": "credential-do-not-leak",
        "message": "api_key=do-not-print", "signed": "https://images.example/a.png?token=private-token",
    }))
    result = await runtime().execute("echo", "", KEY)
    assert "图片链接：https://images.example/a.png" in result.text
    assert "视频链接：https://video.example/movie.mp4" in result.text
    assert "169.254.169.254" not in result.text
    assert "credential-do-not-leak" not in result.text and "do-not-print" not in result.text and "private-token" not in result.text


@pytest.mark.parametrize("content_type,label", [("image/png", "图片链接"), ("video/mp4", "视频链接")])
async def test_direct_media_returns_link_without_downloading_media(runtime, content_type, label):
    stream = Stream([b"do not download"])
    transport(lambda request: httpx.Response(200, stream=stream, headers={"content-type": content_type}))
    reply = await runtime().execute("echo", "", KEY)
    assert f"{label}：https://api.suyanw.cn/api/echo.php" in reply.text
    assert stream.closed and stream.read_count == 0


@pytest.mark.parametrize("failure", [httpx.ConnectError("token=secret-stack"), httpx.ReadTimeout("token=secret-stack")])
async def test_upstream_exceptions_do_not_leak_details_or_retry(runtime, failure):
    calls = []

    def handle(request):
        calls.append(request)
        raise failure

    transport(handle)
    reply = await runtime().execute("echo", "", KEY)
    assert "secret-stack" not in reply.text and "Traceback" not in reply.text
    assert "失败" in reply.text or "超时" in reply.text
    assert len(calls) == 1


async def test_invalid_session_identity_is_rejected_without_request(runtime):
    result = await runtime().execute("echo", "", ("1", 2, 3))
    assert "会话标识无效" in result.text


async def test_schema_one_documented_entries_execute_without_fabricated_probe_flags(runtime):
    requests = []
    transport(lambda request: requests.append(request) or httpx.Response(200, json={"answer": "真实文档约定"}))
    entry = {
        "id": "schema-one", "name": "文档示例", "description": "返回文字", "doc_url": "https://api.suyanw.cn/doc/word.php",
        "entry_url": "https://api.suyanw.cn/doc/word.php", "endpoint": "api/word.php", "method": "GET/POST",
        "response_type": "JSON", "params": [{"name": "text", "required": True, "description": "输入文字"}],
        "status": "catalog_only", "source_status": "运行中", "availability": "documented", "parse_status": "complete",
        "reason": "公开文档已解析；功能接口未被调用。",
    }
    service = runtime([entry], reviewed_apis={
        "schema-one": ("https://api.suyanw.cn/doc/word.php", "api/word.php", "GET", (("text", True),)),
    })

    service.catalog_path.write_text(json.dumps({"schema_version": 1, "entries": [entry]}), encoding="utf-8")
    assert "可调用" in service.build_menu().text
    assert "参数 text" in (await service.execute("schema-one", "", KEY)).text
    assert "真实文档约定" in (await service.continue_session("hello: world", KEY)).text
    assert requests[0].method == "GET" and requests[0].url.path == "/api/word.php"


@pytest.mark.parametrize("changes,reason", [
    ({"status": "blocked", "reason": "涉及敏感信息查询，禁止执行"}, "禁止执行"),
    ({"availability": "blocked", "reason": "来源禁止执行"}, "禁止执行"),
    ({"source_status": "维护中"}, "维护中"),
    ({"parameters": [{"name": "q", "required": None}]}, "必填的文档不完整"),
])
async def test_source_block_flags_and_unknown_requiredness_cannot_be_bypassed(runtime, changes, reason):
    service = runtime([api(**changes)])
    assert reason in (await service.execute("echo", "", KEY)).text


async def test_slow_dns_workers_remain_bounded_after_request_timeout(runtime, monkeypatch):
    release = threading.Event()
    entered = threading.Event()
    calls = []
    original = suyan.resolve_outbound_target

    def slow(*args, **kwargs):
        calls.append(args[0])
        entered.set()
        release.wait(2)
        return original(*args, **kwargs)

    monkeypatch.setattr(suyan, "resolve_outbound_target", slow)
    service = runtime(request_timeout=0.04, max_concurrent=1)
    try:
        assert "超时" in (await service.execute("echo", "", KEY)).text
        assert entered.is_set()
        assert "DNS 校验正在忙碌" in (await service.execute("echo", "", KEY)).text
        assert len(calls) == 1
    finally:
        release.set()
        if service._dns_jobs:
            await asyncio.wait_for(asyncio.gather(*tuple(service._dns_jobs), return_exceptions=True), 1)


async def test_compressed_response_is_rejected_before_decompression(runtime):
    stream = Stream([b"not even valid gzip"])
    requests = []
    transport(lambda request: requests.append(request) or httpx.Response(200, stream=stream, headers={"content-encoding": "gzip", "content-type": "text/plain"}))
    reply = await runtime(max_response_bytes=100).execute("echo", "", KEY)
    assert "解压缩超限" in reply.text
    assert requests[0].headers["accept-encoding"] == "identity"
    assert stream.read_count == 0 and stream.closed


async def test_documented_defaults_and_fixed_query_keep_their_request_locations(runtime):
    requests = []
    transport(lambda request: requests.append(request) or httpx.Response(200, text="ok"))
    service = runtime([api(
        method="POST", endpoint="https://api.suyanw.cn/api/echo.php?format=json",
        parameters=[{"name": "q", "required": True, "default": "documented"}, {"name": "format", "default": "json"}],
    )])
    assert "ok" in (await service.execute("echo", "", KEY)).text
    assert dict(requests[0].url.params) == {"format": "json"}
    assert parse_qs(requests[0].content.decode()) == {"q": ["documented"]}


async def test_duplicate_stable_ids_are_disabled_even_when_chosen_by_number(runtime):
    service = runtime([api("duplicate"), api("duplicate", name="另一个项目")])
    assert "稳定 ID 重复" in service.build_menu().text
    assert "稳定 ID 重复" in (await service.execute("1", "", KEY)).text
    assert "重复" in (await service.execute("duplicate", "", KEY)).text


async def test_blocked_document_urls_do_not_expose_credentials(runtime):
    service = runtime([api(executable=False, doc_url="https://user:very-private@api.suyanw.cn/doc/x.php?token=secret-document")])
    reply = await service.execute("echo", "", KEY)
    assert "very-private" not in reply.text and "secret-document" not in reply.text
    assert "敏感链接已隐藏" in reply.text


async def test_explicit_no_parameter_document_placeholder_is_supported(runtime):
    transport(lambda request: httpx.Response(200, text="无需参数的结果"))
    service = runtime([api(parameters=[{"name": "无", "required": None, "description": "无"}])])
    assert "可调用" in service.build_menu().text
    assert "无需参数的结果" in (await service.execute("echo", "", KEY)).text
    script = runtime([api(endpoint="https://api.suyanw.cn/api/component.js", parameters=[{"name": "无", "required": None, "description": "无"}])])
    assert "前端组件" in (await script.execute("echo", "", KEY)).text


@pytest.mark.parametrize("name", ["Skey", "Pskey", "p_skey", "pwd", "key", "jwt"])
async def test_credentials_are_never_prompted_for_even_under_legacy_names(runtime, name):
    service = runtime([api(parameters=[{"name": name, "required": True}])])
    result = await service.execute("echo", "", KEY)
    assert "凭据" in result.text and not service.has_session(KEY)


def test_missing_catalogue_explains_unavailability(tmp_path):
    assert "目录暂不可用" in SuyanService(tmp_path / "missing.json").build_menu().text


def test_catalogue_text_cannot_inject_native_markdown(runtime):
    service = runtime([api(name="[点我](javascript:alert(1)) <script>x</script>")])
    menu = service.build_menu()
    assert "<script>" not in menu.text
    assert "\\[" in menu.markdown["content"]
