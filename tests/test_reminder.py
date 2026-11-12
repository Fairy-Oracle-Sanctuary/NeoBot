"""定时提醒：时间解析、上限、到点 @ 人，以及重启后仍能从 Redis 读出来。"""
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from neobot.core.handlers.unknown_command import suggest_command
from neobot.core.managers.command_manager import matcher
from neobot.plugins import reminder

SHANGHAI = ZoneInfo("Asia/Shanghai")
NOW = datetime(2026, 11, 12, 10, 0, tzinfo=SHANGHAI)


class _Redis:
    def __init__(self):
        self.kv = {}
        self.sets = {}

    async def get(self, key):
        return self.kv.get(key)

    async def set(self, key, value, ex=None):
        self.kv[key] = value

    async def delete(self, *keys):
        for key in keys:
            self.kv.pop(key, None)

    async def sadd(self, key, *values):
        self.sets.setdefault(key, set()).update(str(value) for value in values)

    async def srem(self, key, *values):
        bucket = self.sets.setdefault(key, set())
        for value in values:
            bucket.discard(str(value))

    async def smembers(self, key):
        return set(self.sets.get(key, ()))

    async def scard(self, key):
        return len(self.sets.get(key, ()))

    async def hget(self, key, field):
        return None


def test_parse_examples():
    drink = reminder.parse_reminder("30分钟 喝水", NOW)
    assert drink["kind"] == "once"
    assert drink["text"] == "喝水"
    assert drink["next_at"] == int(datetime(2026, 11, 12, 10, 30, tzinfo=SHANGHAI).timestamp())

    meeting = reminder.parse_reminder("明天 9:00 开会", NOW)
    assert meeting["kind"] == "once"
    assert meeting["text"] == "开会"
    assert meeting["next_at"] == int(datetime(2026, 11, 13, 9, 0, tzinfo=SHANGHAI).timestamp())

    night = reminder.parse_reminder("每天 21:00 互道晚安", NOW)
    assert night["kind"] == "daily"
    assert night["hour"] == 21 and night["minute"] == 0
    assert night["text"] == "互道晚安"

    too_soon = reminder.parse_reminder("每10分钟 喝水", NOW)
    assert "30" in too_soon
    past = reminder.parse_reminder("今天 9:00 开会", NOW)
    assert "已经过了" in past
    assert reminder.parse_reminder("列表", NOW)["action"] == "list"
    assert reminder.parse_reminder("删除 ab12cd", NOW) == {"action": "delete", "id": "ab12cd"}


def test_commands_join_the_hint_vocabulary():
    names = list(matcher.message_handler.platform_commands.get("qq", {}))
    assert "提醒" in names
    assert "schedule" in names
    assert suggest_command("今日猪猪", names) is None
    assert suggest_command("我的猪圈", names) is None
    assert suggest_command("提醒下", names) == "提醒"


@pytest.mark.asyncio
async def test_create_list_fire_and_survive_reload(monkeypatch):
    store = _Redis()
    monkeypatch.setattr(reminder.redis_manager, "_redis", store)
    monkeypatch.setattr(
        "neobot.plugins.group_manage.is_feature_enabled",
        _async_true,
    )
    event = _event()
    await reminder.handle_reminder(None, event, ["30分钟", "喝水"])
    reply = event.reply.await_args.args[0]
    assert "喝水" in reply
    reminder_id = reply.strip().split()[-1]
    assert reminder_id in store.kv[reminder._item_key(reminder_id)] or store.kv

    event.reply.reset_mock()
    await reminder.handle_reminder(None, event, ["列表"])
    listed = event.reply.await_args.args[0]
    assert reminder_id in listed
    assert "喝水" in listed

    sent = []

    async def _send(group_id, user_id, text):
        sent.append((group_id, user_id, text))

    stored = reminder.json.loads(store.kv[reminder._item_key(reminder_id)])
    later = datetime.fromtimestamp(stored["next_at"], SHANGHAI)
    fired = await reminder.reminder_tick(later, sender=_send)
    assert fired == 1
    assert sent == [(100, 7, "喝水")]
    assert await store.get(reminder._item_key(reminder_id)) is None

    # 循环提醒写回 Redis，新的存储对象也能读到并再次触发
    event.reply.reset_mock()
    await reminder.handle_reminder(None, event, ["每天", "21:00", "互道晚安"])
    raw_id = event.reply.await_args.args[0].strip().split()[-1]
    fresh = _Redis()
    fresh.kv = dict(store.kv)
    fresh.sets = {key: set(values) for key, values in store.sets.items()}
    monkeypatch.setattr(reminder.redis_manager, "_redis", fresh)
    sent.clear()
    stored_daily = reminder.json.loads(fresh.kv[reminder._item_key(raw_id)])
    evening = datetime.fromtimestamp(stored_daily["next_at"], SHANGHAI)
    assert await reminder.reminder_tick(evening, sender=_send) == 1
    assert sent[0][2] == "互道晚安"
    kept = await reminder._load(fresh, raw_id)
    assert kept is not None
    assert kept["kind"] == "daily"
    assert int(kept["next_at"]) > int(evening.timestamp())


@pytest.mark.asyncio
async def test_user_cap_and_group_switch(monkeypatch):
    store = _Redis()
    monkeypatch.setattr(reminder.redis_manager, "_redis", store)
    monkeypatch.setattr(reminder, "_limits", lambda: (1, 40, 30))
    monkeypatch.setattr("neobot.plugins.group_manage.is_feature_enabled", _async_true)
    event = _event()
    await reminder.handle_reminder(None, event, ["30分钟", "喝水"])
    event.reply.reset_mock()
    await reminder.handle_reminder(None, event, ["1小时", "伸懒腰"])
    assert "排满" in event.reply.await_args.args[0]

    async def _off(*_args, **_kwargs):
        return False

    monkeypatch.setattr("neobot.plugins.group_manage.is_feature_enabled", _off)
    event.reply.reset_mock()
    await reminder.handle_reminder(None, event, ["列表"])
    assert "收起来" in event.reply.await_args.args[0]


def _event():
    from unittest.mock import AsyncMock, MagicMock

    event = MagicMock()
    event.group_id = 100
    event.user_id = 7
    event.reply = AsyncMock()
    return event


async def _async_true(*_args, **_kwargs):
    return True
