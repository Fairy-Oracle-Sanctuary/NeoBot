# -*- coding: utf-8 -*-
"""推特解析插件的单元测试。"""
import asyncio

from neobot.plugins import twitter_parser as tp


def test_extract_status_id():
    assert tp.STATUS_URL_RE.search("https://twitter.com/user/status/123456789").group(1) == "123456789"
    assert tp.STATUS_URL_RE.search("https://x.com/abc_123/status/987654321?s=20").group(1) == "987654321"
    assert tp.STATUS_URL_RE.search("看这个 https://x.com/i/status/555666777 很精彩").group(1) == "555666777"
    assert tp.STATUS_URL_RE.search("https://example.com/twitter.com/status/1") is None
    assert tp.TCO_URL_RE.search("https://t.co/AbC123") is not None


def test_fmt_num():
    assert tp._fmt_num(999) == "999"
    assert tp._fmt_num(123456) == "12.3万"
    assert tp._fmt_num(None) == "None"


def test_format_created_at():
    assert tp._format_created_at("Tue Feb 15 21:21:13 +0000 2022") == "2022-02-15 21:21"
    assert tp._format_created_at("") == ""
    assert tp._format_created_at("not a date") == "not a date"


def test_build_tweet_card():
    tweet = {
        "text": "你好，世界",
        "author": {"name": "测试", "screen_name": "tester"},
        "likes": 12345,
        "retweets": 6,
        "replies": 0,
        "views": 99999,
        "created_at": "Tue Feb 15 21:21:13 +0000 2022",
        "url": "https://x.com/tester/status/1",
    }
    card = tp._build_tweet_card(tweet)
    assert "测试 @tester" in card
    assert "你好，世界" in card
    assert "1.2万" in card
    assert "2022-02-15 21:21" in card


def test_collect_media():
    tweet = {
        "media": {
            "all": [
                {"type": "photo", "url": "https://pbs.twimg.com/media/a.jpg"},
                {"type": "photo", "url": "https://pbs.twimg.com/media/b.jpg"},
                {"type": "video", "url": "https://video.twimg.com/v.mp4"},
                {"type": "gif", "url": "https://video.twimg.com/g.mp4"},
            ]
        }
    }
    photos, videos = tp._collect_media(tweet)
    assert photos == [
        "https://pbs.twimg.com/media/a.jpg",
        "https://pbs.twimg.com/media/b.jpg",
    ]
    assert videos == [
        "https://video.twimg.com/v.mp4",
        "https://video.twimg.com/g.mp4",
    ]


def test_collect_media_fallback_arrays():
    tweet = {
        "media": {
            "photos": [{"url": "https://pbs.twimg.com/media/c.jpg"}],
            "videos": [{"url": "https://video.twimg.com/x.mp4"}],
        }
    }
    photos, videos = tp._collect_media(tweet)
    assert photos == ["https://pbs.twimg.com/media/c.jpg"]
    assert videos == ["https://video.twimg.com/x.mp4"]


def test_default_disabled_and_memory_toggle():
    async def scenario():
        tp._enabled_map.clear()
        assert await tp.is_enabled_for("user:1") is False
        await tp._set_enabled("user:1", True)
        assert await tp.is_enabled_for("user:1") is True
        await tp._set_enabled("user:1", False)
        assert await tp.is_enabled_for("user:1") is False

    asyncio.run(scenario())
