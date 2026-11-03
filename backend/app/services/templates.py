"""模板渲染：支持 {key} 占位符，未知变量安全替换为空。"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any


class _SafeDict(dict):
    def __missing__(self, key: str) -> str:  # noqa: D105
        return ""


def render_template(template: str, values: Mapping[str, Any]) -> str:
    if not template:
        return ""
    normalized = template.replace("{{", "{").replace("}}", "}")
    try:
        return normalized.format_map(_SafeDict({k: ("" if v is None else v) for k, v in values.items()}))
    except (ValueError, IndexError):
        # 模板本身语法有误时做最小替换，保证通知不丢失
        result = template
        for key, value in values.items():
            result = result.replace("{" + key + "}", str(value if value is not None else ""))
        return result


def truncate(text: str | None, limit: int = 1500) -> str:
    if not text:
        return ""
    if len(text) <= limit:
        return text
    return text[: limit - 20].rstrip() + "\n……（内容过长已截断）"


def strip_markdown(text: str) -> str:
    """把 GitHub Release 的 Markdown 转成适合 QQ 阅读的纯文本。"""
    if not text:
        return ""
    result = re.sub(r"```.*?```", "[代码块]", text, flags=re.S)
    result = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", result)
    result = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"\1（\2）", result)
    result = re.sub(r"^#{1,6}\s*", "", result, flags=re.M)
    result = re.sub(r"\*\*([^*]+)\*\*", r"\1", result)
    result = re.sub(r"[*_`>]", "", result)
    result = re.sub(r"\n{3,}", "\n\n", result)
    return result.strip()
