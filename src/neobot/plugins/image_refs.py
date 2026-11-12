"""从消息或 get_msg 结果里找出 http 图片地址。"""
from __future__ import annotations

from typing import Any, Iterable, List, Optional


def _http_url(value: object) -> str:
    text = str(value or "")
    if text.startswith("http://") or text.startswith("https://"):
        return text
    return ""


def image_urls_from_segments(message: Iterable[object] | None) -> List[str]:
    found: List[str] = []
    for segment in message or []:
        if getattr(segment, "type", None) != "image":
            continue
        data = getattr(segment, "data", None) or {}
        url = _http_url(data.get("url") or data.get("file"))
        if url and url not in found:
            found.append(url)
    return found


def reply_message_id(message: Iterable[object] | None) -> Optional[str]:
    for segment in message or []:
        if getattr(segment, "type", None) != "reply":
            continue
        data = getattr(segment, "data", None) or {}
        reply_id = data.get("id")
        if reply_id:
            return str(reply_id)
    return None


def image_urls_from_payload(payload: Any) -> List[str]:
    """兼容 get_msg 返回的 dict，以及消息段列表。"""
    if payload is None:
        return []
    message = payload
    if isinstance(payload, dict):
        message = payload.get("message", payload.get("data"))
        if isinstance(message, dict):
            message = message.get("message", message)
    found: List[str] = []
    if not isinstance(message, list):
        return found
    for segment in message:
        if isinstance(segment, dict):
            if segment.get("type") != "image":
                continue
            data = segment.get("data") or {}
            url = _http_url(data.get("url") or data.get("file"))
        else:
            if getattr(segment, "type", None) != "image":
                continue
            data = getattr(segment, "data", None) or {}
            url = _http_url(data.get("url") or data.get("file"))
        if url and url not in found:
            found.append(url)
    return found
