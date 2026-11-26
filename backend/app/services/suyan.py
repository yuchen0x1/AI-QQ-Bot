"""Bounded, transport-independent runtime for the reviewed Suyan API catalogue.

Catalogue metadata is never permission to pick a new host. Only explicitly
reviewed, documented HTTPS paths on api.suyanw.cn can execute. Sessions are
process-local and deliberately short lived; no account, adapter or DB is used.
"""

from __future__ import annotations

import asyncio
import hashlib
import html
import ipaddress
import json
import re
import shlex
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, unquote, urlencode, urljoin, urlsplit, urlunsplit

import httpx

from app.core.http import new_client
from app.core.ssrf import OutboundTarget, OutboundURLError, resolve_outbound_target
from app.services.bot_reply import BotReply

API_ORIGIN = "https://api.suyanw.cn"
CATALOG_PATH = Path(__file__).resolve().parents[1] / "catalog" / "suyan_apis.json"
PAGE_SIZE = 8
SessionKey = tuple[int, int, int]
_REVIEWED_APIS = {
    "naowan": ("https://api.suyanw.cn/doc/naowan.php", "https://api.suyanw.cn/api/naowan.php", "GET", ()),
    "duanzi": ("https://api.suyanw.cn/doc/duanzi.php", "https://api.suyanw.cn/api/duanzi.php", "GET", ()),
}

_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_.-]{0,63}$")
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,79}$")
_HTML = re.compile(r"<\s*(?:!doctype\b|/?[a-z][a-z0-9:-]*(?:\s|/?>))", re.I)
_URL = re.compile(r"https?://[^\s<>\"'`]+", re.I)
_SECRET = re.compile(r"(?:password|passwd|secret|token|authorization|cookie|credential|api[_-]?key|access[_-]?key|signature|^key$|^pwd$|(?:^|_)p?skey$|^auth$|^sign$|^jwt$|session[_-]?id)", re.I)
_SECRET_TEXT = re.compile(
    r"(?i)\b(password|passwd|pwd|secret|(?:access[_-]?)?token|api[_-]?key|authorization|cookie|p_?skey|skey|key|sign|auth|jwt|session[_-]?id)"
    r"\s*[:=]\s*(?:\"[^\"]*\"|'[^']*'|(?:bearer|basic)\s+[^\s,;]+|[^\s,;\"'<>]+)"
)
_FORBIDDEN_NAMES = {"endpoint", "host", "hostname", "base_url", "baseurl", "proxy", "headers", "method"}
_URL_NAMES = {"url", "uri", "link", "src", "target", "image", "img", "pic", "video", "avatar", "website", "resource"}
_DANGER = re.compile(
    r"攻击|轰炸|爆破|洪泛|短信发送|发送短信|短信接口|短信验证码|刷赞|刷量|刷屏|刷访问|刷人气|"
    r"盗号|木马|钓鱼|开盒|人肉|查户籍|手机号定位|漏洞利用|端口扫描|远程命令|任意文件|"
    r"(?:\bddos\b|\bdos\b|\bsms\b|smsbomb|flood|stress.?test|cc.?attack|brute.?force)",
    re.I,
)
_WRITE = re.compile(
    r"删除|写入|上传|注册|登录|签到|点赞|评论|邀请|修改|发布|设置|注销|开通|发信|发送邮件|发送消息|群发|加群|退群|绑定|解绑|支付|下单|充值|转账|投票|发帖|"
    r"(?:^|[/_.-])(?:delete|remove|update|write|upload|register|login|send|pay|vote|follow|like|comment|checkin|insert)(?:[/_.-]|$)",
    re.I,
)
_MEDIA_IMAGE = {"image/jpeg", "image/png", "image/gif", "image/webp", "image/avif", "image/bmp"}
_REDIRECTS = {301, 302, 303, 307, 308}


class _Rejected(ValueError):
    """Safe, fixed user-facing error; never contains upstream exception text."""


def _clean(value: Any, limit: int = 200) -> str:
    text = str(value if value is not None else "")
    text = "".join(char for char in text if char in "\n\t" or ord(char) >= 32)
    text = re.sub(r"[\x7f-\x9f\u200b-\u200f\u202a-\u202e\u2066-\u2069]", "", text)
    return text[:limit]


def _label(value: Any, limit: int = 100) -> str:
    return re.sub(r"<[^>]*>", "", html.unescape(_clean(value, limit * 2))).replace("\n", " ").strip()[:limit]


def _md(text: str) -> str:
    text = html.escape(text, quote=False)
    return re.sub(r"([\\`*_{}\[\]()#+.!|>~-])", r"\\\1", text)


def _redact_text(text: str) -> str:
    for match in reversed(list(_URL.finditer(text))):
        try:
            parsed = urlsplit(match.group(0))
            sensitive = parsed.username or parsed.password or any(_SECRET.search(key) for key, _ in parse_qsl(parsed.query, max_num_fields=64))
        except ValueError:
            sensitive = True
        if sensitive:
            text = text[:match.start()] + "[敏感链接已隐藏]" + text[match.end():]
    return _SECRET_TEXT.sub(r"\1=[已隐藏]", text)


def _reply(text: str, keyboard: dict | None = None) -> BotReply:
    text = _redact_text(text)
    if len(text) > 6000:
        text = text[:5960] + "\n[结果过长，已截断]"
    return BotReply(text=text, markdown={"content": _md(text)}, keyboard=keyboard)


