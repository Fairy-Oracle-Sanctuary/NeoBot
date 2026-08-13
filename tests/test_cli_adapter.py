# -*- coding: utf-8 -*-
"""CLI Adapter & MockBot 基础单元测试"""
import pytest

from neobot.adapters.cli_adapter import MockBot, CLIDebugger
from neobot.models.events.message import GroupMessageEvent, PrivateMessageEvent
from neobot.models.message import MessageSegment


class TestMockBot:
    """MockBot 基础功能测试"""

    def test_instantiate(self):
        bot = MockBot()
        assert bot.self_id == 999999
        assert bot.nickname == "CLI-Bot"

    def test_process_message_text(self):
        bot = MockBot()
        result = bot._process_message("hello")
        assert result == "hello"

    def test_process_message_none(self):
        bot = MockBot()
        result = bot._process_message(None)
        assert result == ""

    def test_process_message_segment(self):
        bot = MockBot()
        seg = MessageSegment.text("hi")
        result = bot._process_message(seg)
        assert result == {"type": "text", "data": {"text": "hi"}}

    def test_process_message_list(self):
        bot = MockBot()
        segs = [MessageSegment.text("a"), MessageSegment.text("b")]
        result = bot._process_message(segs)
        assert isinstance(result, list)
        assert len(result) == 2

    def test_build_forward_node(self):
        bot = MockBot()
        node = bot.build_forward_node(123, "test_user", "hello")
        assert node["type"] == "node"
        assert node["data"]["uin"] == 123
        assert node["data"]["name"] == "test_user"
        assert node["data"]["content"] == "hello"

    @pytest.mark.asyncio
    async def test_call_api_group_msg(self):
        bot = MockBot()
        result = await bot.call_api("send_group_msg", {
            "group_id": 10000,
            "message": "测试消息"
        })
        assert "message_id" in result

    @pytest.mark.asyncio
    async def test_call_api_private_msg(self):
        bot = MockBot()
        result = await bot.call_api("send_private_msg", {
            "user_id": 10001,
            "message": "私聊测试"
        })
        assert "message_id" in result

    @pytest.mark.asyncio
    async def test_call_api_forward_msg(self):
        bot = MockBot()
        node = bot.build_forward_node(123, "test", "hi")
        result = await bot.call_api("send_group_forward_msg", {
            "group_id": 10000,
            "messages": [node]
        })
        assert "message_id" in result

    def test_msg_id_increment(self):
        bot = MockBot()
        ids = [bot._next_msg_id() for _ in range(5)]
        assert ids == [1, 2, 3, 4, 5]

    @pytest.mark.asyncio
    async def test_display_does_not_raise(self):
        """_display 不应抛异常"""
        bot = MockBot()
        # 不应抛任何异常
        await bot._display("send_group_msg", {
            "group_id": 10000,
            "message": "hello"
        })


class TestCLIDebugger:
    """CLIDebugger 基础功能测试"""

    def test_default_state(self):
        d = CLIDebugger()
        assert d.mode == "group"
        assert d.group_id == 10000
        assert d.user_id == 10001
        assert d.bot is not None
        assert isinstance(d.bot, MockBot)

    def test_make_event_group(self):
        d = CLIDebugger()
        event = d._make_event("/help")
        assert isinstance(event, GroupMessageEvent)
        assert event.raw_message == "/help"
        assert event.group_id == 10000
        assert event.user_id == 10001
        assert event.bot is d.bot
        # 验证 message 段
        assert len(event.message) == 1
        assert event.message[0].type == "text"
        assert event.message[0].data["text"] == "/help"

    def test_make_event_private(self):
        d = CLIDebugger()
        d.mode = "private"
        event = d._make_event("hello")
        assert isinstance(event, PrivateMessageEvent)
        assert event.raw_message == "hello"
        assert event.user_id == 10001

    def test_make_event_empty_text(self):
        d = CLIDebugger()
        event = d._make_event("")
        assert event.raw_message == ""

    def test_msg_id_increment(self):
        d = CLIDebugger()
        ids = [d._next_msg_id() for _ in range(3)]
        assert ids == [20000, 20001, 20002]
