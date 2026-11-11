# -*- coding: utf-8 -*-
"""
出站消息镜像（QQ 群 / Discord → 另一端）。

核心只在总线上发布 PlatformMessage，本模块把平台原始内容还原成
转发器需要的文本与附件。订阅者异常由 MessageBus 隔离，不会打断发送。
"""
from typing import Any, Awaitable, Callable, List, Optional, Tuple

from neobot.plugin_api import ModuleLogger

logger = ModuleLogger("GatewayMirror")

NotifyQQ = Callable[..., Awaitable[None]]
NotifyDiscord = Callable[..., Awaitable[None]]
FetchReply = Callable[[Any], Awaitable[Any]]


def _build_filename(msg_type: str, data: dict) -> str:
    filename = data.get("filename", "")
    if filename:
        return filename
    file_field = data.get("file", "")
    if file_field and not str(file_field).startswith(("http", "data:", "/")):
        return str(file_field)
    ext_map = {"image": ".png", "video": ".mp4", "record": ".wav", "file": ".bin"}
    return msg_type + ext_map.get(msg_type, ".bin")


def _consume_segment(seg: Any, content: str, attachments: List[dict], reply_ids: List[Any]) -> str:
    """把一个 OneBot 消息段并入文本 / 附件 / 回复 id。"""
    if isinstance(seg, dict):
        seg_type = seg.get("type")
        data = seg.get("data", {}) or {}
        if seg_type == "text":
            content += data.get("text", "")
        elif seg_type == "at":
            content += f"@{data.get('qq', '')}"
        elif seg_type == "reply":
            reply_id = data.get("id", "")
            if reply_id:
                reply_ids.append(reply_id)
        elif seg_type in ("image", "video", "record", "file"):
            url = data.get("url") or data.get("file")
            if url:
                attachments.append({
                    "type": seg_type,
                    "url": str(url),
                    "filename": _build_filename(seg_type, data),
                })
    elif isinstance(seg, str):
        content += seg
    return content


def parse_onebot_outgoing(message: Any) -> Tuple[str, List[dict], List[Any]]:
    """OneBot 消息（str / dict / list）→ (文本, 附件, 回复 id 列表)。"""
    content = ""
    attachments: List[dict] = []
    reply_ids: List[Any] = []
    if isinstance(message, list):
        for seg in message:
            content = _consume_segment(seg, content, attachments, reply_ids)
    elif isinstance(message, (dict, str)):
        content = _consume_segment(message, content, attachments, reply_ids)
    return content, attachments, reply_ids


def _as_message_dict(result: Any) -> Optional[dict]:
    """兼容 get_msg 的 data 字典，以及仍包着 ``data`` 键的完整 API 响应。"""
    if not isinstance(result, dict):
        return None
    data = result.get("data")
    if isinstance(data, dict) and ("message" in data or "raw_message" in data):
        return data
    if "message" in result or "raw_message" in result:
        return result
    return None


def _reply_text(reply_msg: dict) -> str:
    raw = reply_msg.get("raw_message", "") or ""
    message = reply_msg.get("message")
    if isinstance(message, list):
        raw = "".join(
            segment.get("data", {}).get("text", "")
            for segment in message
            if isinstance(segment, dict) and segment.get("type") == "text"
        )
    return str(raw) if raw else ""


async def _apply_reply_quotes(content: str, reply_ids: List[Any], fetch_reply: FetchReply) -> str:
    for reply_id in reply_ids:
        try:
            reply_msg = _as_message_dict(await fetch_reply(reply_id))
            if reply_msg is None:
                content = f"[回复消息 #{reply_id}] {content}"
                continue
            raw = _reply_text(reply_msg)
            if raw:
                content = f"> {raw[:200]}\n" + content
        except Exception:
            content = f"[回复消息 #{reply_id}] {content}"
    return content


async def handle_outgoing_message(
    msg: Any,
    *,
    notify_qq_sent: NotifyQQ,
    notify_discord_sent: NotifyDiscord,
    fetch_reply: FetchReply,
    enabled: bool,
) -> None:
    """把一条出站 PlatformMessage 交给跨平台转发器。

    ``metadata['no_mirror']`` 为真时直接返回,避免 Discord→QQ 回环。
    ``enabled`` 为假时不做任何转发(对应跨平台开关)。
    """
    metadata = getattr(msg, "metadata", None) or {}
    if metadata.get("no_mirror"):
        return
    if not enabled:
        return

    platform = getattr(msg, "platform", "")
    if platform == "qq" and getattr(msg, "channel_type", "") == "group":
        content, attachments, reply_ids = parse_onebot_outgoing(getattr(msg, "raw", None))
        if reply_ids:
            content = await _apply_reply_quotes(content, reply_ids, fetch_reply)
        if not content and not attachments:
            logger.debug("[GatewayMirror:QQ→DC] 消息内容为空，跳过")
            return
        group_id = getattr(msg, "channel_id", None)
        logger.debug(
            f"[GatewayMirror:QQ→DC] 提取内容: content_len={len(content)}, attachments={len(attachments)}"
        )
        logger.info(
            f"[GatewayMirror:QQ→DC] 上报 QQ 已发送消息: group={group_id}, content='{content[:80]}...'"
        )
        await notify_qq_sent(
            qq_nickname="NeoBot",
            qq_user_id=getattr(msg, "author_id", 0) or 0,
            group_name=f"群{group_id}",
            group_id=group_id,
            content=content,
            attachments=attachments,
        )
        return

    if platform == "discord":
        content = getattr(msg, "content", "") or ""
        if not content:
            return
        sender_name = getattr(msg, "author_name", "") or "Bot"
        await notify_discord_sent(
            int(getattr(msg, "channel_id", 0) or 0),
            content,
            sender_name=sender_name,
        )
