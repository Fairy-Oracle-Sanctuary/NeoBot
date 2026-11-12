"""链接解析结果缓存，以及同一群短时间内不重复解析。

Redis 可用时结果放 Redis，否则用内存 LRU。两边都有容量上限。
"""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Optional
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from cachetools import TTLCache

from neobot.plugin_api import logger, redis_manager

_STATUS_RE = re.compile(
    r"(?:https?://)?(?:www\.)?(?:mobile\.)?(?:twitter\.com|x\.com)/(?:[\w]+/)?status/(\d+)",
    re.IGNORECASE,
)
_DROP_QUERY = {
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_term",
    "utm_content",
    "spm",
    "spm_id_from",
    "vd_source",
    "share_source",
    "share_medium",
    "seid",
    "from",
}

_cache: Optional["LinkCache"] = None


def normalize_link(url: str) -> str:
    """把同一条内容的不同写法收成一个缓存键。"""
    text = (url or "").strip()
    status = _STATUS_RE.search(text)
    if status:
        return f"https://x.com/i/status/{status.group(1)}"
    if not text:
        return ""
    if not text.startswith(("http://", "https://")):
        text = "https://" + text
    parsed = urlparse(text)
    host = (parsed.hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    if host in ("mobile.twitter.com", "twitter.com", "mobile.x.com"):
        host = "x.com"
    port = f":{parsed.port}" if parsed.port else ""
    path = parsed.path.rstrip("/") or "/"
    query = urlencode(
        [
            (key, value)
            for key, value in parse_qsl(parsed.query, keep_blank_values=False)
            if key not in _DROP_QUERY
        ]
    )
    scheme = (parsed.scheme or "https").lower()
    return urlunparse((scheme, host + port, path, "", query, ""))


def _settings() -> tuple[int, int, int]:
    ttl = 600
    dedupe = 180
    max_items = 256
    try:
        from neobot.plugin_api import global_config
        section = global_config.link_cache
        ttl = max(1, int(section.ttl_seconds))
        dedupe = max(1, int(section.dedupe_seconds))
        max_items = max(8, int(section.max_items))
    except Exception:
        pass
    return ttl, dedupe, max_items


class LinkCache:
    def __init__(self, ttl_seconds: int = 600, dedupe_seconds: int = 180, max_items: int = 256):
        self.ttl_seconds = ttl_seconds
        self.dedupe_seconds = dedupe_seconds
        self._results: TTLCache[str, Any] = TTLCache(maxsize=max_items, ttl=ttl_seconds)
        self._seen: TTLCache[str, bool] = TTLCache(maxsize=max(max_items * 4, 32), ttl=dedupe_seconds)

    @classmethod
    def from_config(cls) -> "LinkCache":
        ttl, dedupe, max_items = _settings()
        return cls(ttl, dedupe, max_items)

    def normalize(self, url: str) -> str:
        return normalize_link(url)

    def scope_for(self, event: Any) -> str:
        group_id = getattr(event, "group_id", None)
        if group_id:
            return f"group:{group_id}"
        return f"user:{getattr(event, 'user_id', 0)}"

    def _digest(self, normalized: str) -> str:
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()

    def _redis(self):
        client = getattr(redis_manager, "_redis", None)
        return client

    async def get(self, normalized: str) -> Any:
        if not normalized:
            return None
        if normalized in self._results:
            return self._results[normalized]
        client = self._redis()
        if client is None:
            return None
        try:
            raw = await client.get(self._result_key(normalized))
        except Exception as exc:
            logger.debug(f"[LinkCache] 读取 Redis 失败: {type(exc).__name__}")
            return None
        if not raw:
            return None
        try:
            data = json.loads(raw)
        except (TypeError, ValueError):
            return None
        self._results[normalized] = data
        return data

    async def set(self, normalized: str, data: Any) -> None:
        if not normalized or data is None:
            return
        self._results[normalized] = data
        client = self._redis()
        if client is None:
            return
        try:
            payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
        except (TypeError, ValueError):
            return
        if len(payload) > 200_000:
            return
        try:
            await client.set(self._result_key(normalized), payload, ex=self.ttl_seconds)
        except Exception as exc:
            logger.debug(f"[LinkCache] 写入 Redis 失败: {type(exc).__name__}")

    async def seen(self, scope: str, normalized: str) -> bool:
        """同一范围里这个链接是否刚发过。"""
        if not normalized:
            return False
        key = f"{scope}|{normalized}"
        if key in self._seen:
            return True
        client = self._redis()
        if client is None:
            return False
        try:
            return bool(await client.get(self._dedupe_key(scope, normalized)))
        except Exception:
            return False

    async def mark(self, scope: str, normalized: str) -> None:
        if not normalized:
            return
        self._seen[f"{scope}|{normalized}"] = True
        client = self._redis()
        if client is None:
            return
        try:
            await client.set(self._dedupe_key(scope, normalized), "1", ex=self.dedupe_seconds)
        except Exception as exc:
            logger.debug(f"[LinkCache] 写入去重标记失败: {type(exc).__name__}")

    def _result_key(self, normalized: str) -> str:
        return f"neobot:linkcache:{self._digest(normalized)}"

    def _dedupe_key(self, scope: str, normalized: str) -> str:
        safe_scope = scope.replace(" ", "")
        return f"neobot:linkdedupe:{safe_scope}:{self._digest(normalized)}"


def get_link_cache() -> LinkCache:
    global _cache
    if _cache is None:
        _cache = LinkCache.from_config()
    return _cache


def reset_link_cache() -> LinkCache:
    """测试用：按当前配置重建缓存。"""
    global _cache
    _cache = LinkCache.from_config()
    return _cache
