"""每日早报：只发指定群，来源用假的 RSS，不访问网络。"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from neobot.core.handlers.unknown_command import DEFAULT_IGNORE, suggest_command
from neobot.plugins import group_manage

PLACEHOLDER_GROUP = 900000111
OTHER_GROUP = 900000222

NOW = datetime(2026, 11, 13, 0, 2, tzinfo=timezone.utc)  # 上海 08:02，周五

WORLD_XML = """<?xml version="1.0" encoding="utf-8"?>
<rss version="2.0"><channel>
<item>
  <title>甲地签署新协定</title>
  <link>https://example.com/world/a</link>
  <description>&lt;p&gt;双方确认了合作文本，并约定下月磋商。&lt;/p&gt;</description>
  <pubDate>Fri, 13 Nov 2026 07:40:00 +0800</pubDate>
</item>
<item>
  <title>甲地签署了新协定</title>
  <link>https://example.com/world/a-dup</link>
  <description>这是重复标题</description>
  <pubDate>Fri, 13 Nov 2026 07:10:00 +0800</pubDate>
</item>
<item>
  <title>很旧的国际新闻</title>
  <link>https://example.com/world/old</link>
  <description>不该出现</description>
  <pubDate>Mon, 01 Jan 2024 00:00:00 +0800</pubDate>
</item>
</channel></rss>
"""

DOMESTIC_XML = """<?xml version="1.0" encoding="utf-8"?>
<rss version="2.0"><channel>
<item>
  <title>某市开通新线路</title>
  <link>https://example.com/cn/b</link>
  <description>首班车于清晨发出，沿线增设两座车站。</description>
  <pubDate>Fri, 13 Nov 2026 07:50:00 +0800</pubDate>
</item>
</channel></rss>
"""

ATOM_XML = """<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <title>港口恢复通航</title>
    <link href="https://example.com/atom/c"/>
    <summary>港务部门称主航道已经重新开放。</summary>
    <updated>2026-11-13T07:20:00+08:00</updated>
  </entry>
