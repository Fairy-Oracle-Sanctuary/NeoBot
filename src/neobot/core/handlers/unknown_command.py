"""未知 /指令 的近邻提示。差得远的指令保持沉默。"""
from __future__ import annotations

import difflib
import time
from typing import Iterable, Optional

DEFAULT_IGNORE = ("今日猪猪", "我的猪圈")
DEFAULT_CUTOFF = 0.6


def normalize_command_name(name: str) -> str:
    text = (name or "").strip()
    if text.startswith("/"):
        text = text[1:].strip()
    return text


def suggest_command(
    query: str,
    known: Iterable[str],
    ignore: Iterable[str] = DEFAULT_IGNORE,
    cutoff: float = DEFAULT_CUTOFF,
) -> Optional[str]:
    """
    只有和一个已注册指令足够像时才返回建议。

    忽略名单里的名字（别的机器人的指令）直接返回 None，即使它和本机器人的指令有点像。
    """
    query_name = normalize_command_name(query)
    if len(query_name) < 2:
        return None
    ignored = {normalize_command_name(item) for item in ignore}
    ignored.discard("")
    if query_name in ignored:
        return None

    candidates = []
    seen = set()
    for name in known:
        cleaned = normalize_command_name(name)
        if not cleaned or cleaned in ignored or cleaned in seen:
            continue
        seen.add(cleaned)
        candidates.append(cleaned)
    if query_name in seen:
        return None
    matches = difflib.get_close_matches(query_name, candidates, n=1, cutoff=cutoff)
    return matches[0] if matches else None


class HintRateLimiter:
    """按群（或私聊用户）限制提示频率。"""

    def __init__(self) -> None:
        self._last: dict[str, float] = {}

    def allow(self, key: str, interval: float, now: Optional[float] = None) -> bool:
        if interval < 0:
            return False
        moment = time.monotonic() if now is None else now
        previous = self._last.get(key)
        if previous is not None and moment - previous < interval:
            return False
        self._last[key] = moment
        if len(self._last) > 512:
            for old in list(self._last)[:256]:
                self._last.pop(old, None)
        return True
