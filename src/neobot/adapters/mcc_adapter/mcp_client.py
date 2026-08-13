# -*- coding: utf-8 -*-
"""
兼容层：错误类型从 service_client 再导出（旧插件 import 路径不变）。
"""
from .service_client import (
    McpAuthError,
    McpError,
    McpTimeoutError,
    McpToolError,
    McpUnreachableError,
)

__all__ = [
    "McpError",
    "McpAuthError",
    "McpTimeoutError",
    "McpToolError",
    "McpUnreachableError",
]