</feed>
"""


class FakeRedis:
    def __init__(self):
        self.data: dict[str, str] = {}

    async def get(self, key):
        return self.data.get(key)

    async def set(self, key, value, ex=None, nx=False):
        if nx and key in self.data:
            return None
        self.data[key] = str(value)
        return True

    async def delete(self, key):
        self.data.pop(key, None)
        return 1


def _section(**overrides):
    from neobot.core.config_models import DailyNewsModel, DailyNewsSourceModel

    payload = dict(
        enabled=True,
        groups=[PLACEHOLDER_GROUP],
        time="08:00",
        timezone="Asia/Shanghai",
        max_items_international=8,
        max_items_domestic=6,
        request_timeout=12,
        send_as_forward=True,
        sources=[
            DailyNewsSourceModel(name="示例国际", url="https://example.com/world.xml", category="international"),
            DailyNewsSourceModel(name="示例国内", url="https://example.com/cn.xml", category="domestic"),
        ],
    )
    payload.update(overrides)
    return DailyNewsModel(**payload)


def _settings(**overrides):
    from neobot.plugins.daily_news import load_settings

    return load_settings(_section(**overrides))


def _feeds(world=WORLD_XML, domestic=DOMESTIC_XML):
    async def fetch(url, timeout):
        assert timeout == 12
        if url.endswith("world.xml"):
            return world
        if url.endswith("cn.xml"):
            return domestic
        if url.endswith("atom.xml"):
            return ATOM_XML
        raise RuntimeError(f"down:{url}")

    return fetch


@pytest.fixture(autouse=True)
def _clean_runtime():
    from neobot.plugins import daily_news

    daily_news.reset_runtime_state()
    yield
    daily_news.reset_runtime_state()


def test_config_defaults_and_example_have_no_real_group_id():
    from neobot.core.config_models import DailyNewsModel

    model = DailyNewsModel()
    assert model.enabled is False
    assert model.groups == []
    assert model.time == "08:00"
    assert model.timezone == "Asia/Shanghai"
    assert model.max_items_international == 8
    assert model.max_items_domestic == 6
    assert model.send_as_forward is True
    assert model.request_timeout == 12

    example = Path("config.example.toml").read_text(encoding="utf-8")
    assert "[daily_news]" in example
    assert "groups = []" in example
    assert "900000111" not in example
    assert "chinanews.com.cn/rss/world.xml" in example
    assert 'unknown_command_ignore = ["今日猪猪", "我的猪圈"]' in example

    import tomllib

    parsed = DailyNewsModel(**tomllib.loads(example)["daily_news"])
    assert parsed.enabled is False
    assert parsed.groups == []
    assert parsed.sources[0].url.endswith("/world.xml")
    assert parsed.sources[0].category == "international"


def test_default_sources_are_chinanews_categories():
    from neobot.plugins.daily_news import DEFAULT_SOURCES, load_settings
    from neobot.core.config_models import DailyNewsModel

    settings = load_settings(DailyNewsModel(enabled=True, groups=[PLACEHOLDER_GROUP]))
    urls = [source.url for source in settings.sources]
    assert urls == [source.url for source in DEFAULT_SOURCES]
    categories = {source.category for source in settings.sources}
    assert categories == {"international", "domestic"}
    assert all("chinanews.com.cn/rss/" in url for url in urls)
    assert any(url.endswith("/world.xml") for url in urls)
    assert any(url.endswith("/china.xml") for url in urls)


def test_parse_strips_html_and_drops_stale_duplicates():
    from neobot.plugins.daily_news import assemble_digest

    settings = _settings()
    text = assemble_digest(
        settings,
        [
            (settings.sources[0], WORLD_XML),
            (settings.sources[1], DOMESTIC_XML),
        ],
        NOW,
    )
    assert text is not None
    assert "📰 卡尔戈洛早报 · 2026-11-13 周五" in text
    assert "国际快讯" in text
    assert "时事新闻" in text
    assert "甲地签署新协定" in text
    assert "甲地签署了新协定" not in text
    assert "很旧的国际新闻" not in text
    assert "某市开通新线路" in text
    assert "双方确认了合作文本，并约定下月磋商。" in text
    assert "<p>" not in text
    assert "&lt;" not in text
    assert "https://example.com/world/a" in text
    assert "示例国际" in text
    assert text.strip().endswith("今天先看到这里，慢慢看就好。")
    assert "不该出现" not in text


def test_atom_and_length_cap_and_empty_means_skip():
    from neobot.plugins.daily_news import NewsSource, assemble_digest

    settings = _settings(
        max_items_international=8,
        sources=[],
    )
    # 空 sources 会落到内置来源；这里显式传入解析结果。
    source = NewsSource("原子源", "https://example.com/atom.xml", "international")
    text = assemble_digest(settings, [(source, ATOM_XML)], NOW, limit=1800)
    assert text is not None
    assert "港口恢复通航" in text
    assert "港务部门称主航道已经重新开放。" in text
    assert "https://example.com/atom/c" in text

    xml_parts = ["<?xml version='1.0'?><rss version='2.0'><channel>"]
    for index in range(6):
        title = f"长标题{index}" + "新闻" * 30
        xml_parts.append(
            "<item>"
            f"<title>{title}</title>"
            f"<link>https://example.com/long/{index}</link>"
            f"<description>{'摘要' * 40}</description>"
            "<pubDate>Fri, 13 Nov 2026 07:00:00 +0800</pubDate>"
            "</item>"
        )
    xml_parts.append("</channel></rss>")
    capped = assemble_digest(
        _settings(max_items_international=6, max_items_domestic=6),
        [(NewsSource("长", "https://example.com/long.xml", "international"), "".join(xml_parts))],
        NOW,
        limit=360,
    )
    assert capped is not None
    assert len(capped) <= 360
    assert "📰 卡尔戈洛早报 · 2026-11-13 周五" in capped
    assert capped.count("长标题") < 6

    assert assemble_digest(settings, [(source, RuntimeError("down"))], NOW) is None
    assert assemble_digest(settings, [(source, "<rss></rss>")], NOW) is None


async def test_schedule_window_uses_shanghai_and_skips_second_send():
    from neobot.plugins.daily_news import in_send_window, scheduled_push

    settings = _settings()
    assert in_send_window(NOW, settings) is True
    assert in_send_window(datetime(2026, 11, 12, 23, 59, tzinfo=timezone.utc), settings) is False
    assert in_send_window(datetime(2026, 11, 13, 0, 10, tzinfo=timezone.utc), settings) is False

    redis = FakeRedis()
    sent: list[int] = []

    async def sender(group_id, text, _settings):
        sent.append(group_id)
        assert "甲地签署新协定" in text
        return True

    async def enabled(_group_id):
        return True

    first = await scheduled_push(
        now=NOW,
        fetch=_feeds(),
        sender=sender,
        settings=settings,
        client=redis,
        feature_enabled=enabled,
    )
    second = await scheduled_push(
        now=NOW,
        fetch=_feeds(),
        sender=sender,
        settings=settings,
        client=redis,
        feature_enabled=enabled,
    )
    assert first == 1
    assert second == 0
    assert sent == [PLACEHOLDER_GROUP]

    outside = await scheduled_push(
        now=datetime(2026, 11, 13, 2, 0, tzinfo=timezone.utc),
        fetch=_feeds(),
        sender=sender,
        settings=settings,
        client=FakeRedis(),
        feature_enabled=enabled,
    )
    assert outside == 0
    assert sent == [PLACEHOLDER_GROUP]


@pytest.mark.asyncio
async def test_memory_ledger_and_all_sources_down_do_not_error():
    from neobot.plugins import daily_news

    settings = _settings(groups=[PLACEHOLDER_GROUP, OTHER_GROUP])
    sent: list[int] = []

    async def sender(group_id, text, _settings):
        sent.append(group_id)
        return True

    async def enabled(group_id):
        return group_id == PLACEHOLDER_GROUP

    async def boom(url, timeout):
        raise RuntimeError("network")

    warned = []
    errors = []
    original_warning = daily_news.logger.warning
    original_error = daily_news.logger.error
    daily_news.logger.warning = lambda message: warned.append(message)
    daily_news.logger.error = lambda message: errors.append(message)
    try:
        skipped = await daily_news.scheduled_push(
            now=NOW,
            fetch=boom,
            sender=sender,
            settings=settings,
            client=None,
            feature_enabled=enabled,
        )
        again = await daily_news.scheduled_push(
            now=NOW,
            fetch=boom,
            sender=sender,
            settings=settings,
            client=None,
            feature_enabled=enabled,
        )
    finally:
        daily_news.logger.warning = original_warning
        daily_news.logger.error = original_error

    assert skipped == 0 and again == 0
    assert sent == []
    assert len(warned) == 1
    assert errors == []

    async def fetch(url, timeout):
        return WORLD_XML if "world" in url else DOMESTIC_XML

    first = await daily_news.scheduled_push(
        now=NOW,
        fetch=fetch,
        sender=sender,
        settings=settings,
        client=None,
        feature_enabled=enabled,
    )
    second = await daily_news.scheduled_push(
        now=NOW,
        fetch=fetch,
        sender=sender,
        settings=settings,
        client=None,
        feature_enabled=enabled,
    )
    assert first == 1
    assert second == 0
    assert sent == [PLACEHOLDER_GROUP]


@pytest.mark.asyncio
async def test_forward_falls_back_to_text_and_manual_rules():
    from neobot.plugins.daily_news import deliver, manual_push

    settings = _settings()
    bot = MagicMock()
    bot.self_id = 10000
    bot.build_forward_node = MagicMock(side_effect=lambda user_id, nickname, message: {
        "type": "node",
        "data": {"uin": user_id, "name": nickname, "content": message},
    })
    bot.send_group_forward_msg = AsyncMock(side_effect=RuntimeError("retcode 1200"))
    bot.send_group_msg = AsyncMock()

    mode = await deliver(bot, PLACEHOLDER_GROUP, "📰 早报正文", settings)
    assert mode == "text"
    bot.send_group_msg.assert_awaited_once()
    assert bot.send_group_msg.await_args.args[0] == PLACEHOLDER_GROUP

    bot.send_group_forward_msg = AsyncMock()
    mode = await deliver(bot, PLACEHOLDER_GROUP, "📰 早报正文\n\n国际快讯\n1. 甲", settings)
    assert mode == "forward"
    nodes = bot.send_group_forward_msg.await_args.args[1]
    assert nodes[0]["data"]["name"] == "卡尔戈洛"
    assert "早报正文" in nodes[0]["data"]["content"]

    event = MagicMock()
    event.group_id = OTHER_GROUP
    event.user_id = 42
    event.reply = AsyncMock()
    await manual_push(bot, event, now=NOW, fetch=_feeds(), settings=settings, client=FakeRedis())
    event.reply.assert_not_called()
    bot.send_group_msg.reset_mock()
    bot.send_group_forward_msg.reset_mock()

    event.group_id = None
    await manual_push(bot, event, now=NOW, fetch=_feeds(), settings=settings, client=FakeRedis())
    event.reply.assert_not_called()

    event.group_id = PLACEHOLDER_GROUP
    off = _settings(enabled=False)
    await manual_push(bot, event, now=NOW, fetch=_feeds(), settings=off, client=FakeRedis())
    event.reply.assert_not_called()

    async def disabled(_group_id):
        return False

    await manual_push(
        bot,
        event,
        now=NOW,
        fetch=_feeds(),
        settings=settings,
        client=FakeRedis(),
        feature_enabled=disabled,
    )
    assert "群管" in event.reply.await_args.args[0]
    event.reply.reset_mock()

    redis = FakeRedis()
    calls = {"n": 0}

    async def fetch(url, timeout):
        calls["n"] += 1
        return WORLD_XML if url.endswith("world.xml") else DOMESTIC_XML

    bot.send_group_forward_msg = AsyncMock(side_effect=RuntimeError("forward down"))
    await manual_push(
        bot,
        event,
        now=NOW,
        fetch=fetch,
        settings=settings,
        client=redis,
        feature_enabled=_ok,
    )
    assert calls["n"] >= 1
    assert bot.send_group_msg.await_count == 1
    body = bot.send_group_msg.await_args.args[1]
    assert "甲地签署新协定" in body
    assert "<p>" not in body

    event.reply.reset_mock()
    before = calls["n"]
    await manual_push(
        bot,
        event,
        now=NOW,
        fetch=fetch,
        settings=settings,
        client=redis,
        feature_enabled=_ok,
    )
    assert calls["n"] == before
    assert "分钟" in event.reply.await_args.args[0]


async def _ok(_group_id):
    return True


def test_near_duplicate_titles_collapse_across_sections():
    """同一件事换了标点和语序，也不该在早报里出现两次。"""
    from neobot.plugins.daily_news import assemble_digest, titles_similar

    left = "7人死亡！纽约一栋建筑倒塌"
    right = "纽约建筑倒塌已致7人死亡"
    assert titles_similar(left, right)
    assert titles_similar("纽约：高层建筑　倒塌！！", "纽约高层建筑倒塌")
    assert not titles_similar("北京今日发布大风预警", "上海今日发布大风预警")
    assert not titles_similar("中美举行经贸会谈", "欧洲多国遭遇强降雨")

    world = """<?xml version="1.0" encoding="utf-8"?>
