"""
全局配置 —— 插件 API 契约 (plugin-api-v1)。

:data:`global_config` 为全局唯一的配置对象(``neobot.core.config_loader.Config``)。
插件读取 ``config.toml`` 中 [bot]、[platform] 等分节时使用。
"""
from __future__ import annotations

from neobot.core.config_loader import global_config

__all__ = ["global_config"]
