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
