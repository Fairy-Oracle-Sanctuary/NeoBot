"""生日只存月-日，当天在还在群里的人面前说一句。"""
from datetime import date, datetime
from unittest.mock import AsyncMock, MagicMock
from zoneinfo import ZoneInfo

import pytest

from neobot.core.handlers.unknown_command import suggest_command
from neobot.core.managers.command_manager import matcher
from neobot.plugins import birthday

SHANGHAI = ZoneInfo("Asia/Shanghai")


class _Redis:
    def __init__(self):
        self.hashes = {}
        self.sets = {}
        self.kv = {}

    async def hset(self, key, field, value):
        self.hashes.setdefault(key, {})[str(field)] = value

    async def hgetall(self, key):
        return dict(self.hashes.get(key, {}))

    async def hdel(self, key, field):
        bucket = self.hashes.setdefault(key, {})
        return 1 if bucket.pop(str(field), None) is not None else 0

    async def hlen(self, key):
        return len(self.hashes.get(key, {}))

    async def sadd(self, key, *values):
        self.sets.setdefault(key, set()).update(str(value) for value in values)

    async def srem(self, key, *values):
        bucket = self.sets.setdefault(key, set())
        removed = 0
        for value in values:
            if str(value) in bucket:
                bucket.remove(str(value))
                removed += 1
        return removed

    async def smembers(self, key):
        return set(self.sets.get(key, ()))

    async def get(self, key):
        return self.kv.get(key)

    async def set(self, key, value, ex=None):
        self.kv[key] = value


def test_parse_keeps_month_day_only():
    assert birthday.parse_birthday("3-14") == "03-14"
    assert birthday.parse_birthday("02-29") == "02-29"
    assert birthday.parse_birthday("02-30") is None
    assert birthday.parse_birthday("2000-01-01") is None
    assert birthday.contains_year("2000-01-01")
    rows = birthday.upcoming([("7", "11-20"), ("8", "01-01")], date(2026, 11, 12), 30)
    assert rows[0][1] == "7"
    assert all(len(mmdd) == 5 and mmdd[2] == "-" for _delta, _uid, mmdd in rows)
    text = birthday.wish_text(7, date(2026, 11, 12))
    assert "岁" not in text and "年龄" not in text


def test_feb_29_is_celebrated_on_feb_28_in_non_leap_years():
    assert birthday.celebration_date("02-29", 2026) == date(2026, 2, 28)
    assert birthday.is_birthday_today("02-29", date(2026, 2, 28))
    assert birthday.celebration_date("02-29", 2024) == date(2024, 2, 29)


def test_commands_are_hintable_without_touching_other_bots():
    names = list(matcher.message_handler.platform_commands.get("qq", {}))
    assert "登记生日" in names
    assert "生日列表" in names
    assert suggest_command("今日猪猪", names) is None
    assert suggest_command("我的猪圈", names) is None


@pytest.mark.asyncio
async def test_registration_is_group_scoped_and_job_skips_absent_members(monkeypatch):
    store = _Redis()
    monkeypatch.setattr(birthday.redis_manager, "_redis", store)
    monkeypatch.setattr("neobot.plugins.group_manage.is_feature_enabled", _yes)

    async def _register(group_id, user_id, text):
        event = MagicMock()
        event.group_id = group_id
        event.user_id = user_id
        event.reply = AsyncMock()
        await birthday.handle_register(None, event, text.split())
        return event

    await _register(1, 7, "11-12")
    await _register(2, 7, "01-02")
    assert store.hashes[birthday._group_key(1)]["7"] == "11-12"
    assert store.hashes[birthday._group_key(2)]["7"] == "01-02"
    assert "年" not in store.hashes[birthday._group_key(1)]["7"]

    sent = []

    async def _send(group_id, user_id, text):
        sent.append((group_id, user_id, text))

    async def _present(group_id, user_id):
        return group_id == 1

    morning = datetime(2026, 11, 12, 9, 5, tzinfo=SHANGHAI)
    assert await birthday.birthday_tick(morning, sender=_send, member_present=_present) == 1
    assert sent == [(1, 7, sent[0][2])]
    assert "岁" not in sent[0][2]
    assert await birthday.birthday_tick(morning, sender=_send, member_present=_present) == 0

    early = datetime(2026, 11, 12, 8, 0, tzinfo=SHANGHAI)
    assert birthday.in_send_window(early) is False


async def _yes(*_args, **_kwargs):
    return True
