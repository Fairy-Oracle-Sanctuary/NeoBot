"""从消息段里取出 @ 到的用户。"""
from __future__ import annotations

from typing import Iterable, List


def mentioned_user_ids(message: Iterable[object] | None) -> List[int]:
    found: List[int] = []
    for segment in message or []:
        if getattr(segment, "type", None) != "at":
            continue
        data = getattr(segment, "data", None) or {}
        qq = str(data.get("qq") or "")
        if qq.isdigit() and qq != "0":
            user_id = int(qq)
            if user_id not in found:
                found.append(user_id)
    return found
