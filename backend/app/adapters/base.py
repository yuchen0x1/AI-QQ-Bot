"""QQ 协议适配层：统一接口，业务核心不依赖任何具体协议实现。"""

from __future__ import annotations

import abc
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

CAPABILITIES: dict[str, str] = {
    "send_private_message": "发送私聊消息",
    "send_group_message": "发送群消息",
    "get_login_info": "获取登录信息",
    "get_friend_list": "获取好友列表",
    "get_group_list": "获取群列表",
    "get_group_info": "获取群信息",
    "get_group_member_list": "获取群成员列表",
    "set_group_ban": "禁言成员",
    "set_group_whole_ban": "全体禁言",
    "set_group_kick": "踢出成员",
    "set_group_card": "设置群名片",
    "set_group_name": "设置群名称",
    "set_group_announce": "设置群公告",
    "set_group_admin": "设置管理员",
    "delete_msg": "撤回消息",
    "set_group_add_request": "处理加群申请",
    "set_friend_add_request": "处理好友申请",
}


class AdapterError(RuntimeError):
    pass


class UnsupportedAction(AdapterError):
    """协议端不支持该操作——必须明确报错，绝不假装成功。"""


@dataclass
class LoginInfo:
    self_id: int
    nickname: str = ""
    avatar_url: str = ""
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class AdapterEvent:
    """统一事件模型。"""

    post_type: str
    message_type: str | None = None
    sub_type: str | None = None
    self_id: int | None = None
    group_id: int | None = None
    user_id: int | None = None
    message_id: int | None = None
    raw_message: str = ""
    sender: dict[str, Any] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)
    received_at: datetime = field(default_factory=datetime.utcnow)

    @property
    def sender_name(self) -> str:
        return (
            self.sender.get("card")
            or self.sender.get("nickname")
            or self.sender.get("nick")
            or str(self.user_id or "")
        )

    @property
    def is_at_me(self) -> bool:
        message = self.raw.get("message")
        if isinstance(message, list):
            return any(seg.get("type") == "at" and str(seg.get("data", {}).get("qq")) == str(self.self_id) for seg in message)
        return f"[CQ:at,qq={self.self_id}]" in self.raw_message


class QQAdapter(abc.ABC):
    """所有协议实现必须继承的接口。"""

    protocol: str = "base"

    def __init__(self) -> None:
        self._supported: set[str] = set()

    # ---------------- 能力 ----------------
    @property
    def supported_actions(self) -> set[str]:
        return set(self._supported)

    def capabilities(self) -> dict[str, bool]:
        return {key: key in self._supported for key in CAPABILITIES}

    def supports(self, action: str) -> bool:
        return action in self._supported

    def _require(self, action: str) -> None:
        if action not in self._supported:
            raise UnsupportedAction(f"当前协议端不支持操作：{action}（{CAPABILITIES.get(action, action)}）")

    # ---------------- 生命周期 ----------------
    @abc.abstractmethod
    async def connect(self) -> LoginInfo: ...

    @abc.abstractmethod
    async def disconnect(self) -> None: ...

    @property
    @abc.abstractmethod
    def connected(self) -> bool: ...

    @abc.abstractmethod
    async def listen(self) -> Any:
        """异步迭代事件。"""

    # ---------------- 查询 ----------------
    @abc.abstractmethod
    async def get_login_info(self) -> LoginInfo: ...

    @abc.abstractmethod
    async def get_friend_list(self) -> list[dict[str, Any]]: ...

    @abc.abstractmethod
    async def get_group_list(self) -> list[dict[str, Any]]: ...

    @abc.abstractmethod
    async def get_group_info(self, group_id: int) -> dict[str, Any]: ...

    @abc.abstractmethod
    async def get_group_member_list(self, group_id: int) -> list[dict[str, Any]]: ...

    # ---------------- 消息 ----------------
    @abc.abstractmethod
    async def send_private_message(self, user_id: int, message: str) -> dict[str, Any]: ...

    @abc.abstractmethod
    async def send_group_message(self, group_id: int, message: str) -> dict[str, Any]: ...

    # ---------------- 群管理 ----------------
    @abc.abstractmethod
    async def set_group_ban(self, group_id: int, user_id: int, duration: int = 600) -> dict[str, Any]: ...

    @abc.abstractmethod
    async def set_group_whole_ban(self, group_id: int, enable: bool) -> dict[str, Any]: ...

    @abc.abstractmethod
    async def set_group_kick(self, group_id: int, user_id: int, reject_add_request: bool = False) -> dict[str, Any]: ...

    @abc.abstractmethod
    async def set_group_card(self, group_id: int, user_id: int, card: str) -> dict[str, Any]: ...

    @abc.abstractmethod
    async def set_group_name(self, group_id: int, name: str) -> dict[str, Any]: ...

    @abc.abstractmethod
    async def set_group_announce(self, group_id: int, content: str) -> dict[str, Any]: ...

    @abc.abstractmethod
    async def set_group_admin(self, group_id: int, user_id: int, enable: bool) -> dict[str, Any]: ...

    @abc.abstractmethod
    async def delete_msg(self, message_id: int) -> dict[str, Any]: ...

    async def set_group_add_request(self, flag: str, sub_type: str, approve: bool, reason: str = "") -> dict[str, Any]:
        self._require("set_group_add_request")
        raise NotImplementedError

    async def set_friend_add_request(self, flag: str, approve: bool, remark: str = "") -> dict[str, Any]:
        self._require("set_friend_add_request")
        raise NotImplementedError

    # ---------------- 事件交给引擎 ----------------
    async def handle_event(self, event: AdapterEvent) -> None:  # pragma: no cover - 由管理器覆盖
        return None
