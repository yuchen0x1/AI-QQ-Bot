"""Transport-independent reply shared by bot commands and API services."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class BotReply:
    text: str
    markdown: dict | None = None
    keyboard: dict | None = None
