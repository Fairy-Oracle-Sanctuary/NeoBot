# -*- coding: utf-8 -*-
"""
平台无关消息模型。
"""
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class MessageSegment:
    """平台无关消息段：text / image / video / record / file / at。"""

    type: str
    text: str = ""
    url: str = ""
    filename: str = ""
    extra: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def text(cls, text: str) -> "MessageSegment":
        return cls(type="text", text=text)

    @classmethod
    def image(cls, url: str, filename: str = "") -> "MessageSegment":
        return cls(type="image", url=url, filename=filename)

    @classmethod
    def video(cls, url: str, filename: str = "") -> "MessageSegment":
        return cls(type="video", url=url, filename=filename)

    @classmethod
    def record(cls, url: str, filename: str = "") -> "MessageSegment":
        return cls(type="record", url=url, filename=filename)


@dataclass
class PlatformMessage:
    """跨平台统一消息（消息总线载荷）。"""

    platform: str            # "qq" | "discord" | "cli" | "mcc"
    channel_id: Any          # QQ 群号 / Discord 频道 ID
    channel_type: str        # "group" | "private"
    message_id: Any
    author_id: Any
    author_name: str
    content: str             # 纯文本
    segments: List[MessageSegment] = field(default_factory=list)
    reply_to: Any = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    raw: Any = None

    def to_text(self) -> str:
        """拼接所有文本段（含附件占位）。"""
        if self.content:
            return self.content
        parts = []
        for seg in self.segments:
            if seg.type == "text":
                parts.append(seg.text)
            elif seg.url:
                parts.append(f"[{seg.type}: {seg.filename or seg.url}]")
        return "".join(parts)
