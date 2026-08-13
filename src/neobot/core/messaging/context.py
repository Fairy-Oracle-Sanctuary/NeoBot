# -*- coding: utf-8 -*-
"""
平台感知的指令上下文（CommandContext）。

替代"把 Discord 伪装成 OneBot 事件"的方案：插件拿到的是统一上下文，
属性与 MessageEvent 兼容（message_type/group_id/user_id/raw_message/message/reply），
因此从 OneBot 事件迁移到 CommandContext 的插件无需改函数体。
"""
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Union

from neobot.models.message import MessageSegment as OneBotMessageSegment

from .message import PlatformMessage, MessageSegment


@dataclass
class CommandContext:
    """统一指令上下文。"""

    platform: str
    message_type: str            # "group" | "private"
    message_id: Any
    user_id: Any
    raw_message: str
    bot: Any                     # 发送句柄（适配器）
    group_id: Optional[Any] = None
    message: List[OneBotMessageSegment] = field(default_factory=list)
    author_name: str = ""
    self_id: Any = 0
    source: PlatformMessage = None
    _extra: Dict[str, Any] = field(default_factory=dict)

    # ── 兼容属性 ────────────────────────────────────────────────

    @property
    def sender(self):
        from neobot.models.sender import Sender
        return Sender(user_id=self.user_id, nickname=self.author_name or str(self.user_id))

    async def reply(self, message: Union[str, OneBotMessageSegment, List[OneBotMessageSegment]]):
        """按平台发送回复。"""
        if self.message_type == "group" and self.group_id is not None:
            return await self.bot.send_group_msg(self.group_id, message)
        return await self.bot.send_private_msg(self.user_id, message)

    def get(self, key: str, default: Any = None) -> Any:
        return self._extra.get(key, default)

    def set(self, key: str, value: Any) -> None:
        self._extra[key] = value

    # ── 工厂 ────────────────────────────────────────────────────

    @classmethod
    def from_onebot_event(cls, event, bot: Any) -> "CommandContext":
        """从 OneBot MessageEvent 派生（QQ 命令迁移用，行为与事件一致）。"""
        group_id = getattr(event, "group_id", None)
        return cls(
            platform="qq",
            message_type=getattr(event, "message_type", "group"),
            message_id=getattr(event, "message_id", None),
            user_id=getattr(event, "user_id", None),
            raw_message=getattr(event, "raw_message", "") or "",
            bot=bot,
            group_id=group_id,
            message=getattr(event, "message", None) or [],
            author_name=getattr(getattr(event, "sender", None), "nickname", "") or "",
            self_id=getattr(event, "self_id", 0) or getattr(bot, "self_id", 0) or 0,
            source=None,
        )

    @classmethod
    def from_platform_message(cls, msg: PlatformMessage, bot: Any, sender_name: str = "") -> "CommandContext":
        """从平台消息构造（Discord 等非 OneBot 平台）。"""
        group_id = msg.channel_id if msg.channel_type == "group" else None
        segments = _platform_segments_to_onebot(msg.segments, msg.content)
        return cls(
            platform=msg.platform,
            message_type=msg.channel_type,
            message_id=msg.message_id,
            user_id=msg.author_id,
            raw_message=msg.to_text(),
            bot=bot,
            group_id=group_id,
            message=segments,
            author_name=sender_name or msg.author_name,
            self_id=getattr(bot, "self_id", 0) or 0,
            source=msg,
        )


def _platform_segments_to_onebot(
    segments: List[MessageSegment], fallback_text: str
) -> List[OneBotMessageSegment]:
    """平台消息段 → OneBot MessageSegment（发送/兼容用）。"""
    result: List[OneBotMessageSegment] = []
    for seg in segments:
        if seg.type == "text":
            result.append(OneBotMessageSegment.text(seg.text))
        elif seg.type == "image":
            result.append(OneBotMessageSegment.image(seg.url))
        elif seg.type == "video":
            result.append(OneBotMessageSegment.video(seg.url))
        elif seg.type == "record":
            result.append(OneBotMessageSegment.record(seg.url))
    if not result and fallback_text:
        result.append(OneBotMessageSegment.text(fallback_text))
    return result
