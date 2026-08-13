# -*- coding: utf-8 -*-
"""
MCC 适配器（转发层）：neobot 只处理指令并转发到独立程序 mcc-service。

实例列表、MCP 能力、Agent、Wiki/地图数据都在 mcc-service；本包只保留
群路由与监听去重等本地状态。

配置：config.toml 的 [mcc_adapter] 段（enabled/service_url/service_token）。
"""
from .adapter import McpAdapter, McpAdapterDisabledError, McpAdapterManager, mcc, mcc_manager
from .service_client import (
    McpAuthError,
    McpError,
    McpTimeoutError,
    McpToolError,
    McpUnreachableError,
)

__all__ = [
    "mcc",
    "mcc_manager",
    "McpAdapter",
    "McpAdapterManager",
    "McpAdapterDisabledError",
    "McpError",
    "McpAuthError",
    "McpTimeoutError",
    "McpToolError",
    "McpUnreachableError",
]
