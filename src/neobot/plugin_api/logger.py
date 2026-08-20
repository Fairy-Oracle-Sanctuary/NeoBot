"""
日志 —— 插件 API 契约 (plugin-api-v1)。

- :data:`logger`:全局默认 logger(带日志级别 / 彩色输出);
- :class:`ModuleLogger`:按模块名创建带命名空间的 logger,插件推荐使用::

    from neobot.plugin_api import ModuleLogger
    logger = ModuleLogger("MyPlugin")
"""
from __future__ import annotations

from neobot.core.utils.logger import ModuleLogger, logger

__all__ = ["logger", "ModuleLogger"]
