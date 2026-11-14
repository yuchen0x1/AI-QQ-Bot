"""应用版本号唯一来源。

前端 ``package.json`` 的版本独立演进（管理台 UI），后端元数据统一取这里，
避免再出现根路由 / health / info 各自写死 ``1.0.0`` 的漂移。
"""

from __future__ import annotations

APP_VERSION = "1.4.4"

__all__ = ["APP_VERSION"]