def _prefix(value: str) -> str:
    return value if isinstance(value, str) and 0 < len(value) <= 16 and not any(c.isspace() or ord(c) < 32 for c in value) else "/"


def _button(label: str, command: str) -> dict:
    return {
        "render_data": {"label": label[:40], "visited_label": label[:40], "style": 1},
        "action": {"type": 2, "permission": {"type": 2}, "data": command, "enter": True},
    }


def _cancel_keyboard(prefix: str) -> dict:
    return {"content": {"rows": [{"buttons": [_button("取消接口", f"{prefix}取消接口")]}]}}


def _official_url(value: str, *, endpoint: bool = False) -> str:
    """Syntactic origin/path check, separate from per-request DNS checks."""
    if not value or len(value) > 8192 or any(c.isspace() or ord(c) < 32 for c in value) or "\\" in value:
        raise _Rejected("接口地址格式不安全")
    if value.startswith("/") and not value.startswith("//"):
        value = API_ORIGIN + value
    elif endpoint and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_./-]*", value):
        value = API_ORIGIN + "/" + value
    try:
        parsed = urlsplit(value)
        valid = (
            parsed.scheme == "https" and parsed.hostname == "api.suyanw.cn"
            and parsed.port in (None, 443) and not parsed.username and not parsed.password and not parsed.fragment
        )
    except ValueError:
        valid = False
    if not valid:
        raise _Rejected("站外入口或非官方 HTTPS 来源，仅提供文档")
    path = parsed.path or "/"
    if "%" in path or "//" in path or any(part in {".", ".."} for part in path.split("/")) or ";" in path:
        raise _Rejected("接口路径未通过安全校验")
    if endpoint and path == "/":
        raise _Rejected("缺少明确的已验证请求路径")
    return urlunsplit(("https", "api.suyanw.cn", path, parsed.query, ""))


@dataclass(frozen=True, slots=True)
class _Parameter:
    name: str
    required: bool = False
    description: str = ""
    kind: str = "string"
    default: str | None = None
    choices: tuple[str, ...] = ()
    is_url: bool = False


@dataclass(frozen=True, slots=True)
class _Entry:
    id: str
    name: str
    description: str
    category: str
    doc_url: str
    endpoint: str
    method: str
    parameters: tuple[_Parameter, ...]
    reason: str
    body_format: str = "form"
    response_type: str = "auto"


@dataclass(slots=True)
class _Session:
    entry: _Entry
    values: dict[str, str]
    expires_at: float


@dataclass(slots=True)
class _Run:
    task: asyncio.Task | None
    cancelled: bool = False


def _parameters(raw: Any) -> tuple[tuple[_Parameter, ...], str]:
    if raw is None:
        return (), "缺少参数文档，暂不可执行"
    if isinstance(raw, Mapping):
        raw = [dict(item, name=name) if isinstance(item, Mapping) else {"name": name, "description": item}
               for name, item in raw.items()]
    if not isinstance(raw, list) or len(raw) > 32:
        return (), "参数文档格式不受支持"
    no_parameters = {"无", "无参数", "无需参数", "不需要", "none", "n/a", "-", "—"}
    if len(raw) == 1 and isinstance(raw[0], Mapping):
        placeholder = raw[0]
        if (str(placeholder.get("name", "")).strip().lower() in no_parameters
                and str(placeholder.get("description", placeholder.get("desc", "无"))).strip().lower() in no_parameters
                and placeholder.get("required") in (None, False, 0, "false", "否")
                and placeholder.get("default") in (None, "")):
            return (), ""
    result = []
    for item in raw:
        if not isinstance(item, Mapping):
            return (), "参数文档不完整"
        name = str(item.get("name", item.get("key", "")))
        if not _NAME.fullmatch(name) or name in {param.name for param in result}:
            return (), "参数名称无效或重复"
        if name.lower() in _FORBIDDEN_NAMES or _SECRET.search(name):
            return (), "需要凭据或可覆盖请求目标的参数，暂不可执行"
        required = item.get("required", False)
        if not isinstance(required, (bool, int, str)) or required not in (True, False, 1, 0, "true", "false", "yes", "no", "是", "否", "必填", "可选", "required", "optional"):
            return (), "参数是否必填的文档不完整，暂不可执行"
        kind = str(item.get("type", item.get("kind", "string"))).lower()
        if kind in {"file", "binary", "multipart", "object", "array", "header", "cookie"}:
            return (), "需要文件、复杂请求体或凭据，暂不可执行"
        default = item.get("default")
        if default is not None and not isinstance(default, (str, int, float, bool)):
            return (), "参数默认值文档不完整"
        choices = item.get("enum", item.get("choices", []))
        if not isinstance(choices, (list, tuple)) or any(not isinstance(v, (str, int, float, bool)) for v in choices):
            return (), "参数枚举文档不完整"
        result.append(_Parameter(
            name=name, required=required in (True, 1, "true", "yes", "是", "必填", "required"),
            description=_label(item.get("description", item.get("desc", "")), 180), kind=kind,
            default=str(default) if default is not None else None, choices=tuple(str(v) for v in choices),
            is_url=item.get("is_url") is True or kind in {"url", "uri"} or str(item.get("format", "")).lower() in {"url", "uri"},
        ))
    return tuple(result), ""


