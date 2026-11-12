"""/py 默认关闭，Docker 只在真正要用的时候才碰。"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from neobot.core.config_models import CodePyModel
from neobot.plugins import code_py


def test_code_py_defaults_to_disabled():
    assert CodePyModel().enabled is False


@pytest.mark.asyncio
async def test_disabled_sandbox_replies_without_docker():
    event = MagicMock()
    event.bot.code_executor = None
    event.reply = AsyncMock()
    with patch("docker.from_env") as mock_from_env:
        assert await code_py.sandbox_ready(event) is False
        mock_from_env.assert_not_called()
    text = event.reply.await_args.args[0]
    assert "歇着" in text


@pytest.mark.asyncio
async def test_non_admin_gets_disabled_notice_before_permission(monkeypatch):
    from neobot.core.managers.command_manager import matcher

    event = MagicMock()
    event.platform = "qq"
    event.user_id = 42
    event.reply = AsyncMock()
    event.bot = MagicMock()
    event.bot.code_executor = None
    monkeypatch.setattr(code_py.permission_manager, "check_permission", AsyncMock(return_value=False))
    await matcher.message_handler._dispatch_platform_commands(
        event, raw_text="/py print(1)", prefix_found="/"
    )
    text = event.reply.await_args.args[0]
    assert "歇着" in text
    assert "权限" not in text


@pytest.mark.asyncio
async def test_enabled_non_admin_does_not_learn_docker_state(monkeypatch):
    from neobot.core.managers.command_manager import matcher

    executor = MagicMock()
    executor.enabled = True
    executor.ensure_ready = AsyncMock(return_value=False)
    executor.add_task = AsyncMock()
    event = MagicMock()
    event.platform = "qq"
    event.user_id = 42
    event.reply = AsyncMock()
    event.bot = MagicMock()
    event.bot.code_executor = executor
    monkeypatch.setattr(code_py.permission_manager, "check_permission", AsyncMock(return_value=False))
    await matcher.message_handler._dispatch_platform_commands(
        event, raw_text="/py print(1)", prefix_found="/"
    )
    text = event.reply.await_args.args[0]
    assert "权限" in text
    executor.ensure_ready.assert_not_called()
    executor.add_task.assert_not_called()


@pytest.mark.asyncio
async def test_multiline_checks_enabled_before_admin_and_docker(monkeypatch):
    event = MagicMock()
    event.user_id = 9
    event.group_id = 3
    event.raw_message = "print(1)"
    event.reply = AsyncMock()
    executor = MagicMock()
    executor.enabled = True
    executor.ensure_ready = AsyncMock(return_value=False)
    event.bot = MagicMock()
    event.bot.code_executor = executor
    key = (9, 3)
    code_py.multi_line_sessions[key] = MagicMock()
    monkeypatch.setattr(code_py.permission_manager, "check_permission", AsyncMock(return_value=False))
    try:
        await code_py.handle_multi_line_code(event)
    finally:
        code_py.multi_line_sessions.pop(key, None)
    text = event.reply.await_args.args[0]
    assert "权限" in text
    executor.ensure_ready.assert_not_called()


@pytest.mark.asyncio
async def test_enabled_but_docker_down_is_friendly():
    executor = MagicMock()
    executor.enabled = True
    executor.ensure_ready = AsyncMock(return_value=False)
    event = MagicMock()
    event.bot.code_executor = executor
    event.reply = AsyncMock()
    assert await code_py.sandbox_ready(event) is False
    text = event.reply.await_args.args[0]
    assert "Docker" in text
    assert "不跑" in text
