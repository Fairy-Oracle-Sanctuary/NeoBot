"""
MCC 适配能力 —— 插件 API 契约 (plugin-api-v1)。

MCC(晚风小镇 MC 假人服务)相关接口的契约出口。插件从本模块
(或 ``neobot.plugin_api`` 顶层)导入,不直接触碰 ``neobot.adapters``。

- :data:`mcc_manager`:MCC 适配器管理器(获取 client / 实例列表);
- :data:`McpAdapter`:MCC 服务客户端;
- :class:`MccServiceClient`:MCC 服务 HTTP 客户端;
- 异常族:``McpError`` / ``McpAuthError`` / ``McpTimeoutError`` /
  ``McpToolError`` / ``McpUnreachableError`` / ``McpAdapterDisabledError``。
"""
from __future__ import annotations

from neobot.adapters.mcc_adapter import (
    McpAdapter,
    McpAdapterDisabledError,
    McpAdapterManager,
    McpAuthError,
    McpError,
    McpTimeoutError,
    McpToolError,
    McpUnreachableError,
    mcc,
    mcc_manager,
)
from neobot.adapters.mcc_adapter.service_client import MccServiceClient

__all__ = [
    "mcc",
    "mcc_manager",
    "McpAdapter",
    "McpAdapterManager",
    "MccServiceClient",
    "McpAdapterDisabledError",
    "McpError",
    "McpAuthError",
    "McpTimeoutError",
    "McpToolError",
    "McpUnreachableError",
]