def _entry(raw: Mapping, reviewed_apis: Mapping[str, tuple] = _REVIEWED_APIS) -> _Entry:
    request = raw.get("request") if isinstance(raw.get("request"), Mapping) else {}
    name = _label(raw.get("name", raw.get("title", "未命名接口")))
    description = _label(raw.get("description", raw.get("desc", "")), 240)
    category = _label(raw.get("category", ""))
    doc_url = _clean(raw.get("doc_url", raw.get("documentation_url", raw.get("detail_url", ""))), 2000).strip()
    endpoint = str(request.get("url", request.get("endpoint", raw.get("endpoint", raw.get("api_url", "")))) or "")
    identifier = str(raw.get("id", raw.get("stable_id", "")))
    if not _ID.fullmatch(identifier):
        identifier = "suyan-" + hashlib.sha256(f"{name}\n{doc_url}\n{endpoint}".encode()).hexdigest()[:12]
    elif identifier.isdecimal():
        identifier = "suyan-" + identifier
    method = str(request.get("method", raw.get("method", "GET"))).upper()
    methods = set(re.split(r"\s*[/,|]\s*", method))
    if methods and methods <= {"GET", "POST"}:
        method = "GET" if "GET" in methods else "POST"
    parameters, reason = _parameters(request.get("parameters", request.get("params", raw.get("parameters", raw.get("params")))))
    explicit_reason = _label(raw.get("blocked_reason", raw.get("unavailable_reason", raw.get("reason", ""))), 200)
    approved = reviewed_apis.get(identifier)
    reviewed_parameters = tuple((param.name, param.required) for param in parameters)
    catalog_disabled = raw.get("executable") is False or raw.get("verified") is False
    if catalog_disabled and explicit_reason and not reason:
        reason = explicit_reason
    verified = bool(
        not catalog_disabled
        and approved
        and (doc_url, endpoint, method, reviewed_parameters) == approved
    )
    executable = verified
    risk = str(raw.get("risk", raw.get("safety", ""))).lower()
    if raw.get("status") == "blocked" or raw.get("availability") == "blocked":
        reason = explicit_reason or "目录已标记危险，禁止执行"
    elif raw.get("dangerous") is True or raw.get("unsafe") is True or risk in {"dangerous", "unsafe", "blocked", "high", "attack"} or _DANGER.search(
        " ".join((name, description, category, endpoint, identifier, explicit_reason))
    ):
        reason = "涉及攻击、骚扰或未经授权操作，禁止执行"
    elif raw.get("side_effects") is True or raw.get("read_only") is False or raw.get("write_operation") is True or _WRITE.search(" ".join((name, description, endpoint))):
        reason = "涉及写入、账号或外部状态变更，群内暂不可执行"
    elif raw.get("source_status") in {"维护中", "维护", "已下线", "停用", "暂停", "异常", "不可用"}:
        reason = f"来源标记为{raw['source_status']}，暂不可执行"
    elif reason:
        pass
    elif not doc_url:
        reason = "缺少接口文档，暂不可执行"
    elif not endpoint:
        reason = "文档未给出明确请求地址，暂不可执行"
    elif method not in {"GET", "POST"}:
        reason = "仅支持已验证的 GET/POST 接口"
    else:
        try:
            _official_url(doc_url)
            endpoint = _official_url(endpoint, endpoint=True)
            fixed = parse_qsl(urlsplit(endpoint).query, keep_blank_values=True, max_num_fields=32)
            known = {param.name for param in parameters}
            if any(key not in known or _SECRET.search(key) for key, _ in fixed):
                raise _Rejected("请求地址携带未记录或敏感参数")
        except (ValueError, _Rejected):
            reason = "站外入口、未验证路径或请求地址不安全，仅提供文档"
    if not reason and not executable:
        reason = explicit_reason or "接口尚未通过本地安全审核，仅提供文档"
    body_format = str(request.get("body_format", request.get("encoding", raw.get("body_format", "form")))).lower()
    if body_format in {"application/json", "json"}:
        body_format = "json"
    elif body_format in {"application/x-www-form-urlencoded", "form", "query", "params"}:
        body_format = "form"
    elif not reason:
        reason = "请求体格式未获文档确认"
    response = raw.get("response") if isinstance(raw.get("response"), Mapping) else {}
    response_type = str(raw.get("response_type", response.get("type", "auto"))).lower()
    if not reason and (re.search(r"\b(?:html|javascript|ecmascript|svg)\b", response_type)
                       or urlsplit(endpoint).path.lower().endswith((".js", ".html", ".htm", ".svg", ".css"))):
        reason = "返回 HTML、脚本或前端组件，不支持群内执行"
    return _Entry(identifier, name, description, category, doc_url, endpoint, method, parameters, reason,
                  body_format, response_type)


