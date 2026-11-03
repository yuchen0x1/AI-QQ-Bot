"""关键词自动回复插件：命中配置规则时回复固定文本。"""

from __future__ import annotations


def register(ctx) -> None:
    async def on_message(message):
        text = (message.text or "").strip()
        if not text or text.startswith("/"):
            return None
        for rule in ctx.config.get("rules", []):
            keyword = (rule.get("keyword") or "").strip()
            reply = (rule.get("reply") or "").strip()
            if keyword and reply and keyword in text:
                return reply
        return None

    ctx.on_message(on_message)
