"""RBAC 权限定义。"""

from __future__ import annotations

ALL_PERMISSIONS = [
    "account:view",
    "account:manage",
    "group:view",
    "group:manage",
    "request:view",
    "request:manage",
    "message:view",
    "message:send",
    "ai:view",
    "ai:manage",
    "github:view",
    "github:manage",
    "push:view",
    "push:manage",
    "task:view",
    "task:manage",
    "plugin:view",
    "plugin:manage",
    "log:view",
    "system:view",
    "system:manage",
    "user:manage",
    "audit:view",
]

READ_ONLY = [
    "account:view",
    "group:view",
    "request:view",
    "message:view",
    "ai:view",
    "github:view",
    "push:view",
    "task:view",
    "plugin:view",
    "log:view",
    "system:view",
]

OPERATOR = [
    p
    for p in ALL_PERMISSIONS
    if p not in {"user:manage", "system:manage", "audit:view"}
]

ROLE_DEFS: list[dict] = [
    {
        "name": "super_admin",
        "description": "超级管理员，拥有全部权限",
        "permissions": ["*"],
        "is_system": True,
    },
    {
        "name": "operator",
        "description": "运维操作员，可管理账号、群聊、AI、仓库与任务，不能管理用户与系统设置",
        "permissions": OPERATOR,
        "is_system": True,
    },
    {
        "name": "viewer",
        "description": "只读访客",
        "permissions": READ_ONLY,
        "is_system": True,
    },
]
