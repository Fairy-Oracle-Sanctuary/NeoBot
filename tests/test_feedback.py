# -*- coding: utf-8 -*-
"""feedback 插件测试：群限制 + 反馈转发 + 空内容处理。"""
from typing import cast

import pytest

from neobot.plugins import feedback as fb
from neobot.plugin_api import Bot, MessageEvent


class FakeBot:
    def __init__(self):
        self.sent = []

    async def send_private_msg(self, user_id, message):
        self.sent.append((user_id, message))


class FakeEvent:
    """模拟群消息事件（仅含插件用到的字段）。"""

    def __init__(self, group_id=None, user_id="12345", sender=None, reply=None):
        self.group_id = group_id
        self.user_id = user_id
        self.sender = sender or {"card": "测试员", "nickname": "测试员"}
        self._reply = reply or []

    async def reply(self, msg):
        self._reply.append(msg)


@pytest.mark.asyncio
async def test_feedback_only_in_allowed_group():
    """非官群使用 /反馈 被拒绝。"""
    bot = FakeBot()
    ev = FakeEvent(group_id=999999, reply=[])
    await fb.handle_feedback(cast(Bot, bot), cast(MessageEvent, ev), ["测试", "内容"])
    assert "仅" in ev._reply[0]
    assert bot.sent == []  # 未转发


@pytest.mark.asyncio
async def test_feedback_forwards_to_admin():
    """官群反馈转发给管理员 + 回复确认。"""
    bot = FakeBot()
    ev = FakeEvent(group_id=fb.ALLOWED_GROUP_ID, user_id="88888", reply=[])
    await fb.handle_feedback(cast(Bot, bot), cast(MessageEvent, ev), ["抖音", "解析", "失败"])
    assert bot.sent, "应转发给管理员"
    admin_id, message = bot.sent[0]
    assert admin_id == fb.ADMIN_QQ
    assert "抖音 解析 失败" in message
    assert "88888" in message
    assert "收到" in ev._reply[0]


@pytest.mark.asyncio
async def test_feedback_empty_args():
    """无内容时提示格式。"""
    bot = FakeBot()
    ev = FakeEvent(group_id=fb.ALLOWED_GROUP_ID, reply=[])
    await fb.handle_feedback(cast(Bot, bot), cast(MessageEvent, ev), [])
    assert "格式" in ev._reply[0]
    assert bot.sent == []


@pytest.mark.asyncio
async def test_feedback_too_short():
    """内容太短被拒绝。"""
    bot = FakeBot()
    ev = FakeEvent(group_id=fb.ALLOWED_GROUP_ID, reply=[])
    await fb.handle_feedback(cast(Bot, bot), cast(MessageEvent, ev), ["a"])
    assert "太短" in ev._reply[0]
    assert bot.sent == []