class SuyanService:
    """One bounded in-memory runtime; integer keys are global catalogue positions."""

    def __init__(
        self, catalog_path: str | Path | None = None, *, session_ttl: float = 180,
        max_sessions: int = 256, max_concurrent: int = 4, request_timeout: float = 15,
        max_response_bytes: int = 512 * 1024, max_redirects: int = 2,
        clock: Callable[[], float] = time.monotonic,
        reviewed_apis: Mapping[str, tuple] | None = None,
    ) -> None:
        self.catalog_path = Path(catalog_path) if catalog_path is not None else CATALOG_PATH
        self.session_ttl = max(0.01, session_ttl)
        self.max_sessions = max(1, max_sessions)
        self.max_concurrent = max(1, max_concurrent)
        self.request_timeout = max(0.01, request_timeout)
        self.max_response_bytes = max(1, max_response_bytes)
        self.max_redirects = max(0, min(max_redirects, 5))
        self._clock = clock
        self._reviewed_apis = dict(_REVIEWED_APIS if reviewed_apis is None else reviewed_apis)
        self._sessions: dict[SessionKey, _Session] = {}
        self._runs: dict[SessionKey, _Run] = {}
        self._dns_jobs: set[asyncio.Task] = set()
        self._lock = threading.RLock()
        self._signature: tuple[int, int] | None = None
        self._entries: tuple[_Entry, ...] = ()
        self._catalog_error = ""

    def _catalog(self) -> tuple[_Entry, ...]:
        try:
            stat = self.catalog_path.stat()
            signature = (stat.st_mtime_ns, stat.st_size)
            if signature == self._signature:
                return self._entries
            if stat.st_size > 5 * 1024 * 1024:
                raise ValueError("catalogue too large")
            data = json.loads(self.catalog_path.read_text(encoding="utf-8-sig"))
            for _ in range(3):
                if not isinstance(data, Mapping):
                    break
                data = next((data[key] for key in ("apis", "entries", "items", "catalog", "data") if key in data), None)
            if not isinstance(data, list) or len(data) > 10000 or any(not isinstance(row, Mapping) for row in data):
                raise ValueError("unsupported catalogue")
            entries = tuple(_entry(row, self._reviewed_apis) for row in data)
            counts: dict[str, int] = {}
            for entry in entries:
                counts[entry.id] = counts.get(entry.id, 0) + 1
            entries = tuple(replace(entry, reason="目录稳定 ID 重复，暂不可执行") if counts[entry.id] > 1 else entry for entry in entries)
            self._entries, self._signature, self._catalog_error = entries, signature, ""
        except (OSError, ValueError, TypeError, RecursionError):
            # Never retain a previously executable catalogue after a failed reload.
            self._entries, self._signature = (), None
            self._catalog_error = "接口目录暂不可用，请稍后重试。"
        return self._entries

    def build_menu(self, page: int = 1, query: str = "", prefix: str = "/") -> BotReply:
        prefix = _prefix(prefix)
        entries = self._catalog()
        if self._catalog_error:
            return _reply(self._catalog_error)
        query = _label(query, 80)
        terms = query.casefold().split()
        selected = [(i, entry) for i, entry in enumerate(entries, 1) if all(
            term in " ".join((entry.id, entry.name, entry.description, entry.category)).casefold() for term in terms
        )]
        pages = max(1, (len(selected) + PAGE_SIZE - 1) // PAGE_SIZE)
        try:
            page = max(1, min(int(page), pages))
        except (TypeError, ValueError, OverflowError):
            page = 1
        lines = [f"素颜 API 功能菜单 · 第 {page}/{pages} 页", f"共 {len(entries)} 项；当前匹配 {len(selected)} 项"]
        if query:
            lines.append(f"搜索：{query}")
        visible = selected[(page - 1) * PAGE_SIZE:page * PAGE_SIZE]
        buttons = []
        for number, entry in visible:
            if entry.reason:
                state = f"仅文档（不可执行：{_label(entry.reason, 80)}）"
            else:
                state = "可调用"
            lines.append(f"{number}. {entry.name} [{entry.id}] · {state}")
            buttons.append(_button(f"{number}. {entry.name}", f"{prefix}接口 {entry.id}"))
        if not visible:
            lines.append("没有匹配的接口，请换个关键词。")
        lines.extend((f"调用：{prefix}接口 编号或ID [参数名=值]", f"搜索：{prefix}搜索接口 关键词"))
        suffix = f" {query}" if query else ""
        if page > 1:
            lines.append(f"上一页：{prefix}菜单 {page - 1}{suffix}")
        if page < pages:
            lines.append(f"下一页：{prefix}菜单 {page + 1}{suffix}")
        rows = [{"buttons": buttons[i:i + 2]} for i in range(0, len(buttons), 2)]
        navigation = []
        if page > 1:
            navigation.append(_button("上一页", f"{prefix}菜单 {page - 1}{suffix}"))
        navigation.append(_button(f"第 {page}/{pages} 页", f"{prefix}菜单 {page}{suffix}"))
        if page < pages:
            navigation.append(_button("下一页", f"{prefix}菜单 {page + 1}{suffix}"))
        if query:
            navigation.append(_button("全部接口", f"{prefix}菜单 1"))
        rows.append({"buttons": navigation})
        text = _redact_text("\n".join(lines))
        return BotReply(text, {"content": "## " + _md(text)}, {"content": {"rows": rows}})

    def _prune(self) -> None:
        now = self._clock()
        for key in [key for key, session in self._sessions.items() if session.expires_at <= now and key not in self._runs]:
            self._sessions.pop(key, None)

    def has_session(self, session_key: SessionKey) -> bool:
        with self._lock:
            self._prune()
            return session_key in self._sessions or session_key in self._runs

    def cancel_session(self, session_key: SessionKey) -> BotReply:
        with self._lock:
            self._prune()
            session = self._sessions.pop(session_key, None)
            run = self._runs.get(session_key)
            if run:
                run.cancelled = True
                task = run.task
                if task and not task.done():
                    task.get_loop().call_soon_threadsafe(task.cancel)
        return _reply("已取消接口调用。" if session or run else "当前没有待填写或运行中的接口。")

    def clear_account(self, account_id: int) -> None:
        """Called when an account stops; discard prompts and cancel its requests."""
        with self._lock:
            keys = {key for key in self._sessions if key[0] == account_id}
            keys.update(key for key in self._runs if key[0] == account_id)
            for key in keys:
                self.cancel_session(key)

    def _claim(self, key: SessionKey) -> _Run:
        if not isinstance(key, tuple) or len(key) != 3 or any(type(v) is not int for v in key):
            raise _Rejected("接口会话标识无效。")
        with self._lock:
            self._prune()
            if key in self._runs:
                raise _Rejected("上一条接口请求正在处理中，请稍候，或发送「取消接口」。")
            if len(self._runs) >= self.max_concurrent:
                raise _Rejected("接口正在忙碌，请稍后重试。")
            run = _Run(asyncio.current_task())
            self._runs[key] = run
            return run

    def _select(self, key: str) -> _Entry:
        entries = self._catalog()
        if self._catalog_error:
            raise _Rejected(self._catalog_error)
        key = str(key).strip()
        if key.isascii() and key.isdecimal():
            if len(key) > 8 or not 1 <= int(key) <= len(entries):
                raise _Rejected("接口编号不存在，请发送「菜单」查看目录。")
            return entries[int(key) - 1]
        matches = [entry for entry in entries if entry.id == key]
        if len(matches) != 1:
            raise _Rejected("接口 ID 不存在或重复，请发送「菜单」查看目录。")
        return matches[0]

    @staticmethod
    def _blocked(entry: _Entry) -> BotReply:
        text = f"{entry.name} [{entry.id}]\n不可执行：{entry.reason}"
        if entry.doc_url:
            # Documentation is inert text, never a provider-controlled Markdown link.
            text += f"\n文档：{_label(entry.doc_url, 2000)}"
        else:
            text += "\n文档：目录暂未提供 doc_url。"
        return _reply(text)

    @staticmethod
    def _parse(entry: _Entry, raw_args: str, initial: dict[str, str] | None = None) -> dict[str, str]:
        if len(raw_args) > 8192:
            raise _Rejected("参数过长，请缩短后重试。")
        try:
            tokens = shlex.split(raw_args, posix=True)
        except ValueError:
            raise _Rejected("参数引号未闭合，请使用 name=value，带空格的值请加引号。") from None
        if len(tokens) > 64:
            raise _Rejected("参数过多。")
        values = dict(initial or {})
        names = {param.name for param in entry.parameters}
        assigned = set()
        for token in tokens:
            name, separator, value = token.partition("=")
            if separator and _NAME.fullmatch(name):
                if name not in names:
                    raise _Rejected(f"存在未记录的参数：{_label(name)}。请按文档填写。")
            else:
                name = next((param.name for param in entry.parameters if param.name not in values and param.name not in assigned), "")
                value = token
                if not name:
                    raise _Rejected("位置参数过多，请使用文档中的参数名。")
            if name in assigned:
                raise _Rejected(f"参数 {_label(name)} 重复，请只填写一次。")
            values[name] = value
            assigned.add(name)
        return values

    @staticmethod
    def _validate_values(entry: _Entry, values: Mapping[str, str]) -> None:
        params = {param.name: param for param in entry.parameters}
        if set(values) - set(params):
            raise _Rejected("请求包含未记录的参数。")
        if sum(len(value) for value in values.values()) > 8192:
            raise _Rejected("参数总长度超过限制。")
        for name, value in values.items():
            param = params[name]
            if len(value) > 2048 or any(ord(char) < 32 for char in value):
                raise _Rejected(f"参数 {name} 过长或包含控制字符。")
            if param.required and not value.strip():
                raise _Rejected(f"参数 {name} 为必填项，不能为空。")
            if value and param.choices and value not in param.choices:
                raise _Rejected(f"参数 {name} 不在文档规定的可选值中。")
            if value and param.kind in {"int", "integer", "number", "float"}:
                pattern = r"[+-]?\d{1,18}" if param.kind in {"int", "integer"} else r"[+-]?(?:\d{1,18}(?:\.\d{1,12})?|\.\d{1,12})"
                if not re.fullmatch(pattern, value, flags=re.ASCII):
                    raise _Rejected(f"参数 {name} 需要有效数字。")
            if value and param.kind in {"bool", "boolean"} and value.lower() not in {"true", "false", "1", "0"}:
                raise _Rejected(f"参数 {name} 需要 true/false 或 1/0。")

    async def _resolve(self, value: str, **options: Any) -> OutboundTarget:
        # getaddrinfo cannot be killed when its awaiting coroutine times out.
        # Keep its slot until the worker actually exits, rather than allowing
        # repeated timeouts to enqueue unbounded background DNS work.
        with self._lock:
            self._dns_jobs = {job for job in self._dns_jobs if not job.done()}
            if len(self._dns_jobs) >= self.max_concurrent:
                raise _Rejected("接口 DNS 校验正在忙碌，请稍后重试。")
            job = asyncio.create_task(asyncio.to_thread(resolve_outbound_target, value, **options))
            self._dns_jobs.add(job)

        def finished(task: asyncio.Task) -> None:
            with self._lock:
                self._dns_jobs.discard(task)
            if not task.cancelled():
                task.exception()  # Consume an error even if the caller already timed out.

        job.add_done_callback(finished)
        return await asyncio.shield(job)

    async def _validate_urls(self, entry: _Entry, values: Mapping[str, str]) -> None:
        for param in entry.parameters:
            value = values.get(param.name, "").strip()
            decoded = value
            for _ in range(3):
                updated = unquote(decoded)
                if updated == decoded:
                    break
                decoded = updated
            looks_url = bool(re.search(r"[A-Za-z][A-Za-z0-9+.-]*://|(?:file|data|gopher|ftp|javascript|dict):", decoded, re.I)) or decoded.startswith("//")
            required_url = param.is_url or param.name.lower() in _URL_NAMES
            if not value or not (required_url or looks_url):
                continue
            candidates = [decoded] if required_url or re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:", decoded) else _URL.findall(decoded)
            if len(candidates) > 8:
                raise _Rejected(f"参数 {param.name} 中链接过多。")
            if not candidates:
                raise _Rejected(f"参数 {param.name} 需要公开 HTTP(S) 链接。")
            for candidate in candidates:
                if "\\" in candidate or any(c.isspace() or ord(c) < 32 for c in candidate):
                    raise _Rejected(f"参数 {param.name} 的链接不安全。")
                try:
                    parsed = urlsplit(candidate)
                    sensitive_query = any(_SECRET.search(name) for name, _ in parse_qsl(parsed.query, max_num_fields=64))
                    if (parsed.scheme not in {"https", "http"} or not parsed.hostname or parsed.username
                            or parsed.password or parsed.fragment or sensitive_query):
                        raise ValueError("unsafe URL")
                    self._reject_ambiguous_host(parsed.hostname)
                    await self._resolve(candidate, allow_http=True)
                except (ValueError, OutboundURLError):
                    raise _Rejected(f"参数 {param.name} 的链接不安全；仅允许公开 HTTP(S) 地址，禁止私网、元数据及文件地址。") from None

    def _prompt(self, entry: _Entry, values: dict[str, str], key: SessionKey, prefix: str) -> BotReply | None:
        missing = [param for param in entry.parameters if param.required and not values.get(param.name, "").strip()]
        if not missing:
            return None
        with self._lock:
            self._prune()
            if key not in self._sessions and len(self._sessions) >= self.max_sessions:
                raise _Rejected("待填写接口会话已达上限，请稍后重试。")
            self._sessions[key] = _Session(entry, dict(values), self._clock() + self.session_ttl)
        param = missing[0]
        text = f"{entry.name} [{entry.id}]\n请填写参数 {param.name}（必填；还剩 {len(missing)} 项）。"
        if param.description:
            text += f"\n说明：{param.description}"
        if param.choices:
            text += "\n可选值：" + " / ".join(param.choices)[:300]
        text += f"\n可直接回复参数值，或发送 参数名=值。会话将在 {self.session_ttl:g} 秒无操作后失效。\n取消：{prefix}取消接口"
        return _reply(text, _cancel_keyboard(prefix))

    async def execute(self, key: str, raw_args: str, session_key: SessionKey, prefix: str = "/") -> BotReply:
        prefix = _prefix(prefix)
        try:
            run = self._claim(session_key)
        except _Rejected as exc:
            return _reply(str(exc))
        try:
            async with asyncio.timeout(self.request_timeout):
                entry = self._select(key)
                if entry.reason:
                    return self._blocked(entry)
                values = self._with_defaults(entry, self._parse(entry, raw_args))
                self._validate_values(entry, values)
                await self._validate_urls(entry, values)
                prompt = self._prompt(entry, values, session_key, prefix)
                if prompt:
                    return prompt
                with self._lock:
                    self._sessions.pop(session_key, None)
                return await self._perform(entry, values)
        except asyncio.CancelledError:
            if not run.cancelled:
                raise
            return _reply("已取消接口调用。")
        except (TimeoutError, httpx.TimeoutException):
            return _reply("接口请求超时，请稍后重试。")
        except _Rejected as exc:
            return _reply(str(exc))
        except (httpx.HTTPError, OutboundURLError, OSError, ValueError):
            return _reply("接口调用失败或目标地址不安全，请稍后重试或查看接口文档。")
        finally:
            with self._lock:
                self._runs.pop(session_key, None)
                if run.cancelled:
                    self._sessions.pop(session_key, None)

    async def continue_session(self, text: str, session_key: SessionKey, prefix: str = "/") -> BotReply | None:
        prefix = _prefix(prefix)
        with self._lock:
            self._prune()
            session = self._sessions.get(session_key)
            running = session_key in self._runs
        if not session and not running:
            return None
        if text.strip().lower() in {"取消", "取消接口", "cancel", "api_cancel", f"{prefix}取消接口", f"{prefix}api_cancel"}:
            return self.cancel_session(session_key)
        try:
            run = self._claim(session_key)
        except _Rejected as exc:
            return _reply(str(exc))
        try:
            async with asyncio.timeout(self.request_timeout):
                if not session:
                    return _reply("上一条接口请求正在处理中。")
                # Recheck the current catalogue before continuing a previous selection.
                current = self._select(session.entry.id)
                if current != session.entry:
                    with self._lock:
                        self._sessions.pop(session_key, None)
                    return _reply("接口目录已更新，请重新选择接口。")
                missing = [p for p in current.parameters if p.required and not session.values.get(p.name, "").strip()]
                stripped = text.strip()
                # A natural-language reply belongs to the next parameter, including spaces and '=' in URLs.
                first_name = stripped.partition("=")[0]
                if "=" in stripped and _NAME.fullmatch(first_name):
                    values = self._parse(current, stripped, session.values)
                else:
                    values = dict(session.values)
                    if not missing:
                        raise _Rejected("会话已完成，请重新选择接口。")
                    values[missing[0].name] = stripped
                self._validate_values(current, values)
                await self._validate_urls(current, values)
                prompt = self._prompt(current, values, session_key, prefix)
                if prompt:
                    return prompt
                with self._lock:
                    self._sessions.pop(session_key, None)
                return await self._perform(current, values)
        except asyncio.CancelledError:
            if not run.cancelled:
                raise
            return _reply("已取消接口调用。")
        except (TimeoutError, httpx.TimeoutException):
            return _reply("接口请求超时，请稍后重试。")
        except _Rejected as exc:
            return _reply(str(exc), _cancel_keyboard(prefix))
        except (httpx.HTTPError, OutboundURLError, OSError, ValueError):
            return _reply("接口调用失败或目标地址不安全，请稍后重试或查看接口文档。")
        finally:
            with self._lock:
                self._runs.pop(session_key, None)
                if run.cancelled:
                    self._sessions.pop(session_key, None)

    @staticmethod
    def _with_defaults(entry: _Entry, supplied: dict[str, str]) -> dict[str, str]:
        values = {p.name: p.default for p in entry.parameters if p.default is not None}
        values.update(parse_qsl(urlsplit(entry.endpoint).query, keep_blank_values=True, max_num_fields=32))
        values.update(supplied)
        return values

    async def _perform(self, entry: _Entry, supplied: dict[str, str]) -> BotReply:
        values = self._with_defaults(entry, supplied)
        fixed = dict(parse_qsl(urlsplit(entry.endpoint).query, keep_blank_values=True, max_num_fields=32))
        self._validate_values(entry, values)
        await self._validate_urls(entry, values)
        method = entry.method
        base = urlsplit(entry.endpoint)
        endpoint = urlunsplit((base.scheme, base.netloc, base.path, "", ""))
        query_values = values if method == "GET" else {name: values[name] for name in fixed}
        url = endpoint + ("?" + urlencode(query_values) if query_values else "")
        body = {name: value for name, value in values.items() if name not in fixed} if method == "POST" else None
        for hop in range(self.max_redirects + 1):
            url = _official_url(url, endpoint=True)
            if urlsplit(url).path != base.path:
                raise _Rejected("接口跳转到了未验证路径，已阻止请求。")
            target = await self._resolve(url, base_url=API_ORIGIN)
            async with new_client(target=target, timeout=self.request_timeout, follow_redirects=False) as client:
                kwargs = {entry.body_format if entry.body_format == "json" else "data": body} if body is not None else {}
                async with client.stream(method, url, headers={"Accept": "application/json, text/plain, image/*, video/*", "Accept-Encoding": "identity"}, **kwargs) as response:
                    if response.status_code in _REDIRECTS:
                        if hop == self.max_redirects:
                            raise _Rejected("接口重定向次数超过限制。")
                        location = response.headers.get("location", "")
                        if not location:
                            raise _Rejected("接口返回了无效重定向。")
                        next_url = _official_url(urljoin(url, location), endpoint=True)
                        if urlsplit(next_url).path != base.path:
                            raise _Rejected("接口跳转到了站外来源或未验证路径，已阻止请求。")
                        pairs = parse_qsl(urlsplit(next_url).query, keep_blank_values=True, max_num_fields=32)
                        if len({k for k, _ in pairs}) != len(pairs):
                            raise _Rejected("接口重定向包含重复参数。")
                        redirected = dict(pairs)
                        self._validate_values(entry, redirected)
                        await self._validate_urls(entry, redirected)
                        if response.status_code == 303:
                            method, body = "GET", None
                        elif method == "POST" and response.status_code in {301, 302}:
                            raise _Rejected("POST 接口重定向方式未经确认，已阻止请求。")
                        url = next_url
                        continue
                    if not 200 <= response.status_code < 300:
                        raise _Rejected(f"接口暂不可用（HTTP {response.status_code}），请稍后重试。")
                    content_type = response.headers.get("content-type", "").split(";", 1)[0].lower().strip()
                    if response.headers.get("content-encoding", "identity").strip().lower() not in {"", "identity"}:
                        raise _Rejected("接口忽略了禁止压缩的请求，已停止读取以避免解压缩超限。")
                    length = response.headers.get("content-length")
                    if length:
                        try:
                            declared_length = int(length)
                        except ValueError:
                            raise _Rejected("接口响应长度无效。") from None
                        if declared_length < 0 or declared_length > self.max_response_bytes:
                            raise _Rejected("接口响应超过大小限制，已停止读取。")
                    if content_type in _MEDIA_IMAGE or content_type.startswith("video/"):
                        label = "图片" if content_type in _MEDIA_IMAGE else "视频"
                        if self._sensitive_url(url):
                            raise _Rejected("媒体链接含敏感参数，已隐藏。")
                        return _reply(f"{entry.name}\n{label}链接：{url}")
                    if content_type and content_type not in {"application/json", "text/json", "text/plain", "application/octet-stream"} and not content_type.endswith("+json"):
                        raise _Rejected("接口返回了 HTML、可执行内容或不支持的文件，已隐藏。")
                    chunks = bytearray()
                    async for chunk in response.aiter_bytes(chunk_size=8192):
                        if len(chunks) + len(chunk) > self.max_response_bytes:
                            raise _Rejected("接口响应超过大小限制，已停止读取。")
                        chunks.extend(chunk)
                    if b"\x00" in chunks:
                        raise _Rejected("接口返回了不支持的二进制内容。")
                    try:
                        text = chunks.decode(response.encoding or "utf-8")
                    except (UnicodeError, LookupError):
                        raise _Rejected("接口返回内容编码不受支持。") from None
                    return await self._format_result(entry, text)
        raise _Rejected("接口重定向次数超过限制。")

    @staticmethod
    def _sensitive_url(value: str) -> bool:
        try:
            parsed = urlsplit(value)
            return bool(parsed.username or parsed.password or any(_SECRET.search(key) for key, _ in parse_qsl(parsed.query, max_num_fields=64)))
        except ValueError:
            return True

    @staticmethod
    def _reject_ambiguous_host(host: str) -> None:
        try:
            ipaddress.ip_address(host)
        except ValueError:
            # Legacy inet_aton forms (decimal, hex, octal or short dotted IPs)
            # can otherwise be interpreted differently by the remote URL fetcher.
            if all(re.fullmatch(r"(?:0x[0-9a-f]+|[0-9]+)", part, re.I) for part in host.split(".")):
                raise ValueError("ambiguous numeric host") from None

    async def _safe_result_url(self, value: str) -> str | None:
        if len(value) > 2048 or self._sensitive_url(value) or "\\" in value or any(c.isspace() or ord(c) < 32 for c in value):
            return None
        try:
            self._reject_ambiguous_host(urlsplit(value).hostname or "")
            await self._resolve(value, allow_http=True)
            return value
        except (ValueError, OutboundURLError):
            return None

    async def _format_result(self, entry: _Entry, text: str) -> BotReply:
        text = _clean(text, self.max_response_bytes).strip()
        if _HTML.search(html.unescape(text)):
            raise _Rejected("接口返回了 HTML 或可执行内容，已隐藏。")
        if not text:
            return _reply(f"{entry.name}\n接口返回了空结果。")
        try:
            data = json.loads(text)
        except (ValueError, RecursionError):
            data = None
        media: list[tuple[str, str]] = []
        budget = [200]
        checked_urls: dict[str, str | None] = {}

        async def scrub(value: Any, key: str = "", depth: int = 0) -> Any:
            budget[0] -= 1
            if budget[0] < 0 or depth > 6:
                return "[结果过长，已省略]"
            if _SECRET.search(key):
                return "[已隐藏]"
            if isinstance(value, dict):
                result = {}
                for raw_key, item in list(value.items())[:50]:
                    key_text = str(raw_key)
                    if _HTML.search(html.unescape(key_text)) or _URL.search(key_text):
                        key_text = "[隐藏字段名]"
                    result[key_text] = await scrub(item, str(raw_key), depth + 1)
                return result
            if isinstance(value, list):
                return [await scrub(v, key, depth + 1) for v in value[:50]]
            if not isinstance(value, str):
                return value
            if _HTML.search(html.unescape(value)):
                raise _Rejected("接口返回了 HTML 或可执行内容，已隐藏。")
            value = _SECRET_TEXT.sub(r"\1=[已隐藏]", value)
            urls = list(_URL.finditer(value))
            for match in reversed(urls[:8]):
                url = match.group(0)
                if url not in checked_urls and len(checked_urls) < 8:
                    checked_urls[url] = await self._safe_result_url(url)
                safe = checked_urls.get(url)
                if safe is None:
                    value = value[:match.start()] + "[不安全或敏感链接已隐藏]" + value[match.end():]
                    continue
                path = urlsplit(safe).path.lower()
                kind = "视频" if re.search(r"\.(?:mp4|webm|mov|m3u8)$", path) or "video" in key.lower() or entry.response_type in {"video", "视频"} else ""
                if not kind and (re.search(r"\.(?:jpg|jpeg|png|gif|webp|avif|bmp)$", path) or key.lower() in {"image", "img", "pic", "picture", "avatar", "cover", "image_url", "picurl"} or entry.response_type in {"image", "图片"}):
                    kind = "图片"
                if kind and (kind, safe) not in media:
                    media.append((kind, safe))
            # Never emit URLs skipped because the per-result validation budget is exhausted.
            if len(urls) > 8:
                value = _URL.sub("[过多链接已隐藏]", value)
            return value

        cleaned = await scrub(data if data is not None else text)
        rendered = json.dumps(cleaned, ensure_ascii=False, indent=2) if data is not None else str(cleaned)
        if len(rendered) > 1000:
            rendered = rendered[:960] + "\n[结果过长，已截断]"
        if media:
            links = "\n".join(f"{kind}链接：{url}" for kind, url in media[:4])
            rendered = links + "\n\n" + rendered
        return _reply(f"{entry.name}\n{rendered}")


suyan_service = SuyanService()
