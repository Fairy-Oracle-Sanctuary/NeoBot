"""
消息与平台消息 —— 插件 API 契约 (plugin-api-v1)。

- :class:`MessageSegment`:OneBot 消息段(text / image / at / node ...),最常用;
- :class:`PlatformMessage` / :class:`PlatformSegment`:跨平台消息载体,
  平台感知插件(Discord 桥等)使用。
"""
from __future__ import annotations

from neobot.core.messaging.message import (
    MessageSegment as PlatformSegment,
    PlatformMessage,
)
from neobot.models.message import MessageSegment

__all__ = ["MessageSegment", "PlatformMessage", "PlatformSegment"]
