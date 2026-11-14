"""Release 通知消息格式测试：表格转纯文本、资产去噪、默认模板不重复下载地址。"""

from __future__ import annotations

from app.services.github.notify import DEFAULT_TEMPLATE, build_values, format_assets
from app.services.templates import strip_markdown

JUKEBOX_BODY = """# JukeboxRoom v0.0.18

发布日期：2026-11-14（北京时间） · [与上一版比较](https://github.com/yuchen0x1/JukeboxRoom/compare/v0.0.17...v0.0.18)

## 本版更新

- 规则模式系统代理兼容：开启 Clash 等规则模式代理时不再被推进国外代理链。

## 下载与发布资产

| 文件 | 用途 |
|---|---|
| [jukeboxroom-desktop-setup-0.0.18-x64.exe](https://github.com/yuchen0x1/JukeboxRoom/releases/download/v0.0.18/jukeboxroom-desktop-setup-0.0.18-x64.exe) | Windows x64 安装程序（内置本地服务端，无需安装 Node.js） |
| [jukeboxroom-desktop-setup-0.0.18-x64.exe.blockmap](https://github.com/yuchen0x1/JukeboxRoom/releases/download/v0.0.18/jukeboxroom-desktop-setup-0.0.18-x64.exe.blockmap) | Windows 增量更新所需文件 |
| [latest.yml](https://github.com/yuchen0x1/JukeboxRoom/releases/download/v0.0.18/latest.yml) | Windows 自动更新版本及 SHA-512 元数据 |

## 已知限制

- Windows 安装包未使用商业代码签名证书，首次运行可能触发 SmartScreen。
"""


def test_strip_markdown_converts_tables_to_plain_lines():
    text = strip_markdown(JUKEBOX_BODY)
    assert "|" not in text, "QQ 不渲染 Markdown，管道符不允许残留"
    assert "---" not in text
    # 表格行转成「· 文件：用途」，链接只保留文件名
    assert "· jukeboxroom-desktop-setup-0.0.18-x64.exe：Windows x64 安装程序（内置本地服务端，无需安装 Node.js）" in text
    # 更新器元数据行在有正式文件行时被过滤
    assert "blockmap" not in text and "latest.yml" not in text and "SHA256SUMS" not in text
    # 表内 URL 不再重复出现，下载链接由发布页承载
    assert "releases/download" not in text
    # 正文其他内容保留
    assert "发布日期：2026-11-14（北京时间）" in text
    assert "已知限制" in text


def test_format_assets_single_line_and_noise_filtered():
    assets = [
        {"name": "jukeboxroom-desktop-setup-0.0.18-x64.exe", "size": 158_000_000, "browser_download_url": "https://x/1"},
        {"name": "jukeboxroom-desktop-setup-0.0.18-x64.exe.blockmap", "size": 200_000},
        {"name": "latest.yml", "size": 300},
        {"name": "SHA256SUMS.txt", "size": 200},
    ]
    text = format_assets(assets)
    lines = text.splitlines()
    assert len(lines) == 1, f"每个资产一行：{lines}"
    assert lines[0] == "· jukeboxroom-desktop-setup-0.0.18-x64.exe（150.7 MB）"
    assert "blockmap" not in text and "latest.yml" not in text


def test_format_assets_keeps_list_when_only_metadata():
    assets = [{"name": "latest.yml", "size": 300}, {"name": "SHA256SUMS.txt", "size": 200}]
    text = format_assets(assets)
    assert "latest.yml" in text and "SHA256SUMS.txt" in text


def test_default_template_has_no_duplicate_download_section():
    assert "下载地址" not in DEFAULT_TEMPLATE
    assert "{downloads}" not in DEFAULT_TEMPLATE


class _FakeRelease:
    tag_name = "v0.0.18"
    name = "JukeboxRoom v0.0.18"
    body = JUKEBOX_BODY
    published_at = None
    assets = []
    html_url = "https://github.com/yuchen0x1/JukeboxRoom/releases/tag/v0.0.18"
    prerelease = False


class _FakeRepo:
    name = "JukeboxRoom"
    full_name = "yuchen0x1/JukeboxRoom"
    owner = "yuchen0x1"
    description = ""
    html_url = "https://github.com/yuchen0x1/JukeboxRoom"


def test_build_values_changelog_is_pipe_free():
    values = build_values(_FakeRepo(), _FakeRelease(), changelog=strip_markdown(_FakeRelease.body))
    assert "|" not in values["changelog"]
    assert "· jukeboxroom-desktop-setup-0.0.18-x64.exe" in values["changelog"]
