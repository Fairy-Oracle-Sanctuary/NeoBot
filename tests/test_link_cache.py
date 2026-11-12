"""链接解析缓存：规范化 URL、TTL、同一群去重。"""
from unittest.mock import AsyncMock, MagicMock

import pytest

from neobot.plugins.web_parser.base import BaseParser
from neobot.plugins.web_parser.link_cache import LinkCache, normalize_link, reset_link_cache


def test_normalize_link_strips_tracking_and_unifies_twitter():
    assert normalize_link("https://WWW.Bilibili.com/video/BV1xx/?spm_id_from=333") == (
        "https://bilibili.com/video/BV1xx"
    )
    assert normalize_link("https://twitter.com/someone/status/99?s=20") == "https://x.com/i/status/99"
    assert normalize_link("https://x.com/i/status/99") == "https://x.com/i/status/99"


@pytest.mark.asyncio
async def test_memory_cache_and_group_dedupe(monkeypatch):
    monkeypatch.setattr("neobot.plugins.web_parser.link_cache.redis_manager._redis", None)
    cache = LinkCache(ttl_seconds=600, dedupe_seconds=180, max_items=8)
    key = normalize_link("https://github.com/a/b/")
    assert await cache.get(key) is None
    await cache.set(key, {"title": "b"})
    assert await cache.get(key) == {"title": "b"}
    assert await cache.seen("group:1", key) is False
    await cache.mark("group:1", key)
    assert await cache.seen("group:1", key) is True
    assert await cache.seen("group:2", key) is False


@pytest.mark.asyncio
async def test_memory_cache_stays_bounded(monkeypatch):
    monkeypatch.setattr("neobot.plugins.web_parser.link_cache.redis_manager._redis", None)
    cache = LinkCache(ttl_seconds=600, dedupe_seconds=60, max_items=2)
    await cache.set("https://example.com/1", {"n": 1})
    await cache.set("https://example.com/2", {"n": 2})
    await cache.set("https://example.com/3", {"n": 3})
    assert len(cache._results) <= 2


@pytest.mark.asyncio
async def test_redis_roundtrip_when_available(monkeypatch):
    store = {}

    class _Redis:
        async def get(self, key):
            return store.get(key)

        async def set(self, key, value, ex=None):
            store[key] = value

    monkeypatch.setattr("neobot.plugins.web_parser.link_cache.redis_manager._redis", _Redis())
    writer = LinkCache(ttl_seconds=600, dedupe_seconds=30, max_items=8)
    reader = LinkCache(ttl_seconds=600, dedupe_seconds=30, max_items=8)
    key = "https://bilibili.com/video/BV1"
    await writer.set(key, {"title": "缓存"})
    assert await reader.get(key) == {"title": "缓存"}
    await writer.mark("group:7", key)
    assert await reader.seen("group:7", key) is True


class _Stub(BaseParser):
    def __init__(self):
        super().__init__()
        self.parsed = 0

    async def parse(self, url):
        self.parsed += 1
        return {"title": "ok", "url": url}

    async def get_real_url(self, short_url):
        return short_url

    async def format_response(self, event, data):
        return [{"type": "node", "data": {"content": data["title"]}}]


@pytest.mark.asyncio
async def test_parser_skips_repeat_in_the_same_group(monkeypatch):
    monkeypatch.setattr("neobot.plugins.web_parser.link_cache.redis_manager._redis", None)
    reset_link_cache()
    parser = _Stub()
    parser.name = "测试"

    def _event():
        event = MagicMock()
        event.group_id = 9
        event.user_id = 3
        event.bot.send_forwarded_messages = AsyncMock()
        event.reply = AsyncMock()
        return event

    first = _event()
    second = _event()
    await parser.process_url(first, "https://www.bilibili.com/video/BV1xx")
    await parser.process_url(second, "https://bilibili.com/video/BV1xx?spm_id_from=1")
    assert parser.parsed == 1
    first.bot.send_forwarded_messages.assert_awaited()
    second.bot.send_forwarded_messages.assert_not_called()
