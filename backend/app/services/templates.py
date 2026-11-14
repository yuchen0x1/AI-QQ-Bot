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


# 自动更新器与校验清单等元数据行对群读者是噪音；存在正式安装包时不再列出。
NOISE_ASSET_PATTERN = re.compile(
    r"\.(blockmap|sig|yml|yaml)$|^(SHA256SUMS|SHA1SUMS|MD5SUMS|CHECKSUMS)|checksums?", re.IGNORECASE
)


def _table_cells(line: str) -> list[str]:
    """表格行拆分：链接只保留文字（URL 由发布页承载），去掉行内加粗/代码标记。"""
    cells: list[str] = []
    for raw in line.strip().strip("|").split("|"):
        cell = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", raw)
        cell = re.sub(r"\*\*([^*]+)\*\*", r"\1", cell).replace("`", "").strip()
        cells.append(cell)
    return cells


def _convert_tables(text: str) -> str:
    """QQ 不渲染 Markdown 表格：管道行转成「· 单元格1：单元格2」，分隔行丢弃。

    表头通常是列标签（如「文件 | 用途」），对读者是噪音，一并跳过。
    资产表里的 blockmap/latest.yml/校验清单行（自动更新器元数据）在有
    正式文件行时过滤，不进群消息。
    """
    lines = text.splitlines()
    out: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        next_is_separator = i + 1 < len(lines) and re.match(r"^\s*\|?\s*:?-{2,}[\s|:-]*$", lines[i + 1])
        if line.lstrip().startswith("|") and next_is_separator:
            i += 2
            rows: list[str] = []
            while i < len(lines) and lines[i].lstrip().startswith("|"):
                parts = [c for c in _table_cells(lines[i]) if c]
                if parts:
                    rows.append("· " + "：".join(parts))
                i += 1
            significant = [r for r in rows if not NOISE_ASSET_PATTERN.search(r.split("：", 1)[0])]
            out.extend(significant if significant else rows)
            continue
        out.append(line)
        i += 1
    return "\n".join(out)


def strip_markdown(text: str) -> str:
    """把 GitHub Release 的 Markdown 转成适合 QQ 阅读的纯文本。"""
    if not text:
        return ""
    result = re.sub(r"```.*?```", "[代码块]", text, flags=re.S)
    result = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", result)
    result = _convert_tables(result)
    result = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"\1（\2）", result)
    result = re.sub(r"^#{1,6}\s*", "", result, flags=re.M)
    result = re.sub(r"\*\*([^*]+)\*\*", r"\1", result)
    result = re.sub(r"[*_`>]", "", result)
    result = re.sub(r"\n{3,}", "\n\n", result)
    return result.strip()
