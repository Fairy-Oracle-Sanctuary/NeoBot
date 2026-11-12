"""每日运势 / 今天吃什么，以及未知指令的近邻提示。"""
from unittest.mock import AsyncMock, MagicMock

import pytest

from neobot.core.handlers.event_handler import MessageHandler
from neobot.core.handlers.unknown_command import HintRateLimiter, suggest_command
from neobot.plugins import daily


def test_fortune_is_stable_for_the_same_user_and_day():
    first = daily.fortune_text(1001, "2026-11-12", salt="s")
    second = daily.fortune_text(1001, "2026-11-12", salt="s")
    other_user = daily.fortune_text(1002, "2026-11-12", salt="s")
    other_day = daily.fortune_text(1001, "2026-11-13", salt="s")
    assert first == second
    assert "今日运势" in first
    assert other_user != first
    assert other_day != first


def test_food_uses_configured_list_and_falls_back_when_empty():
    rng = __import__("random").Random(0)
    assert daily.food_text(["  煎饺  ", ""], rng) == "今天就吃「煎饺」吧。"
    picked = daily.food_text([], __import__("random").Random(1))
    assert picked.startswith("今天就吃「") and picked.endswith("」吧。")
    name = picked.removeprefix("今天就吃「").removesuffix("」吧。")
    assert name in daily.DEFAULT_FOODS


def test_suggest_only_when_close_and_not_ignored():
    known = ["今日运势", "今天吃什么", "echo"]
    assert suggest_command("echoo", known) == "echo"
    assert suggest_command("今天吃啥", known) == "今天吃什么"
    assert suggest_command("今日猪猪", known) is None
    assert suggest_command("我的猪圈", known) is None
    assert suggest_command("完全不相关xyz", known) is None
    assert suggest_command("运势", known) == "今日运势"


def test_hint_rate_limit_is_per_key():
    limiter = HintRateLimiter()
    assert limiter.allow("group:1", 60, now=100)
    assert limiter.allow("group:1", 60, now=120) is False
    assert limiter.allow("group:2", 60, now=120) is True
    assert limiter.allow("group:1", 60, now=160) is True


@pytest.mark.asyncio
async def test_fortune_command_replies_same_text(monkeypatch):
    monkeypatch.setattr(daily, "_today", lambda: "2026-11-12")
    monkeypatch.setattr(daily, "_salt", lambda: "salt")
    event = MagicMock()
    event.user_id = 42
    event.reply = AsyncMock()
    await daily.handle_fortune(None, event, [])
    await daily.handle_fortune(None, event, [])
    first = event.reply.await_args_list[0].args[0]
    second = event.reply.await_args_list[1].args[0]
    assert first == second
    assert "今日运势" in first


@pytest.mark.asyncio
async def test_unknown_command_hint_silence_and_rate_limit():
    handler = MessageHandler(prefixes=("/",))
    handler.commands["echo"] = {
        "func": AsyncMock(),
        "permission": None,
        "override_permission_check": False,
        "plugin_name": "echo",
    }
    handler.commands["今天吃什么"] = dict(handler.commands["echo"])

    async def _ask(text: str, reply: AsyncMock):
        event = MagicMock()
        event.raw_message = text
        event.user_id = 7
        event.group_id = 9
        event.reply = reply
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(
                "neobot.core.handlers.event_handler.redis_manager.execute_lua_script",
                AsyncMock(),
            )
            await handler.handle(MagicMock(), event)

    close = AsyncMock()
    await _ask("/echoo", close)
    close.assert_awaited_once()
    assert close.await_args.args[0] == "你是不是想用 /echo ？"

    again = AsyncMock()
    await _ask("/echoo", again)
    again.assert_not_awaited()

    ignored = AsyncMock()
    await _ask("/今日猪猪", ignored)
    ignored.assert_not_awaited()

    far = AsyncMock()
    await _ask("/我的猪圈", far)
    far.assert_not_awaited()

    unrelated = AsyncMock()
    await _ask("/完全不相关xyz", unrelated)
    unrelated.assert_not_awaited()
