"""In-memory test double. Never imported by the application or shipped in its runtime image."""

from __future__ import annotations

import asyncio
import itertools
from collections.abc import AsyncIterator
from datetime import datetime
from typing import Any

from app.adapters.base import AdapterError, AdapterEvent, LoginInfo, QQAdapter


class FakeOfficialAdapter(QQAdapter):
    protocol = "qq_official"

    def __init__(self, self_id: int = 10000, nickname: str = "模拟机器人", *, fail_connect: bool = False) -> None:
        super().__init__()
        self.self_id = self_id
        self.nickname = nickname
        self.fail_connect = fail_connect
        self._connected = False
        self._queue: asyncio.Queue[AdapterEvent] = asyncio.Queue()
        self._msg_seq = itertools.count(1000)
        self.outbox: list[dict[str, Any]] = []
        self.groups: dict[int, dict[str, Any]] = {
            900001: {"group_id": 900001, "group_name": "模拟测试群 A", "member_count": 12, "max_member_count": 200},
            900002: {"group_id": 900002, "group_name": "模拟测试群 B", "member_count": 5, "max_member_count": 200},
        }
        self.members: dict[int, list[dict[str, Any]]] = {
            900001: [
                {"user_id": 20001, "nickname": "群主", "card": "", "role": "owner"},
                {"user_id": 20002, "nickname": "管理员", "card": "", "role": "admin"},
                {"user_id": 20003, "nickname": "普通成员", "card": "", "role": "member"},
            ],
            900002: [
                {"user_id": 20001, "nickname": "群主", "card": "", "role": "owner"},
                {"user_id": 20009, "nickname": "另一个群的成员", "card": "", "role": "member"},
            ],
        }
        self.bans: dict[tuple[int, int], int] = {}
        self.whole_bans: dict[int, bool] = {}
        self.recalled: list[int] = []
        self.request_decisions: list[dict[str, Any]] = []
        self.cards: dict[tuple[int, int], str] = {}
        self.supported_actions_override: set[str] | None = None
        self._supported = {
            "send_private_message",
            "send_group_message",
            "get_login_info",
            "get_friend_list",
            "get_group_list",
            "get_group_info",
            "get_group_member_list",
            "set_group_ban",
            "set_group_whole_ban",
            "set_group_kick",
            "set_group_card",
            "set_group_name",
            "set_group_announce",
            "set_group_admin",
            "delete_msg",
            "set_group_add_request",
            "set_friend_add_request",
        }

    # ------------------------------------------------------------------
    async def connect(self) -> LoginInfo:
        if self.fail_connect:
            raise AdapterError("模拟连接失败（测试用）")
        self._connected = True
        return await self.get_login_info()

    async def disconnect(self) -> None:
        self._connected = False
        await self._queue.put(AdapterEvent(post_type="__disconnected__"))

    @property
    def connected(self) -> bool:
        return self._connected

    async def listen(self) -> AsyncIterator[AdapterEvent]:
        while True:
            event = await self._queue.get()
            yield event
            if event.post_type == "__disconnected__":
                return

    async def emit(self, event: AdapterEvent) -> None:
        await self._queue.put(event)

    def emit_nowait(self, event: AdapterEvent) -> None:
        self._queue.put_nowait(event)

    # ------------------------------------------------------------------
    def _ok(self, **data: Any) -> dict[str, Any]:
        return {"status": "ok", "retcode": 0, "data": data or None}

    def _check(self) -> None:
        if not self._connected:
            raise AdapterError("模拟适配器未连接")

    async def get_login_info(self) -> LoginInfo:
        self._check()
        return LoginInfo(
            self_id=self.self_id,
            nickname=self.nickname,
            avatar_url="",
            raw={"user_id": self.self_id, "nickname": self.nickname},
        )

    async def get_friend_list(self) -> list[dict[str, Any]]:
        self._check()
        return [{"user_id": 20001, "nickname": "群主"}]

    async def get_group_list(self) -> list[dict[str, Any]]:
        self._check()
        return list(self.groups.values())

    async def get_group_info(self, group_id: int) -> dict[str, Any]:
        self._check()
        if group_id not in self.groups:
            raise AdapterError(f"群 {group_id} 不存在")
        return self.groups[group_id]

    async def get_group_member_list(self, group_id: int) -> list[dict[str, Any]]:
        self._check()
        return list(self.members.get(group_id, []))

    async def send_private_message(
        self,
        user_id: int,
        message: str,
        *,
        markdown: dict[str, Any] | None = None,
        keyboard: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self._check()
        message_id = next(self._msg_seq)
        self.outbox.append(
            {
                "type": "private",
                "target": user_id,
                "message": message,
                "markdown": markdown,
                "keyboard": keyboard,
                "message_id": message_id,
                "at": datetime.utcnow(),
            }
        )
        return self._ok(message_id=message_id)

    async def send_group_message(
        self,
        group_id: int,
        message: str,
        *,
        markdown: dict[str, Any] | None = None,
        keyboard: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self._check()
        if group_id not in self.groups:
            raise AdapterError(f"群 {group_id} 不存在，无法发送消息")
        message_id = next(self._msg_seq)
        self.outbox.append(
            {
                "type": "group",
                "target": group_id,
                "message": message,
                "markdown": markdown,
                "keyboard": keyboard,
                "message_id": message_id,
                "at": datetime.utcnow(),
            }
        )
        return self._ok(message_id=message_id)

    async def set_group_ban(self, group_id: int, user_id: int, duration: int = 600) -> dict[str, Any]:
        self._check()
        self.bans[(group_id, user_id)] = duration
        return self._ok()

    async def set_group_whole_ban(self, group_id: int, enable: bool) -> dict[str, Any]:
        self._check()
        self.whole_bans[group_id] = enable
        return self._ok()

    async def set_group_kick(self, group_id: int, user_id: int, reject_add_request: bool = False) -> dict[str, Any]:
        self._check()
        members = self.members.get(group_id, [])
        before = len(members)
        self.members[group_id] = [m for m in members if int(m["user_id"]) != user_id]
        if len(self.members[group_id]) == before:
            raise AdapterError(f"群 {group_id} 中不存在成员 {user_id}")
        return self._ok()

    async def set_group_card(self, group_id: int, user_id: int, card: str) -> dict[str, Any]:
        self._check()
        self.cards[(group_id, user_id)] = card
        return self._ok()

    async def set_group_name(self, group_id: int, name: str) -> dict[str, Any]:
        self._check()
        if group_id not in self.groups:
            raise AdapterError(f"群 {group_id} 不存在")
        self.groups[group_id]["group_name"] = name
        return self._ok()

    async def set_group_announce(self, group_id: int, content: str) -> dict[str, Any]:
        self._check()
        return self._ok(notice=content)

    async def set_group_admin(self, group_id: int, user_id: int, enable: bool) -> dict[str, Any]:
        self._check()
        for member in self.members.get(group_id, []):
            if int(member["user_id"]) == user_id:
                member["role"] = "admin" if enable else "member"
                return self._ok()
        raise AdapterError(f"群 {group_id} 中不存在成员 {user_id}")

    async def delete_msg(self, message_id: int) -> dict[str, Any]:
        self._check()
        self.recalled.append(message_id)
        return self._ok()

    async def set_group_add_request(
        self, flag: str, sub_type: str, approve: bool, reason: str = ""
    ) -> dict[str, Any]:
        self._check()
        self.request_decisions.append(
            {"type": "group", "flag": flag, "sub_type": sub_type, "approve": approve, "reason": reason}
        )
        return self._ok()

    async def set_friend_add_request(self, flag: str, approve: bool, remark: str = "") -> dict[str, Any]:
        self._check()
        self.request_decisions.append(
            {"type": "friend", "flag": flag, "approve": approve, "remark": remark}
        )
        return self._ok()


    async def send_proactive_group_message(self, group_id: int, message: str) -> dict[str, Any]:
        return await self.send_group_message(group_id, message)

    async def get_group_bot_state(self, group_id: int) -> dict[str, Any]:
        return {"allow_proactive_msg": True}

    async def probe(self) -> dict[str, Any]:
        return {"sandbox": False, "callback_mode": "websocket", "gateway": "wss://fixture.invalid"}
