# -*- coding: utf-8 -*-
"""parse_stats 解析耗时统计模块测试。"""
import time

import pytest

from neobot.plugins.web_parser import parse_stats as ps


@pytest.fixture(autouse=True)
def _reset_state():
    """每个测试前重置内部状态。"""
    ps._alert_cooldowns.clear()
    ps._mem_samples.clear()
    ps._mem_mode = False
    yield


class FakeRedis:
    """最小 Redis 假对象（LPUSH/LTRIM/LRANGE）。"""

    def __init__(self):
        self.lists = {}

    async def lpush(self, key, value):
        self.lists.setdefault(key, []).insert(0, str(value))

    async def ltrim(self, key, start, stop):
        items = self.lists.get(key, [])
        self.lists[key] = items[start:stop + 1]

    async def lrange(self, key, start, stop):
        return self.lists.get(key, [])[start:stop + 1]


async def _noop(parser: str, cost_ms: int) -> None:
    """测试辅助：跳过 Redis 写入。"""


async def _fake_avg(parser: str) -> float:
    """测试辅助：固定返回均值。"""
    return 1200.0


@pytest.mark.asyncio
async def test_record_and_average(monkeypatch):
    """记录耗时后可计算平均值。"""
    fake = FakeRedis()
    # redis_manager.redis 是 property，直接替换实例属性
    monkeypatch.setattr(type(ps.redis_manager), "redis", property(lambda self: fake))

    await ps.record_parse("bili", 500)
    await ps.record_parse("bili", 700)
    await ps.record_parse("bili", 900)

    avg = await ps.average_parse("bili")
    assert avg is not None
    assert abs(avg - 700.0) < 0.01


@pytest.mark.asyncio
async def test_average_none_when_no_samples():
    """无样本时返回 None。"""
    assert await ps.average_parse("xhs") is None


@pytest.mark.asyncio
async def test_slow_alert_triggers_once_per_cooldown(monkeypatch):
    """超过 1s 触发告警，冷却期内不重复发送。"""
    sent = []

    class FakeBot:
        async def send_private_msg(self, user_id, message):
            sent.append((user_id, message))

    class FakeBotManager:
        def get_all_bots(self):
            return [FakeBot()]

    # _alert_slow 内部 from neobot.plugin_api import bot_manager，patch 导入源
    import neobot.plugin_api as plugin_api_mod
    monkeypatch.setattr(plugin_api_mod, "bot_manager", FakeBotManager())
    # 完全隔离：mock 掉 Redis 写入与平均查询，只测告警逻辑
    monkeypatch.setattr(ps, "_record_redis", _noop)
    monkeypatch.setattr(ps, "average_parse", _fake_avg)

    # 第一次慢解析 → 告警
    await ps.record_parse("douyin", 1500)
    assert len(sent) == 1
    assert sent[0][0] == ps.ADMIN_QQ
    assert "douyin" in sent[0][1]
    assert "1500ms" in sent[0][1]

    # 冷却期内再慢 → 不告警
    await ps.record_parse("douyin", 1800)
    assert len(sent) == 1

    # 冷却期过后 → 再告警
    ps._alert_cooldowns["douyin"] = time.monotonic() - ps.ALERT_COOLDOWN_SECONDS - 1
    await ps.record_parse("douyin", 2000)
    assert len(sent) == 2


@pytest.mark.asyncio
async def test_fast_parse_no_alert(monkeypatch):
    """低于阈值不告警。"""
    sent = []

    class FakeBot:
        async def send_private_msg(self, user_id, message):
            sent.append(message)

    class FakeBotManager:
        def get_all_bots(self):
            return [FakeBot()]

    import neobot.plugin_api as plugin_api_mod
    monkeypatch.setattr(plugin_api_mod, "bot_manager", FakeBotManager())
    monkeypatch.setattr(ps, "_record_redis", _noop)
    monkeypatch.setattr(ps, "average_parse", _fake_avg)

    await ps.record_parse("xhs", 300)
    assert sent == []


def test_fmt_cost():
    """耗时格式化。"""
    assert ps.fmt_cost(500) == "500ms"
    assert ps.fmt_cost(1500) == "1.5s"
    assert ps.fmt_cost(999) == "999ms"
