# -*- coding: utf-8 -*-
"""禁漫天堂（JMComic）PDF 解析插件的单元测试。"""
import asyncio

from neobot.plugins import jinman_parser as jp


def test_extract_album_id_bare_number():
    assert jp.extract_album_id("123456") == "123456"
    assert jp.extract_album_id("  421234  ") == "421234"


def test_extract_album_id_jm_prefix():
    assert jp.extract_album_id("JM123456") == "123456"
    assert jp.extract_album_id("jm421234") == "421234"


def test_extract_album_id_from_url():
    assert jp.extract_album_id("https://18comic.vip/album/123456") == "123456"
    assert jp.extract_album_id("https://jmcomic.me/album/421234/") == "421234"
    assert jp.extract_album_id("https://18comic1.org/photo/555666") == "555666"
    assert jp.extract_album_id("看这个 https://ww.18comic.vip/album/99999 很棒") == "99999"


def test_extract_album_id_invalid():
    assert jp.extract_album_id("") is None
    assert jp.extract_album_id("abc") is None
    assert jp.extract_album_id("https://example.com/album/123") is None
    assert jp.extract_album_id("12") is None  # 车牌号至少 3 位


def test_build_pdf_filename():
    assert jp._build_pdf_filename("123456", "测试标题") == "[123456] 测试标题.pdf"
    assert jp._build_pdf_filename("123456", "") == "[123456].pdf"
    assert jp._build_pdf_filename("123456", None) == "[123456].pdf"


def test_sanitize_filename():
    assert jp._sanitize_filename('a/b\\c:d*e?f"g<h>i|j') == "abcdefghij"
    assert jp._sanitize_filename("  标题  ") == "标题"
    assert jp._sanitize_filename("x" * 200) == "x" * 120
    assert jp._sanitize_filename("///") == "JM"


def test_default_disabled_and_memory_toggle():
    async def scenario():
        jp._enabled_map.clear()
        assert await jp.is_enabled_for("group:1") is False
        await jp._set_enabled("group:1", True)
        assert await jp.is_enabled_for("group:1") is True
        await jp._set_enabled("group:1", False)
        assert await jp.is_enabled_for("group:1") is False

    asyncio.run(scenario())
