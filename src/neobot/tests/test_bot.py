import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from neobot.models.message import MessageSegment
from neobot.models.objects import GroupInfo, StrangerInfo
from neobot.core.bot import Bot


class TestBot:
    def test_bot_initialization(self):
        """测试 Bot 类初始化。"""
        mock_ws = MagicMock()
        mock_ws.self_id = 123456
        bot = Bot(mock_ws)
        assert bot.self_id == 123456
        assert bot.code_executor is None

    def test_build_forward_node(self):
        """测试构建合并转发消息节点。"""
        mock_ws = MagicMock()
        bot = Bot(mock_ws)
        node = bot.build_forward_node(123456, "TestUser", "Hello World")
        assert node["type"] == "node"
        assert node["data"]["uin"] == 123456
        assert node["data"]["name"] == "TestUser"
        assert node["data"]["content"] == "Hello World"

    def test_build_forward_node_with_segment(self):
        """测试使用消息段构建合并转发消息节点。"""
        mock_ws = MagicMock()
        bot = Bot(mock_ws)
        segment = MessageSegment.text("Hello")
        node = bot.build_forward_node(123456, "TestUser", segment)
        assert node["type"] == "node"
        assert node["data"]["content"][0]["type"] == segment.type
        assert node["data"]["content"][0]["data"] == segment.data

    def test_build_forward_node_with_segment_list(self):
        """测试使用消息段列表构建合并转发消息节点。"""
        mock_ws = MagicMock()
        bot = Bot(mock_ws)
        segments = [MessageSegment.text("Hello"), MessageSegment.at(123456)]
        node = bot.build_forward_node(123456, "TestUser", segments)
        assert node["type"] == "node"
        assert len(node["data"]["content"]) == 2
        assert node["data"]["content"][0]["type"] == segments[0].type
        assert node["data"]["content"][0]["data"] == segments[0].data
        assert node["data"]["content"][1]["type"] == segments[1].type
        assert node["data"]["content"][1]["data"] == segments[1].data

    @pytest.mark.asyncio
    async def test_send_forwarded_messages_group(self):
        """测试发送群聊合并转发消息。"""
        mock_ws = MagicMock()
        bot = Bot(mock_ws)
        bot.send_group_forward_msg = AsyncMock()
        nodes = [bot.build_forward_node(123456, "TestUser", "Hello")]
        await bot.send_forwarded_messages(111111, nodes)
        bot.send_group_forward_msg.assert_called_once_with(111111, nodes)

    @pytest.mark.asyncio
    async def test_send_forwarded_messages_private(self):
        """测试发送私聊合并转发消息。"""
        mock_ws = AsyncMock()
        bot = Bot(mock_ws)
        bot.send_private_forward_msg = AsyncMock()
        nodes = [bot.build_forward_node(123456, "TestUser", "Hello")]
        from neobot.models.events.base import OneBotEvent
        mock_event = MagicMock(spec=OneBotEvent)
        mock_event.group_id = None
        mock_event.user_id = 222222
        await bot.send_forwarded_messages(mock_event, nodes)
        bot.send_private_forward_msg.assert_called_once_with(222222, nodes)

    @pytest.mark.asyncio
    async def test_send_forwarded_messages_group_event(self):
        """测试通过群聊事件发送合并转发消息。"""
        mock_ws = AsyncMock()
        bot = Bot(mock_ws)
        bot.send_group_forward_msg = AsyncMock()
        nodes = [bot.build_forward_node(123456, "TestUser", "Hello")]
        from neobot.models.events.base import OneBotEvent
        mock_event = MagicMock(spec=OneBotEvent)
        mock_event.group_id = 111111
        mock_event.user_id = 222222
        await bot.send_forwarded_messages(mock_event, nodes)
        bot.send_group_forward_msg.assert_called_once_with(111111, nodes)

    @pytest.mark.asyncio
    async def test_send_forwarded_messages_invalid_target(self):
        """测试发送合并转发消息到无效目标。"""
        mock_ws = AsyncMock()
        bot = Bot(mock_ws)
        nodes = [bot.build_forward_node(123456, "TestUser", "Hello")]
        from neobot.models.events.base import OneBotEvent
        mock_event = MagicMock(spec=OneBotEvent)
        mock_event.group_id = None
        mock_event.user_id = None
        with pytest.raises(ValueError, match="Event has neither group_id nor user_id"):
            await bot.send_forwarded_messages(mock_event, nodes)

    @pytest.mark.asyncio
    async def test_get_group_list(self):
        """测试获取群列表。"""
        mock_ws = MagicMock()
        bot = Bot(mock_ws)
        # 测试返回字典列表的情况
        super_get_group_list = AsyncMock(return_value=[{"group_id": 123456, "group_name": "Test Group"}])
        with patch.object(bot.__class__.__bases__[1], 'get_group_list', super_get_group_list):
            groups = await bot.get_group_list(no_cache=True)
            assert len(groups) == 1
            assert groups[0].group_id == 123456
            assert groups[0].group_name == "Test Group"
            assert isinstance(groups[0], GroupInfo)

    @pytest.mark.asyncio
    async def test_get_stranger_info(self):
        """测试获取陌生人信息。"""
        mock_ws = MagicMock()
        bot = Bot(mock_ws)
        # 测试返回字典的情况
        super_get_stranger_info = AsyncMock(return_value={"user_id": 123456, "nickname": "TestUser", "sex": "male", "age": 18})
        with patch.object(bot.__class__.__bases__[2], 'get_stranger_info', super_get_stranger_info):
            info = await bot.get_stranger_info(123456, no_cache=True)
            assert info.user_id == 123456
            assert info.nickname == "TestUser"
            assert info.sex == "male"
            assert info.age == 18
            assert isinstance(info, StrangerInfo)