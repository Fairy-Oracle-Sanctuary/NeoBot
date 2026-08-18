"""
/群管 指令行为测试：群管理员开关功能、权限校验、默认开启、挂钩生效。
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from neobot.core.managers.command_manager import matcher
from neobot.plugins import group_manage
from neobot.plugins.group_manage import (
    is_feature_enabled,
    handle_group_manage,
    _parse_args,
)


def _make_event(group_id=10001, user_id=2221577113, args=None, message_type="group"):
    """构造带 group_id/user_id/reply 的假事件。"""
    event = MagicMock()
    event.group_id = group_id
    event.user_id = user_id
    event.message_type = message_type
    event.reply = AsyncMock()
    return event


def _make_bot(role="owner"):
    """构造 get_group_member_info 返回指定角色的假 bot。"""
    bot = AsyncMock()
    member = MagicMock()
    member.role = role
    bot.get_group_member_info = AsyncMock(return_value=member)
    return bot


@pytest.fixture(autouse=True)
def fake_redis():
    """给 group_manage 注入假的 Redis hash 存储。"""
    store = {}

    fake = AsyncMock()
    async def fake_hget(key, field):
        return store.get((key, field))

    async def fake_hset(key, field, value):
        store[(key, field)] = value

    fake.hget = fake_hget
    fake.hset = fake_hset

    with patch.object(group_manage.redis_manager, "_redis", fake):
        fake._store = store
        yield fake


class TestParseArgs:
    def test_no_args_means_view(self):
        assert _parse_args([]) == (None, None)

    def test_view_keyword(self):
        assert _parse_args(["查看"]) == (None, None)
        assert _parse_args(["状态"]) == (None, None)

    def test_enable_feature(self):
        assert _parse_args(["开", "视频解析"]) == ("开", "视频解析")

    def test_disable_feature_alias(self):
        assert _parse_args(["关", "推送"]) == ("关", "推送")

    def test_feature_first_order(self):
        assert _parse_args(["视频解析", "开"]) == ("开", "视频解析")

    def test_missing_feature(self):
        action, err = _parse_args(["开"])
        assert action is None
        assert err is not None and "格式" in err


class TestFeatureSwitch:
    @pytest.mark.asyncio
    async def test_default_enabled(self, fake_redis):
        """未设置任何开关时功能默认开启。"""
        assert await is_feature_enabled(10001, "video_parse") is True
        assert await is_feature_enabled(10001, "push") is True

    @pytest.mark.asyncio
    async def test_toggle_off_then_on(self, fake_redis):
        """关闭后为 False，重新开启后恢复 True。"""
        bot = _make_bot()
        event = _make_event()

        await handle_group_manage(bot, event, ["关", "视频解析"])
        assert await is_feature_enabled(10001, "video_parse") is False

        await handle_group_manage(bot, event, ["开", "视频解析"])
        assert await is_feature_enabled(10001, "video_parse") is True

    @pytest.mark.asyncio
    async def test_per_group_isolation(self, fake_redis):
        """开关仅对当前群生效，其他群不受影响。"""
        bot = _make_bot()
        event = _make_event(group_id=10001)

        await handle_group_manage(bot, event, ["关", "推送"])

        assert await is_feature_enabled(10001, "push") is False
        assert await is_feature_enabled(10002, "push") is True


class TestPermission:
    @pytest.mark.asyncio
    async def test_owner_can_toggle(self, fake_redis):
        bot = _make_bot(role="owner")
        event = _make_event()
        await handle_group_manage(bot, event, ["关", "推送"])
        assert await is_feature_enabled(10001, "push") is False

    @pytest.mark.asyncio
    async def test_admin_can_toggle(self, fake_redis):
        bot = _make_bot(role="admin")
        event = _make_event()
        await handle_group_manage(bot, event, ["关", "推送"])
        assert await is_feature_enabled(10001, "push") is False

    @pytest.mark.asyncio
    async def test_normal_member_cannot_toggle(self, fake_redis):
        bot = _make_bot(role="member")
        event = _make_event()
        await handle_group_manage(bot, event, ["关", "推送"])
        # 未被修改，仍为默认开启
        assert await is_feature_enabled(10001, "push") is True
        event.reply.assert_called_once()
        assert "只有本群的群主/管理员" in event.reply.call_args[0][0]

    @pytest.mark.asyncio
    async def test_normal_member_cannot_view(self, fake_redis):
        """整个 /群管 指令（含查看）仅限本群群主/管理员。"""
        bot = _make_bot(role="member")
        event = _make_event()
        await handle_group_manage(bot, event, [])
        event.reply.assert_called_once()
        assert "只有本群的群主/管理员" in event.reply.call_args[0][0]
        # 未返回开关状态内容
        assert "功能开关" not in event.reply.call_args[0][0]

    @pytest.mark.asyncio
    async def test_private_chat_rejected(self, fake_redis):
        bot = _make_bot()
        event = _make_event(group_id=0)
        await handle_group_manage(bot, event, ["关", "推送"])
        event.reply.assert_called_once()
        assert "仅在群聊中可用" in event.reply.call_args[0][0]


class TestRedisFailure:
    @pytest.mark.asyncio
    async def test_read_failure_falls_open(self, fake_redis):
        """Redis 读取失败时功能保守地视为开启（不误伤正常功能）。"""
        # 让 hget 抛异常
        fake_redis.hget = AsyncMock(side_effect=RuntimeError("redis down"))
        assert await is_feature_enabled(10001, "video_parse") is True

    @pytest.mark.asyncio
    async def test_write_failure_replies_error(self, fake_redis):
        """Redis 写入失败时管理员收到错误提示，开关保持不变。"""
        bot = _make_bot()
        event = _make_event()
        fake_redis.hset = AsyncMock(side_effect=RuntimeError("redis down"))

        await handle_group_manage(bot, event, ["关", "视频解析"])

        assert await is_feature_enabled(10001, "video_parse") is True
        event.reply.assert_called_once()
        assert "失败" in event.reply.call_args[0][0]


class TestCommandRegistered:
    def test_group_manage_command_registered(self):
        """/群管 指令已注册到 QQ 平台。"""
        cmds = matcher.message_handler.platform_commands.get("qq", {})
        assert "群管" in cmds
        assert cmds["群管"]["func"].__module__ == "neobot.plugins.group_manage"

    @pytest.mark.asyncio
    async def test_unknown_feature_rejected(self, fake_redis):
        bot = _make_bot()
        event = _make_event()
        await handle_group_manage(bot, event, ["关", "不存在的功能"])
        assert await is_feature_enabled(10001, "不存在的功能") is True
        event.reply.assert_called_once()
        assert "没有这个功能" in event.reply.call_args[0][0]
