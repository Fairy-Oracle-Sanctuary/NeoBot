# -*- coding: utf-8 -*-
"""
平台无关消息层（阶段 2/3）：
- PlatformMessage：跨平台统一消息模型（消息总线载荷）
- CommandContext：平台感知的指令上下文（插件入口，替代伪造的 OneBot 事件）
- MessageBus：进程内消息总线（入站分发 / 出站发送）
"""
from .message import PlatformMessage, MessageSegment as PlatformSegment
from .context import CommandContext
from .bus import MessageBus, message_bus

__all__ = [
    "PlatformMessage",
    "PlatformSegment",
    "CommandContext",
    "MessageBus",
    "message_bus",
]