<rss><channel><item>
  <title>7人死亡！纽约一栋建筑倒塌</title>
  <link>https://example.com/world/nyc</link>
  <description>救援仍在进行。</description>
  <pubDate>Fri, 13 Nov 2026 07:40:00 +0800</pubDate>
</item></channel></rss>"""
    domestic = """<?xml version="1.0" encoding="utf-8"?>
<rss><channel><item>
  <title>纽约建筑倒塌已致7人死亡</title>
  <link>https://example.com/cn/nyc</link>
  <description>现场已封锁。</description>
  <pubDate>Fri, 13 Nov 2026 07:48:00 +0800</pubDate>
</item></channel></rss>"""
    settings = _settings()
    text = assemble_digest(
        settings,
        [
            (settings.sources[0], world),
            (settings.sources[1], domestic),
        ],
        NOW,
    )
    assert text is not None
    assert text.count("纽约") == 1
    assert "建筑倒塌" in text


@pytest.mark.asyncio
async def test_group_switch_disables_daily_news_feature():
    """/群管 关 早报 之后，定时和手动都不该再发。"""
    from neobot.plugins import daily_news, group_manage

    settings = _settings()
    sent: list[int] = []

    async def sender(group_id, text, _settings):
        sent.append(group_id)
        return True

    store = {(group_manage._settings_key(PLACEHOLDER_GROUP), "daily_news"): "0"}

    class _Hash:
        async def hget(self, key, field):
            return store.get((key, field))

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(group_manage.redis_manager, "_redis", _Hash())
    try:
        count = await daily_news.scheduled_push(
            now=NOW,
            fetch=_feeds(),
            sender=sender,
            settings=settings,
            client=FakeRedis(),
        )
        assert count == 0
        assert sent == []

        event = MagicMock()
        event.group_id = PLACEHOLDER_GROUP
        event.reply = AsyncMock()
        bot = MagicMock()
        bot.send_group_msg = AsyncMock()
        bot.send_group_forward_msg = AsyncMock()
        bot.self_id = 10000
        await daily_news.manual_push(
            bot,
            event,
            now=NOW,
            fetch=_feeds(),
            settings=settings,
            client=FakeRedis(),
        )
    finally:
        monkeypatch.undo()

    assert event.reply.await_args is not None
    assert "关掉" in event.reply.await_args.args[0]
    bot.send_group_msg.assert_not_called()
    bot.send_group_forward_msg.assert_not_called()


def test_command_is_in_fuzzy_vocabulary_and_pig_commands_stay_ignored():
    from neobot.core.managers.command_manager import matcher
    from neobot.plugins import daily_news

    assert "今日猪猪" in DEFAULT_IGNORE
    assert "我的猪圈" in DEFAULT_IGNORE
    assert "早报" not in DEFAULT_IGNORE
    assert suggest_command("今日猪猪", ["早报", "今日运势"]) is None
    assert suggest_command("我的猪圈", ["早报", "今日运势"]) is None
    assert suggest_command("早报呀", ["早报", "今日运势"]) == "早报"

    commands = matcher.message_handler.platform_commands.get("qq", {})
    assert "早报" in commands
    assert "早报" in daily_news.plugin_manifest.usage
    assert daily_news.plugin_manifest.name == "daily_news"
    assert group_manage.FEATURES.get("daily_news") == "早报"
    assert group_manage.FEATURE_ALIASES.get("早报") == "daily_news"


@pytest.mark.asyncio
async def test_group_admin_can_disable_digest():
    store = {}

    async def fake_hget(key, field):
        return store.get((key, field))

    async def fake_hset(key, field, value):
        store[(key, field)] = value

    fake = MagicMock()
    fake.hget = fake_hget
    fake.hset = fake_hset

    bot = AsyncMock()
    member = MagicMock()
    member.role = "owner"
    bot.get_group_member_info = AsyncMock(return_value=member)
    event = MagicMock()
    event.group_id = PLACEHOLDER_GROUP
    event.user_id = 42
    event.reply = AsyncMock()

    from unittest.mock import patch

    with patch.object(group_manage.redis_manager, "_redis", fake):
        await group_manage.handle_group_manage(bot, event, ["关", "早报"])
        assert await group_manage.is_feature_enabled(PLACEHOLDER_GROUP, "daily_news") is False
        await group_manage.handle_group_manage(bot, event, ["开", "早报"])
        assert await group_manage.is_feature_enabled(PLACEHOLDER_GROUP, "daily_news") is True
