"""
输入校验 —— 插件 API 契约 (plugin-api-v1)。

:data:`input_validator` 提供 HTML 转义、危险内容清洗等安全工具,
处理用户输入展示到富文本 / 网页前应经过校验。
"""
from __future__ import annotations

from neobot.core.utils.input_validator import InputValidator, input_validator

__all__ = ["input_validator", "InputValidator"]
