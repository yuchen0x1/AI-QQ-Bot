#!/usr/bin/env python3
"""Build a safe, offline-readable catalog from Suyan's public API index/docs.

Only the homepage and same-site /doc/*.php pages are fetched.  Documented
functional endpoints are parsed as data and are never requested.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import html.parser
import json
import os
import pathlib
import re
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from typing import Any

DEFAULT_SOURCE_URL = "https://api.suyanw.cn/"
SOURCE_HOST = "api.suyanw.cn"
DEFAULT_OUTPUT = (
    pathlib.Path(__file__).resolve().parents[1]
    / "backend"
    / "app"
    / "data"
    / "suyan_apis.json"
)
MAX_HOMEPAGE_BYTES = 2 * 1024 * 1024
MAX_DOCUMENT_BYTES = 512 * 1024
MAX_HTML_NODES = 100_000
MAX_CARDS = 2_000
HTTP_TIMEOUT_SECONDS = 10
HTTP_USER_AGENT = "suyan-catalog-sync/1.0 (polite public documentation indexer)"
MAX_WORKERS = 2
REQUEST_START_INTERVAL_SECONDS = 0.5
IGNORED_TEXT_ELEMENTS = frozenset({"script", "style", "noscript", "template"})
VOID_ELEMENTS = frozenset(
    {
        "area",
        "base",
        "br",
        "col",
        "embed",
        "hr",
        "img",
        "input",
        "link",
        "meta",
        "param",
        "source",
        "track",
        "wbr",
    }
)


class CatalogError(Exception):
    """Raised when the public index cannot safely be cataloged."""


class FetchError(Exception):
    """A bounded, intentionally non-verbose HTTP fetch failure."""


class Element:
    """Small tree node used by the stdlib HTMLParser; never executes page data."""

    __slots__ = ("attrs", "children", "tag")

    def __init__(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        self.tag = tag.lower()
        self.attrs = dict(attrs)
        self.children: list[Element | str] = []

    def descendants(self) -> Iterable[Element]:
        pending: list[Element | str] = list(reversed(self.children))
        while pending:
            child = pending.pop()
            if not isinstance(child, Element):
                continue
            yield child
            if child.tag not in IGNORED_TEXT_ELEMENTS:
                pending.extend(reversed(child.children))

    def text(self) -> str:
        parts: list[str] = []
        pending: list[Element | str] = list(reversed(self.children))
        while pending:
            child = pending.pop()
            if isinstance(child, str):
                parts.append(child)
            elif child.tag not in IGNORED_TEXT_ELEMENTS:
                pending.extend(reversed(child.children))
        normalized_parts = [" ".join(part.split()) for part in parts if part.strip()]
        return " ".join(normalized_parts)


class _TreeParser(html.parser.HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = Element("#root", [])
        self.stack = [self.root]
        self.node_count = 0

    def _new_node(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> Element:
        self.node_count += 1
        if self.node_count > MAX_HTML_NODES:
            raise CatalogError("HTML node limit exceeded")
        node = Element(tag, attrs)
        self.stack[-1].children.append(node)
        return node

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        node = self._new_node(tag, attrs)
        if node.tag not in VOID_ELEMENTS:
            self.stack.append(node)

    def handle_startendtag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        self._new_node(tag, attrs)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index].tag == tag:
                del self.stack[index:]
                return

    def handle_data(self, data: str) -> None:
        self.stack[-1].children.append(data)


class _PoliteRateLimiter:
    """Space request start times across the small worker pool."""

    def __init__(self, interval: float) -> None:
        self.interval = interval
        self.lock = threading.Lock()
        self.next_start = 0.0

    def wait(self) -> None:
        with self.lock:
            now = time.monotonic()
            start_at = max(now, self.next_start)
            self.next_start = start_at + self.interval
        delay = start_at - time.monotonic()
        if delay > 0:
            time.sleep(delay)


def _parse_html(raw: bytes) -> tuple[Element, list[Element]]:
    if not isinstance(raw, bytes):
        raise CatalogError("HTML input must be bytes")
    if len(raw) > MAX_HOMEPAGE_BYTES:
        raise CatalogError("HTML input exceeds the homepage size limit")
    parser = _TreeParser()
    try:
        parser.feed(raw.decode("utf-8", errors="replace"))
        parser.close()
    except (ValueError, RecursionError) as exc:
        raise CatalogError(f"HTML parsing failed ({type(exc).__name__})") from None
    return parser.root, list(parser.root.descendants())


def _normal_text(value: str) -> str:
    return " ".join(value.split()).strip()


def _has_class(node: Element, class_name: str) -> bool:
    classes = str(node.attrs.get("class") or "").split()
    return class_name in classes


def _site_url(url: str) -> urllib.parse.SplitResult | None:
    try:
        parsed = urllib.parse.urlsplit(url)
        port = parsed.port
    except (TypeError, ValueError):
        return None
    if (
        parsed.scheme.lower() != "https"
        or (parsed.hostname or "").lower().rstrip(".") != SOURCE_HOST
        or parsed.username is not None
        or parsed.password is not None
        or port not in (None, 443)
    ):
        return None
    return parsed


def _is_document_url(url: str) -> bool:
    parsed = _site_url(url)
    return bool(
        parsed
        and not parsed.query
        and not parsed.fragment
        and re.fullmatch(r"/doc/[A-Za-z0-9_-]+\.php", parsed.path, re.IGNORECASE)
    )


def _public_entry_url(href: str, page_url: str) -> str | None:
    href = href.strip()
    if not href:
        return None
    absolute = urllib.parse.urljoin(page_url, href)
    parsed = urllib.parse.urlsplit(absolute)
    if (
        parsed.scheme.lower() not in {"https", "http"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
    ):
        return None
    return urllib.parse.urldefrag(absolute).url


def _entry_id(entry_url: str | None, doc_url: str | None, name: str) -> str:
    target = doc_url or entry_url
    if target:
        parsed = urllib.parse.urlsplit(target)
        segment = urllib.parse.unquote(parsed.path.rstrip("/").rsplit("/", 1)[-1])
        if segment.lower().endswith((".php", ".html", ".htm")):
            segment = segment.rsplit(".", 1)[0]
        if not segment and parsed.hostname:
            segment = parsed.hostname.split(".", 1)[0]
        candidate = segment
    else:
        candidate = name
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "-", candidate).strip("-_ ").casefold()
    if slug:
        return slug
    seed = f"{target or ''}\0{name}".encode("utf-8", errors="replace")
    return "entry-" + hashlib.sha256(seed).hexdigest()[:12]


def _unique_id(base: str, seen: Counter[str]) -> str:
    seen[base] += 1
    return base if seen[base] == 1 else f"{base}-{seen[base]}"


def _card_header_name(header: str, fallback: str = "") -> str:
    value = _normal_text(header)
    value = re.sub(r"\s*累计调用\s*[:：]\s*[\d,，]+\s*次.*$", "", value)
    value = re.sub(r"\s*(?:点击查看|查看更多)\s*$", "", value)
    value = _normal_text(value.strip(" -|·｜"))
    if not value:
        value = _normal_text(fallback)
        value = re.sub(r"\s*累计调用\s*[:：]\s*[\d,，]+\s*次.*$", "", value)
    first, separator, rest = value.partition(" ")
    if separator and len(first) <= 2 and rest.startswith(first):
        value = rest
    return _normal_text(value)[:160]


def _card_description(card: Element) -> str:
    for node in card.descendants():
        if node.tag == "p" and _has_class(node, "tool-description"):
            text = _normal_text(node.text())
            if text.casefold() in {"素颜api", "素颜 api", "api"}:
                return ""
            return text[:500]
    return ""


def _card_source_status(card: Element) -> str | None:
    known = ("运行中", "维护中", "维护", "已下线", "停用", "暂停", "异常", "不可用")
    for node in card.descendants():
        if node.tag != "div" or not _has_class(node, "tool-meta"):
            continue
        text = _normal_text(node.text())
        for status in known:
            if status in text:
                return status
        return None
    return None


def parse_homepage(raw: bytes, page_url: str = DEFAULT_SOURCE_URL) -> list[dict[str, Any]]:
    """Extract only real tool-card entries; ignore stats, navigation and ads."""
    _, elements = _parse_html(raw)
    cards = [
        node
        for node in elements
        if node.tag == "div" and _has_class(node, "tool-card")
    ]
    if not cards:
        raise CatalogError("No homepage .tool-card entries found; refusing an empty catalog")
    if len(cards) > MAX_CARDS:
        raise CatalogError("Homepage card count exceeds the safety limit")

    entries: list[dict[str, Any]] = []
    seen_ids: Counter[str] = Counter()
    for card in cards:
        links = [node for node in card.descendants() if node.tag == "a"]
        resolved_links = [
            _public_entry_url(str(node.attrs.get("href") or ""), page_url)
            for node in links
        ]
        resolved_links = [url for url in resolved_links if url]
        doc_url = next((url for url in resolved_links if _is_document_url(url)), None)
        entry_url = doc_url or (resolved_links[0] if resolved_links else None)

        header = next(
            (
                node.text()
                for node in card.descendants()
                if node.tag == "div" and _has_class(node, "tool-header")
            ),
            "",
        )
        name = _card_header_name(header, fallback=links[0].text() if links else "")
        base_id = _entry_id(entry_url, doc_url, name)
        entries.append(
            {
                "id": _unique_id(base_id, seen_ids),
                "name": name or base_id,
                "description": _card_description(card),
                "doc_url": doc_url,
                "entry_url": entry_url,
                "document_title": None,
                "endpoint": None,
                "method": None,
                "response_type": None,
                "params": [],
                "status": "catalog_only",
                "source_status": _card_source_status(card),
                "availability": "unknown",
                "reason": None,
                "parse_status": "not_attempted",
            }
        )
    return entries


def _field_value(elements: list[Element], aliases: tuple[str, ...]) -> str | None:
    labels = tuple(re.escape(alias) for alias in aliases)
    label_pattern = re.compile(
        r"^(?:" + "|".join(labels) + r")\s*[:：]?\s*(.*?)\s*$",
        re.IGNORECASE,
    )
    for node in elements:
        if node.tag not in {"p", "div", "li"}:
            continue
        text = _normal_text(node.text())
        if not text or len(text) > 2_000:
            continue
        match = label_pattern.match(text)
        if not match:
            continue
        value = _normal_text(match.group(1))
        if not value:
            return None
        value = value.split()[0]
        value = re.sub(r"^[\s\"'`。，；;,，]+|[\s\"'`。，；;,，]+$", "", value)
        return value or None
    return None


def _table_rows(table: Element) -> list[list[Element]]:
    rows: list[list[Element]] = []
    for row in table.descendants():
        if row.tag != "tr":
            continue
        cells = [
            child
            for child in row.children
            if isinstance(child, Element) and child.tag in {"th", "td"}
        ]
        if cells:
            rows.append(cells)
    return rows


def _header_index(headers: list[str], kind: str) -> int | None:
    normalized = [re.sub(r"[\s:：*＊()（）]+", "", value).casefold() for value in headers]
    if kind == "name":
        accepted = {"名称", "参数", "参数名", "参数名称", "字段", "字段名", "name", "param", "parameter", "parametername"}
        for index, value in enumerate(normalized):
            if value in accepted or ("参数" in value and "示例" not in value):
                return index
    elif kind == "required":
        for index, value in enumerate(normalized):
            if any(word in value for word in ("必填", "必选", "是否必须", "required", "mandatory")):
                return index
    elif kind == "description":
        for index, value in enumerate(normalized):
            if any(word in value for word in ("说明", "描述", "description", "remark")):
                return index
    elif kind == "default":
        for index, value in enumerate(normalized):
            if "默认值" in value or "default" in value:
                return index
    elif kind == "example":
        for index, value in enumerate(normalized):
            if "示例" in value or "example" in value:
                return index
    return None


def _required_value(value: str | None) -> bool | None:
    if value is None:
        return None
    normalized = re.sub(r"\s+", "", value).casefold()
    if normalized in {"是", "必填", "必选", "true", "yes", "1", "required", "必须"}:
        return True
    if normalized in {"否", "非必填", "可选", "选填", "false", "no", "0", "optional"}:
        return False
    return None


def _is_request_params_heading(node: Element) -> bool:
    text = re.sub(r"[\s:：]+", "", node.text()).casefold()
    return len(text) <= 60 and any(
        label in text for label in ("请求参数说明", "请求参数", "requestparameters")
    )


def _is_section_heading(node: Element) -> bool:
    return (
        _has_class(node, "linep")
        or node.tag in {"h1", "h2", "h3", "h4"}
    )


def _parse_parameter_table(elements: list[Element]) -> tuple[list[dict[str, Any]], bool]:
    heading_index = next(
        (index for index, node in enumerate(elements) if _is_request_params_heading(node)),
        None,
    )
    tables = [index for index, node in enumerate(elements) if node.tag == "table"]
    candidate_tables: list[int] = []
    if heading_index is not None:
        for index in tables:
            if index <= heading_index:
                continue
            if any(
                _is_section_heading(node) and not _is_request_params_heading(node)
                for node in elements[heading_index + 1 : index]
            ):
                break
            candidate_tables.append(index)
            break

    if not candidate_tables:
        candidate_tables = [
            index
            for index in tables
            if any(
                _header_index([cell.text() for cell in row], "required") is not None
                and _header_index([cell.text() for cell in row], "name") is not None
                for row in _table_rows(elements[index])[:2]
            )
        ]

    for table_index in candidate_tables:
        rows = _table_rows(elements[table_index])
        if not rows:
            continue
        header_row_index = next(
            (i for i, row in enumerate(rows) if any(cell.tag == "th" for cell in row)),
            0,
        )
        headers = [cell.text() for cell in rows[header_row_index]]
        name_index = _header_index(headers, "name")
        required_index = _header_index(headers, "required")
        description_index = _header_index(headers, "description")
        default_index = _header_index(headers, "default")
        example_index = _header_index(headers, "example")
        if name_index is None:
            continue

        params: list[dict[str, Any]] = []
        for row in rows[header_row_index + 1 :]:
            values = [cell.text() for cell in row]
            name = values[name_index].strip() if name_index < len(values) else ""
            if not name:
                continue
            required = (
                _required_value(values[required_index])
                if required_index is not None and required_index < len(values)
                else None
            )
            description = (
                values[description_index].strip()
                if description_index is not None and description_index < len(values)
                else ""
            )
            param: dict[str, Any] = {
                "name": name[:160],
                "required": required,
                "description": description[:1_000],
            }
            if default_index is not None and default_index < len(values) and values[default_index].strip():
                param["default"] = values[default_index].strip()[:500]
            if example_index is not None and example_index < len(values) and values[example_index].strip():
                param["example"] = values[example_index].strip()[:500]
            params.append(param)
        return params, heading_index is not None
    return [], False


def _document_title(elements: list[Element]) -> str | None:
    for node in elements:
        if node.tag == "title":
            title = _normal_text(node.text())
            return title[:200] or None
    return None


def parse_document(raw: bytes) -> dict[str, Any]:
    """Extract documented fields only; does not validate or call functional URLs."""
    if len(raw) > MAX_DOCUMENT_BYTES:
        raise CatalogError("document exceeds the document size limit")
    root, elements = _parse_html(raw)
    endpoint = _field_value(elements, ("接口地址", "接口URL", "API URL", "Endpoint"))
    method = _field_value(elements, ("请求方式", "请求方法", "Method"))
    response_type = _field_value(elements, ("返回格式", "响应格式", "Response format"))
    params, has_params_section = _parse_parameter_table(elements)
    method = method.upper() if method else None
    if method and not re.fullmatch(r"[A-Z][A-Z0-9]*(?:\s*[/,|]\s*[A-Z][A-Z0-9]*)*", method):
        method = None
    document = {
        "title": _document_title(elements),
        "endpoint": endpoint,
        "method": method,
        "response_type": response_type,
        "params": params,
        "has_params_section": has_params_section,
        "visible_text": root.text()[:200_000],
    }
    if endpoint and not _is_valid_documented_endpoint(endpoint):
        document["endpoint"] = None
    return document


def _is_valid_documented_endpoint(value: str) -> bool:
    if len(value) > 2_048 or any(character.isspace() for character in value):
        return False
    parsed = urllib.parse.urlsplit(value)
    if parsed.scheme:
        return parsed.scheme.lower() in {"https", "http"} and bool(parsed.hostname)
    return value.startswith("/") or re.match(r"^[A-Za-z0-9_.~-]+(?:/|$)", value) is not None


def _document_title_matches(name: str, title: str | None) -> bool:
    """Treat a generic or closely related title as neutral; flag clear mismatches."""
    if not title:
        return True
    title_core = re.split(r"\s*[-|｜]\s*素颜", title, maxsplit=1, flags=re.IGNORECASE)[0]
    title_core = re.sub(r"^素颜\s*(?:免费)?\s*API.*$", "", title_core, flags=re.IGNORECASE)
    title_core = re.sub(r"api\.suyanw\.cn.*$", "", title_core, flags=re.IGNORECASE)
    def clean(value: str) -> str:
        return re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", value.casefold()).replace("api", "")
    card_name = clean(name)
    doc_name = clean(title_core)
    if not doc_name or not card_name or card_name in doc_name or doc_name in card_name:
        return True
    for start in range(len(card_name)):
        if not "\u4e00" <= card_name[start] <= "\u9fff":
            continue
        for end in range(min(len(card_name), start + 6), start + 1, -1):
            phrase = card_name[start:end]
            if len(phrase) >= 2 and phrase in doc_name:
                return True
    card_words = set(re.findall(r"[a-z0-9]+", card_name))
    doc_words = set(re.findall(r"[a-z0-9]+", doc_name))
    return any(len(word) >= 3 for word in card_words & doc_words)


def _blocked_reason(name: str, description: str, endpoint: str | None, page_text: str) -> str | None:
    endpoint_hint = ""
    if endpoint:
        path = urllib.parse.unquote(urllib.parse.urlsplit(endpoint).path)
        endpoint_hint = path.rsplit("/", 1)[-1].replace("_", " ").removesuffix(".php")
    combined = " ".join(part for part in (name, description, endpoint_hint, page_text) if part)
    phrases = (
        (
            re.compile(r"(?:短信|验证码).{0,24}(?:轰炸|刷|群发|骚扰|攻击)|(?:轰炸|群发|骚扰).{0,24}(?:短信|验证码)", re.IGNORECASE),
            "文档涉及短信/验证码轰炸或骚扰能力",
        ),
        (
            re.compile(r"(?:QQ|ＱＱ|群聊|QQ群).{0,24}(?:轰炸|刷屏|骚扰|恶意群发)|(?:轰炸|刷屏|骚扰).{0,24}(?:QQ|ＱＱ|群聊|QQ群)", re.IGNORECASE),
            "文档涉及 QQ/群聊轰炸、刷屏或骚扰能力",
        ),
        (
            re.compile(r"(?:QQ|ＱＱ|QQ群|QQ空间).{0,24}(?:邀请|评论|留言|发布|发送|私信|消息|点赞|说说|发帖)|(?:邀请|评论|留言|发布|发送|私信|消息|点赞|说说|发帖).{0,24}(?:QQ|ＱＱ|QQ群|群聊|QQ空间)", re.IGNORECASE),
            "文档涉及 QQ 邀请、评论、发帖或其他社交写入操作",
        ),
        (
            re.compile(r"(?:强制|批量|自动).{0,12}(?:加群|拉群|加好友)|(?:加群|拉群|加好友).{0,12}(?:强制|批量|自动)", re.IGNORECASE),
            "文档涉及强制或批量拉人入群/加好友，可能构成 QQ 骚扰",
        ),
        (
            re.compile(r"(?<![A-Za-z0-9_])(?:p_?skey|skey)(?![A-Za-z0-9_])", re.IGNORECASE),
            "文档要求 QQ 会话密钥（skey/pskey）；禁止自动传送账户凭据",
        ),
        (
            re.compile(r"(?:IP(?:地址|信息|实际地址).{0,12}(?:信息|实际地址|地址|地理位置)?(?:查询|定位)|(?:查询|定位|地理位置).{0,16}IP(?:地址|信息)?|IP实际地址查询|IP信息查询|地理位置查询)", re.IGNORECASE),
            "文档涉及通过目标 IP 查询地址或定位信息",
        ),
        (
            re.compile(r"(?:QQ|ＱＱ|QQ号|QQ号码).{0,24}(?:昵称查询|注册时间|个人资料查询|信息查询)|(?:查询|获取).{0,24}QQ(?:昵称|注册时间|个人资料)", re.IGNORECASE),
            "文档涉及按 QQ 号查询个人账号资料",
        ),
        (
            re.compile(r"\bDDoS\b|\bDoS攻击\b|漏洞利用|漏洞攻击|密码爆破|撞库攻击|账号盗取|木马入侵|端口扫描|端口探测|网站状态码查询|网站状态查询|\bport scan(?:ning)?\b", re.IGNORECASE),
            "文档涉及攻击、端口扫描、任意网站状态探测或账号入侵能力",
        ),
        (
            re.compile(r"(?:身份证(?:号码|号)?|手机号(?:码)?|电话号码|银行卡(?:号)?|家庭住址|详细住址|个人隐私).{0,24}(?:查询|检索|获取|定位|搜索|查找)|(?:查询|检索|获取|搜索|查找).{0,24}(?:身份证(?:号码|号)?|手机号(?:码)?|银行卡(?:号)?|家庭住址|详细住址|他人隐私)", re.IGNORECASE),
            "文档涉及身份证、手机号、住址或其他个人敏感信息查询",
        ),
        (
            re.compile(r"\bIP(?:地址)?\b.{0,12}(?:定位|查询他人)|(?:定位|查询他人).{0,12}\bIP(?:地址)?\b", re.IGNORECASE),
            "文档涉及对他人 IP 的定位/查询",
        ),
    )
    for pattern, reason in phrases:
        if pattern.search(combined):
            return reason + "；已保留目录条目并禁止执行。"
    return None


def _doc_failure_entry(doc_url: str, error: str) -> dict[str, Any]:
    safe_error = _normal_text(error)[:180] or "文档抓取失败"
    return {
        "endpoint": None,
        "method": None,
        "response_type": None,
        "params": [],
        "status": "catalog_only",
        "availability": "document_unavailable",
        "reason": f"无法读取公开文档：{safe_error}；未调用功能接口。",
        "parse_status": "unavailable",
        "doc_url": doc_url,
    }


def build_catalog(
    homepage_html: bytes,
    document_results: Mapping[str, Mapping[str, Any]],
    *,
    fetched_at: str | None = None,
    source_url: str = DEFAULT_SOURCE_URL,
) -> dict[str, Any]:
    """Build the JSON-ready catalog from downloaded bytes (offline/testable)."""
    cards = parse_homepage(homepage_html, page_url=source_url)
    for entry in cards:
        doc_url = entry["doc_url"]
        if not doc_url:
            parsed = urllib.parse.urlsplit(entry["entry_url"] or "")
            if parsed.hostname and parsed.hostname.lower().rstrip(".") != SOURCE_HOST:
                entry["availability"] = "off_site"
                entry["reason"] = (
                    f"首页入口指向站外 {entry['entry_url']}；仅保留菜单项，不抓取或调用站外服务。"
                )
                entry["parse_status"] = "not_applicable"
            else:
                entry["availability"] = "missing_documentation"
                entry["reason"] = (
                    "首页卡片没有同站 /doc/*.php 文档链接；只收录入口，不抓取或调用该入口。"
                )
                entry["parse_status"] = "not_applicable"
            continue

        result = document_results.get(doc_url)
        html_bytes = result.get("html") if isinstance(result, Mapping) else None
        error = result.get("error") if isinstance(result, Mapping) else None
        if not isinstance(html_bytes, bytes):
            failure = _doc_failure_entry(doc_url, str(error or "文档未出现在下载清单中"))
            entry.update(failure)
            continue

        try:
            parsed_doc = parse_document(html_bytes)
        except (CatalogError, ValueError, TypeError) as exc:
            entry.update(
                {
                    "availability": "document_unparseable",
                    "reason": f"文档已下载但无法解析（{type(exc).__name__}）；未调用功能接口。",
                    "parse_status": "unparseable",
                }
            )
            continue

        entry["endpoint"] = parsed_doc["endpoint"]
        entry["method"] = parsed_doc["method"]
        entry["response_type"] = parsed_doc["response_type"]
        entry["params"] = parsed_doc["params"]
        entry["document_title"] = parsed_doc["title"]
        title_consistent = _document_title_matches(entry["name"], parsed_doc["title"])
        has_core_fields = all(
            parsed_doc[field]
            for field in ("endpoint", "method", "response_type")
        )
        if has_core_fields and parsed_doc["has_params_section"] and title_consistent:
            entry["parse_status"] = "complete"
            entry["availability"] = "documented"
            entry["reason"] = (
                "公开文档已解析；功能接口未被调用，实际可用性与运行安全性未经在线验证。"
            )
        elif has_core_fields and parsed_doc["has_params_section"]:
            entry["parse_status"] = "partial"
            entry["availability"] = "document_incomplete"
            entry["reason"] = (
                "公开文档标题与首页卡片名称不一致（"
                + str(parsed_doc["title"])
                + "）；已提取字段待人工复核，功能接口未被调用。"
            )
        elif any(parsed_doc[field] for field in ("endpoint", "method", "response_type")):
            entry["parse_status"] = "partial"
            entry["availability"] = "document_incomplete"
            missing = [
                name
                for name, field in (
                    ("endpoint", "endpoint"),
                    ("method", "method"),
                    ("response_type", "response_type"),
                )
                if not parsed_doc[field]
            ]
            if not parsed_doc["has_params_section"]:
                missing.append("params_section")
            if not title_consistent:
                missing.append("document_title_match")
            entry["reason"] = (
                "文档字段不完整，未提取到："
                + ", ".join(missing)
                + "；功能接口未被调用。"
            )
        else:
            entry["parse_status"] = "unparseable"
            entry["availability"] = "document_unparseable"
            entry["reason"] = "文档已下载，但未识别到接口字段；功能接口未被调用。"

        title_can_flag_high_risk = bool(
            parsed_doc["title"]
            and re.search(
                r"短信|验证码|轰炸|群发|骚扰|刷屏|强制加群|批量加群|端口扫描|DDoS|漏洞利用",
                parsed_doc["title"],
                re.IGNORECASE,
            )
        )
        safety_evidence = " ".join(
            ([parsed_doc["title"] or ""] if title_consistent or title_can_flag_high_risk else [])
            + [
                f"{param.get('name', '')} {param.get('description', '')}"
                for param in parsed_doc["params"]
            ]
        )
        blocked_reason = _blocked_reason(
            entry["name"],
            entry["description"],
            entry["endpoint"],
            safety_evidence,
        )
        if blocked_reason:
            entry["status"] = "blocked"
            entry["availability"] = "blocked"
            entry["reason"] = blocked_reason

    parse_counts = Counter(entry["parse_status"] for entry in cards)
    availability_counts = Counter(entry["availability"] for entry in cards)
    linked_doc_urls = list(dict.fromkeys(entry["doc_url"] for entry in cards if entry["doc_url"]))
    fetched_doc_count = sum(
        isinstance(document_results.get(url), Mapping)
        and isinstance(document_results[url].get("html"), bytes)
        for url in linked_doc_urls
    )
    fetched_at = fetched_at or datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    return {
        "schema_version": 1,
        "source_url": source_url,
        "fetched_at": fetched_at,
        "source_count": len(cards),
        "summary": {
            "homepage_entries": len(cards),
            "unique_document_links": len(linked_doc_urls),
            "documents_fetched": fetched_doc_count,
            "documents_failed": len(linked_doc_urls) - fetched_doc_count,
            "parse_status_counts": dict(sorted(parse_counts.items())),
            "availability_counts": dict(sorted(availability_counts.items())),
        },
        "entries": cards,
    }


def _validate_fetch_url(url: str, *, kind: str) -> str:
    parsed = _site_url(url)
    if parsed is None:
        raise FetchError("URL is outside the allowed HTTPS host")
    if kind == "homepage" and parsed.path != "/":
        raise FetchError("homepage fetch is restricted to the site root")
    if kind == "document" and not _is_document_url(url):
        raise FetchError("document fetch is restricted to same-site /doc/*.php pages")
    if kind not in {"homepage", "document"}:
        raise FetchError("unsupported fetch type")
    return urllib.parse.urldefrag(url).url


class _SafeRedirectHandler(urllib.request.HTTPRedirectHandler):
    def __init__(self, kind: str) -> None:
        super().__init__()
        self.kind = kind

    def redirect_request(
        self,
        request: urllib.request.Request,
        file_pointer: Any,
        code: int,
        message: str,
        headers: Any,
        new_url: str,
    ) -> urllib.request.Request | None:
        try:
            _validate_fetch_url(new_url, kind=self.kind)
        except FetchError:
            raise urllib.error.HTTPError(
                new_url,
                code,
                "redirect outside the allowed documentation path",
                headers,
                file_pointer,
            ) from None
        return super().redirect_request(request, file_pointer, code, message, headers, new_url)


def _fetch_html(url: str, *, kind: str, max_bytes: int) -> tuple[bytes, str]:
    url = _validate_fetch_url(url, kind=kind)
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": HTTP_USER_AGENT,
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Encoding": "identity",
        },
    )
    opener = urllib.request.build_opener(_SafeRedirectHandler(kind))
    try:
        with opener.open(request, timeout=HTTP_TIMEOUT_SECONDS) as response:
            final_url = _validate_fetch_url(response.geturl(), kind=kind)
            content_type = str(response.headers.get("Content-Type", "")).lower()
            if "html" not in content_type:
                raise FetchError("response content type is not HTML")
            content_length = response.headers.get("Content-Length")
            if content_length:
                try:
                    if int(content_length) > max_bytes:
                        raise FetchError(f"response exceeds {max_bytes}-byte limit")
                except ValueError:
                    pass
            body = bytearray()
            deadline = time.monotonic() + HTTP_TIMEOUT_SECONDS * 3
            while True:
                chunk = response.read(min(16 * 1024, max_bytes + 1 - len(body)))
                if not chunk:
                    break
                body.extend(chunk)
                if len(body) > max_bytes:
                    raise FetchError(f"response exceeds {max_bytes}-byte limit")
                if time.monotonic() > deadline:
                    raise FetchError("response exceeded the download deadline")
            return bytes(body), final_url
    except urllib.error.HTTPError as exc:
        raise FetchError(f"HTTP {exc.code}") from None
    except FetchError:
        raise
    except urllib.error.URLError as exc:
        reason = exc.reason
        if isinstance(reason, (TimeoutError, OSError)):
            raise FetchError(f"network error ({type(reason).__name__})") from None
        raise FetchError("network error") from None
    except (TimeoutError, OSError) as exc:
        raise FetchError(f"network error ({type(exc).__name__})") from None


def _save_manifest(directory: pathlib.Path, payload: dict[str, Any]) -> None:
    path = directory / "manifest.json"
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _fetch_document_set(
    doc_urls: list[str], directory: pathlib.Path
) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    limiter = _PoliteRateLimiter(REQUEST_START_INTERVAL_SECONDS)
    results: dict[str, dict[str, Any]] = {}
    manifest_documents: list[dict[str, Any] | None] = [None] * len(doc_urls)

    def fetch_one(index: int, url: str) -> tuple[int, dict[str, Any]]:
        file_name = f"document-{index + 1:04d}.html"
        last_error = "document fetch failed"
        for attempt in range(3):
            limiter.wait()
            try:
                body, final_url = _fetch_html(
                    url,
                    kind="document",
                    max_bytes=MAX_DOCUMENT_BYTES,
                )
                (directory / file_name).write_bytes(body)
                return index, {
                    "url": url,
                    "file": file_name,
                    "final_url": final_url,
                    "error": None,
                    "html": body,
                }
            except FetchError as exc:
                last_error = str(exc)
                retryable = last_error.startswith((
                    "network error",
                    "response exceeded the download deadline",
                )) or re.fullmatch(r"HTTP (?:429|5\d{2})", last_error) is not None
                if not retryable or attempt == 2:
                    break
                time.sleep(attempt + 1)
        return index, {
            "url": url,
            "file": None,
            "final_url": None,
            "error": last_error,
            "html": None,
        }

    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = [pool.submit(fetch_one, index, url) for index, url in enumerate(doc_urls)]
        for completed, future in enumerate(concurrent.futures.as_completed(futures), start=1):
            index, item = future.result()
            url = item["url"]
            results[url] = {"html": item["html"], "error": item["error"]}
            manifest_documents[index] = {
                key: item[key]
                for key in ("url", "file", "final_url", "error")
            }
            if completed % 25 == 0 or completed == len(doc_urls):
                print(f"Documentation pages fetched: {completed}/{len(doc_urls)}", flush=True)
    return results, [item for item in manifest_documents if item is not None]


def _unique_doc_urls(entries: list[dict[str, Any]]) -> list[str]:
    return list(dict.fromkeys(entry["doc_url"] for entry in entries if entry["doc_url"]))


def _read_bounded_file(path: pathlib.Path, limit: int) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise CatalogError(f"missing or unsafe cache file: {path.name}")
    if path.stat().st_size > limit:
        raise CatalogError(f"cache file exceeds size limit: {path.name}")
    return path.read_bytes()


def _load_offline_cache(directory: pathlib.Path) -> tuple[bytes, dict[str, dict[str, Any]], str | None]:
    if directory.is_symlink() or not directory.is_dir():
        raise CatalogError("offline cache must be an existing directory")
    homepage = _read_bounded_file(directory / "homepage.html", MAX_HOMEPAGE_BYTES)
    manifest_raw = _read_bounded_file(directory / "manifest.json", 2 * 1024 * 1024)
    try:
        manifest = json.loads(manifest_raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise CatalogError("offline cache manifest is not valid UTF-8 JSON") from None
    if not isinstance(manifest, dict) or not isinstance(manifest.get("documents"), list):
        raise CatalogError("offline cache manifest has an invalid shape")

    results: dict[str, dict[str, Any]] = {}
    for item in manifest["documents"]:
        if not isinstance(item, dict):
            continue
        url = item.get("url")
        if not isinstance(url, str) or not _is_document_url(url):
            continue
        file_name = item.get("file")
        body: bytes | None = None
        error = item.get("error")
        if isinstance(file_name, str) and re.fullmatch(r"document-\d{4,}\.html", file_name):
            try:
                body = _read_bounded_file(directory / file_name, MAX_DOCUMENT_BYTES)
                error = None
            except CatalogError as exc:
                error = str(exc)
        results[url] = {"html": body, "error": str(error or "document absent from cache")}
    fetched_at = manifest.get("fetched_at")
    if not isinstance(fetched_at, str) or len(fetched_at) > 40:
        fetched_at = None
    return homepage, results, fetched_at


def _retry_failed_cache(
    source_directory: pathlib.Path,
) -> tuple[bytes, dict[str, dict[str, Any]], str | None, pathlib.Path]:
    homepage, previous_results, fetched_at = _load_offline_cache(source_directory)
    cards = parse_homepage(homepage)
    doc_urls = _unique_doc_urls(cards)
    retry_urls = [
        url
        for url in doc_urls
        if not isinstance(previous_results.get(url, {}).get("html"), bytes)
    ]
    cache_dir = pathlib.Path(tempfile.mkdtemp(prefix="suyan_catalog_retry_"))
    (cache_dir / "homepage.html").write_bytes(homepage)
    if retry_urls:
        retried_results, _ = _fetch_document_set(retry_urls, cache_dir)
    else:
        retried_results = {}
    document_results = dict(previous_results)
    document_results.update(retried_results)

    manifest_documents: list[dict[str, Any]] = []
    for index, url in enumerate(doc_urls):
        result = document_results.get(url, {})
        body = result.get("html")
        file_name: str | None = None
        if isinstance(body, bytes):
            file_name = f"document-{index + 1:04d}.html"
            (cache_dir / file_name).write_bytes(body)
        manifest_documents.append(
            {
                "url": url,
                "file": file_name,
                "final_url": url if file_name else None,
                "error": None if file_name else str(result.get("error") or "document unavailable"),
            }
        )
    _save_manifest(
        cache_dir,
        {
            "source_url": DEFAULT_SOURCE_URL,
            "fetched_at": fetched_at,
            "documents": manifest_documents,
        },
    )
    return homepage, document_results, fetched_at, cache_dir


def _atomic_write_json(destination: pathlib.Path, payload: dict[str, Any]) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            dir=destination.parent,
            prefix=destination.name + ".",
            suffix=".tmp",
            delete=False,
        ) as stream:
            temporary_name = stream.name
            json.dump(payload, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_name, destination)
    finally:
        if temporary_name and os.path.exists(temporary_name):
            os.unlink(temporary_name)


def _print_report(catalog: dict[str, Any], output: pathlib.Path, cache_dir: pathlib.Path | None) -> None:
    summary = catalog["summary"]
    print(f"Catalog entries: {catalog['source_count']}")
    print(
        "Documentation pages: "
        f"{summary['unique_document_links']} unique links, "
        f"{summary['documents_fetched']} fetched, "
        f"{summary['documents_failed']} failed"
    )
    print("Parse status counts: " + json.dumps(summary["parse_status_counts"], ensure_ascii=False, sort_keys=True))
    print("Availability counts: " + json.dumps(summary["availability_counts"], ensure_ascii=False, sort_keys=True))
    blocked = [entry for entry in catalog["entries"] if entry["status"] == "blocked"]
    print(f"Blocked (listed, never invoked): {len(blocked)}")
    for entry in catalog["entries"]:
        if entry["availability"] not in {"documented", "blocked"}:
            print(
                f"  {entry['id']}: {entry['availability']} / {entry['parse_status']}"
                f" — {entry['reason']}"
            )
    if cache_dir is not None:
        print(f"Downloaded HTML/cache (data only): {cache_dir}")
    print(f"Catalog JSON: {output}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Fetch Suyan's public homepage/docs and regenerate a safe static catalog."
    )
    parser.add_argument(
        "--output",
        type=pathlib.Path,
        default=DEFAULT_OUTPUT,
        help="JSON output path (default: backend/app/data/suyan_apis.json)",
    )
    cache_group = parser.add_mutually_exclusive_group()
    cache_group.add_argument(
        "--offline-cache",
        type=pathlib.Path,
        help="regenerate from a previous run's homepage.html and manifest.json, without network",
    )
    cache_group.add_argument(
        "--retry-failed-cache",
        type=pathlib.Path,
        help="retry only failed doc URLs from a prior cache and emit a new reusable cache",
    )
    args = parser.parse_args(argv)

    if args.offline_cache:
        homepage, document_results, fetched_at = _load_offline_cache(args.offline_cache)
        catalog = build_catalog(
            homepage,
            document_results,
            fetched_at=fetched_at,
        )
        cache_dir: pathlib.Path | None = args.offline_cache.resolve()
    elif args.retry_failed_cache:
        homepage, document_results, fetched_at, cache_dir = _retry_failed_cache(
            args.retry_failed_cache
        )
        catalog = build_catalog(
            homepage,
            document_results,
            fetched_at=fetched_at,
        )
    else:
        cache_dir = pathlib.Path(tempfile.mkdtemp(prefix="suyan_catalog_"))
        homepage, final_url = _fetch_html(
            DEFAULT_SOURCE_URL,
            kind="homepage",
            max_bytes=MAX_HOMEPAGE_BYTES,
        )
        (cache_dir / "homepage.html").write_bytes(homepage)
        fetched_at = datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        entries = parse_homepage(homepage, page_url=final_url)
        doc_urls = _unique_doc_urls(entries)
        document_results, documents = _fetch_document_set(doc_urls, cache_dir)
        _save_manifest(
            cache_dir,
            {
                "source_url": final_url,
                "fetched_at": fetched_at,
                "documents": documents,
            },
        )
        catalog = build_catalog(
            homepage,
            document_results,
            fetched_at=fetched_at,
            source_url=final_url,
        )

    _atomic_write_json(args.output, catalog)
    _print_report(catalog, args.output.resolve(), cache_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
