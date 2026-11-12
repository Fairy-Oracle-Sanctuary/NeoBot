"""话痨榜只记条数，能按天和按周排前十。"""
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock
from zoneinfo import ZoneInfo

import pytest

from neobot.core.handlers.unknown_command import suggest_command
from neobot.core.managers.command_manager import matcher
from neobot.plugins import chatty

SHANGHAI = ZoneInfo("Asia/Shanghai")


class _Redis:
    def __init__(self):
        self.hashes = {}
        self.expiry = {}

    async def hincrby(self, key, field, amount):
        bucket = self.hashes.setdefault(key, {})
        bucket[str(field)] = int(bucket.get(str(field), 0)) + int(amount)
        return bucket[str(field)]

    async def hgetall(self, key):
        return dict(self.hashes.get(key, {}))

    async def expire(self, key, seconds):
        self.expiry[key] = seconds

    async def hget(self, key, field):
        return None


def test_rank_does_not_keep_message_text():
    rows = chatty.rank_counts({"2": "3", "1": "10", "3": "0"}, top_n=2)
    assert rows == [("1", 10), ("2", 3)]
    text = chatty.format_board("今日话痨 TOP", [("1", "小明", 10)])
    assert "小明 · 10 句" in text
    assert "内容" not in text


def test_hint_vocabulary_ignores_other_bots():
    names = list(matcher.message_handler.platform_commands.get("qq", {}))
    assert "今日话痨" in names
    assert "本周话痨" in names
    assert "我的发言" in names
    assert suggest_command("今日猪猪", names) is None
    assert suggest_command("我的猪圈", names) is None


@pytest.mark.asyncio
async def test_counts_are_per_group_and_week_sums_days(monkeypatch):
    store = _Redis()
    monkeypatch.setattr(chatty.redis_manager, "_redis", store)
    monkeypatch.setattr("neobot.plugins.group_manage.is_feature_enabled", _yes)

    async def _say(group_id, user_id, day):
        event = MagicMock()
        event.group_id = group_id
        event.user_id = user_id
        event.self_id = 1
        monkeypatch.setattr(chatty, "today", lambda now=None: day)
        await chatty.count_message(event)

    monday = datetime(2026, 11, 9, 12, tzinfo=SHANGHAI)
    tuesday = datetime(2026, 11, 10, 12, tzinfo=SHANGHAI)
    await _say(9, 7, monday)
    await _say(9, 7, monday)
    await _say(9, 8, tuesday)
    await _say(10, 7, tuesday)
    monkeypatch.setattr(chatty, "today", lambda now=None: tuesday)

    assert store.hashes[chatty.day_key(9, monday)]["7"] == 2
    assert "8" not in store.hashes[chatty.day_key(9, monday)]
    assert store.expiry[chatty.day_key(9, monday)] == 8 * 86400

    bot = MagicMock()

    async def _member(_group, user_id):
        member = MagicMock()
        member.card = {7: "阿七", 8: "阿八"}[user_id]
        member.nickname = ""
        return member

    bot.get_group_member_info = _member
    event = MagicMock()
    event.group_id = 9
    event.user_id = 7
    event.reply = AsyncMock()
    monkeypatch.setattr(chatty, "recent_days", lambda now=None, count=7: [tuesday, monday])
    await chatty.handle_week(bot, event, [])
    text = event.reply.await_args.args[0]
    assert "阿七 · 2 句" in text
    assert "阿八 · 1 句" in text
    assert text.index("阿七") < text.index("阿八")

    event.reply.reset_mock()
    monkeypatch.setattr(chatty, "recent_days", lambda now=None, count=1: [tuesday])
    await chatty.handle_mine(bot, event, [])
    assert "0 句" in event.reply.await_args.args[0] or "还没说话" in event.reply.await_args.args[0]


async def _yes(*_args, **_kwargs):
    return True
