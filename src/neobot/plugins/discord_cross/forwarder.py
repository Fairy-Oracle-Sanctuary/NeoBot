# -*- coding: utf-8 -*-
"""
跨平台转发器（阶段 1 收敛目标）

QQ↔Discord 的转发决策、映射、去重、防环全部收敛到这一处：
- 用户消息：handlers 调 forward_qq_to_discord / forward_discord_to_qq
- 机器人发送的消息：发送层调 notify_qq_sent / notify_discord_sent 上报，
  由本转发器决定是否需要转发到另一端（不再在发送函数里直接转发）
- 统一去重（TTL 内同平台同频道同内容不重复转发）与防环（发送端不再有副作用）
"""
import hashlib
import time
from typing import Dict, List, Optional, Tuple

from neobot.core.utils.logger import ModuleLogger

from .config import config
from .sender import (
    forward_discord_to_qq as _send_discord_to_qq,
    forward_qq_to_discord as _send_qq_to_discord,
)

logger = ModuleLogger("CrossPlatformForwarder")

DEDUP_TTL_SECONDS = 30.0
MAX_RECENT = 512


class CrossPlatformForwarder:
    """QQ ↔ Discord 统一转发器。"""

    def __init__(self):
        self._recent: Dict[Tuple[str, int, str], float] = {}

    @staticmethod
    def _key(platform: str, channel_id: int, content: str) -> Tuple[str, int, str]:
        h = hashlib.md5((content or "").encode("utf-8", errors="replace")).hexdigest()
        return (platform, int(channel_id), h)

    def _seen(self, platform: str, channel_id: int, content: str) -> bool:
        """TTL 内是否已转发过同内容（去重）；并顺带记录本次。"""
        now = time.monotonic()
        key = self._key(platform, channel_id, content)
        last = self._recent.get(key)
        if last is not None and now - last < DEDUP_TTL_SECONDS:
            return True
        self._recent[key] = now
        if len(self._recent) > MAX_RECENT:
            self._recent = {
                k: v for k, v in self._recent.items()
                if now - v < DEDUP_TTL_SECONDS
            }
        return False

    def _mapped_discord(self, qq_group_id: int) -> Optional[int]:
        for dc_id, info in config.CROSS_PLATFORM_MAP.items():
            if info.get("qq_group_id") == qq_group_id:
                return dc_id
        return None

    def _mapped_qq(self, discord_channel_id: int) -> Optional[int]:
        info = config.CROSS_PLATFORM_MAP.get(discord_channel_id)
        return info.get("qq_group_id") if info else None

    async def forward_qq_to_discord(
        self,
        qq_nickname: str,
        qq_user_id: int,
        group_name: str,
        group_id: int,
        content: str,
        attachments: Optional[List[dict]] = None,
    ):
        """QQ 用户消息 → Discord（handlers 调用）。"""
        dc_id = self._mapped_discord(group_id)
        if dc_id is None:
            return
        if self._seen("qq", group_id, content):
            logger.debug("[CrossPlatformForwarder] QQ→DC 去重命中，跳过")
            return
        await _send_qq_to_discord(qq_nickname, qq_user_id, group_name, group_id, content, attachments)
        self._recent[self._key("discord", dc_id, content)] = time.monotonic()

    async def forward_discord_to_qq(
        self,
        discord_username: str,
        discord_discriminator: str,
        content: str,
        channel_id: int,
        attachments: Optional[List[dict]] = None,
    ):
        """Discord 用户消息 → QQ（handlers 调用）。"""
        qq_group = self._mapped_qq(channel_id)
        if qq_group is None:
            return
        if self._seen("discord", channel_id, content):
            logger.debug("[CrossPlatformForwarder] DC→QQ 去重命中，跳过")
            return
        await _send_discord_to_qq(discord_username, discord_discriminator, content, channel_id, attachments)
        self._recent[self._key("qq", qq_group, content)] = time.monotonic()

    async def notify_qq_sent(
        self,
        qq_nickname: str,
        qq_user_id: int,
        group_name: str,
        group_id: int,
        content: str,
        attachments: Optional[List[dict]] = None,
    ):
        """机器人在 QQ 群发出消息后上报（原 ws.py 镜像职责，含去重防环）。"""
        if not content and not attachments:
            return
        dc_id = self._mapped_discord(group_id)
        if dc_id is None:
            return
        if self._seen("qq", group_id, content):
            logger.debug("[CrossPlatformForwarder] QQ 已发送消息去重命中，跳过")
            return
        await _send_qq_to_discord(qq_nickname, qq_user_id, group_name, group_id, content, attachments)
        self._recent[self._key("discord", dc_id, content)] = time.monotonic()

    async def notify_discord_sent(self, channel_id: int, content: str, sender_name: str = "Bot"):
        """机器人在 Discord 发出消息后上报（原 router 镜像职责，含去重防环）。"""
        if not content:
            return
        qq_group = self._mapped_qq(channel_id)
        if qq_group is None:
            return
        if self._seen("discord", channel_id, content):
            logger.debug("[CrossPlatformForwarder] Discord 已发送消息去重命中，跳过")
            return
        # 机器人回复不做翻译（保持原镜像行为，避免 LLM 延迟）
        await _send_discord_to_qq(sender_name, "", content, channel_id, None, translate=False)
        self._recent[self._key("qq", qq_group, content)] = time.monotonic()


forwarder = CrossPlatformForwarder()


# ── 消息总线接入（阶段 2/3）：跨平台转发由总线驱动 ──────────────
def _segments_to_attachments(segments) -> Optional[List[dict]]:
    """平台消息段 → 转发器附件格式。"""
    result = []
    for seg in segments:
        url = getattr(seg, "url", "") or ""
        if not url:
            continue
        result.append({
            "type": getattr(seg, "type", "image"),
            "url": url,
            "filename": getattr(seg, "filename", "") or "",
        })
    return result or None


async def _bus_qq_incoming(msg):
    """QQ 群消息入站 → 转发到映射的 Discord。"""
    if getattr(msg, "channel_type", "") != "group":
        return
    await forwarder.forward_qq_to_discord(
        qq_nickname=msg.author_name or "玩家",
        qq_user_id=msg.author_id or 0,
        group_name=f"群{msg.channel_id}",
        group_id=msg.channel_id,
        content=msg.content,
        attachments=_segments_to_attachments(msg.segments),
    )


async def _bus_discord_incoming(msg):
    """Discord 消息入站 → 转发到映射的 QQ。"""
    await forwarder.forward_discord_to_qq(
        discord_username=msg.author_name or "Discord",
        discord_discriminator="",
        content=msg.content,
        channel_id=msg.channel_id,
        attachments=_segments_to_attachments(msg.segments),
    )


def _register_bus_subscriptions():
    from neobot.core.messaging.bus import message_bus
    # key 唯一标识本模块的订阅：热重载后同 key 重新注册会自动替换旧订阅，避免订阅者累积
    message_bus.on_incoming("qq", key="forwarder._bus_qq_incoming")(_bus_qq_incoming)
    message_bus.on_incoming("discord", key="forwarder._bus_discord_incoming")(_bus_discord_incoming)


_register_bus_subscriptions()
