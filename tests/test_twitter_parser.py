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


# ── ffmpeg 水印处理（2026-08 新增：改变文件指纹后发送） ──────────


def test_random_meta_title_format():
    for _ in range(20):
        title = tp._random_meta_title()
        word, _, num = title.rpartition(" ")
        assert word in tp._WATERMARK_TITLE_WORDS
        assert num.isdigit() and len(num) == 4


def test_random_meta_time_iso():
    import re as _re

    for _ in range(20):
        ts = tp._random_meta_time()
        # ISO8601: 2026-08-19T07:25:12
        assert _re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}", ts)


def test_build_watermark_filter():
    f = tp._build_watermark_filter("2026-08-19 18:25:00")
    # 8 行全屏铺底 + 1 个右下角清晰时间戳
    assert f.count("drawtext=") == 9
    # 时间戳冒号必须转义（filter 语法中 : 是分隔符）
    assert r"18\:25\:00" in f
    # 右下角时间戳带黑边
    assert "borderw=2" in f and "bordercolor=black@0.7" in f
    # 全屏铺底是半透明
    assert "fontcolor=white@0.15" in f


def test_watermark_video_returns_none_when_ffmpeg_missing(monkeypatch):
    """ffmpeg 不可用时水印处理直接返回 None（调用方回退原逻辑）。"""
    monkeypatch.setattr(tp, "FFMPEG_AVAILABLE", False)

    async def scenario():
        assert await tp._watermark_video("https://video.twimg.com/v.mp4") is None

    asyncio.run(scenario())


def test_watermark_video_returns_none_when_server_down(monkeypatch):
    """本地文件服务器未启动时水印处理返回 None。"""
    monkeypatch.setattr(tp, "FFMPEG_AVAILABLE", True)
    monkeypatch.setattr(
        tp, "get_local_file_server", lambda: type("S", (), {"site": None})(),
    )

    async def scenario():
        assert await tp._watermark_video("https://video.twimg.com/v.mp4") is None

    asyncio.run(scenario())
