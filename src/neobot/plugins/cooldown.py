"""按 key 冷却。纯内存，方便单测。"""
from __future__ import annotations

import time
from typing import Optional


class Cooldown:
    def __init__(self) -> None:
        self._last: dict[str, float] = {}

    def allow(self, key: str, seconds: float, now: Optional[float] = None) -> bool:
        if seconds <= 0:
            return True
        moment = time.monotonic() if now is None else now
        previous = self._last.get(key)
        if previous is not None and moment - previous < seconds:
            return False
        self._last[key] = moment
        if len(self._last) > 1024:
            for old in list(self._last)[:512]:
                self._last.pop(old, None)
        return True
