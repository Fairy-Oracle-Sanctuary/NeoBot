# -*- coding: utf-8 -*-
"""抖音网页逆向解析器的单元测试（纯逻辑，无网络）。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from neobot.plugins.web_parser.parsers.douyin_web import _extract_result


def _video_item(**overrides):
    item = {
        "aweme_id": "7667129679366895241",
        "desc": "测试视频",
        "create_time": 1785142739,
        "author": {"nickname": "测试作者", "uid": "123",
                   "avatar_larger": {"url_list": ["https://a.com/avatar.jpg"]}},
        "statistics": {"digg_count": 1005, "comment_count": 10},
        "video": {
            "play_addr": {"url_list": ["https://v.douyin.com/video.mp4"]},
            "cover": {"url_list": ["https://c.douyin.com/cover.jpg"]},
        },
        "images": [],
    }
    item.update(overrides)
    return item


def test_extract_video():
    """有 play_addr 无 images → 视频，含封面/头像/点赞/时间。"""
    r = _extract_result(_video_item())
    assert r is not None
    assert r["type"] == "video"
    assert r["video_url"] == "https://v.douyin.com/video.mp4"
    assert r["video_url_HQ"] == r["video_url"]
    assert r["nickname"] == "测试作者"
    assert r["desc"] == "测试视频"
    assert r["aweme_id"] == "7667129679366895241"
    assert r["like"] == 1005
    assert r["cover"] == "https://c.douyin.com/cover.jpg"
    assert r["author_avatar"] == "https://a.com/avatar.jpg"
    assert r["time"] == 1785142739
    assert r["images"] == []


def test_extract_image_set():
    """images 非空 → 图集，取每张图 url_list 首元素。"""
    item = _video_item()
    item["video"] = {}  # 无 video.cover 时封面应回退到首图
    item["images"] = [
        {"url_list": ["https://p1.douyinpic.com/1.jpg", "https://p1.douyinpic.com/1_big.jpg"]},
        {"url_list": ["https://p2.douyinpic.com/2.jpg"]},
        {},  # 无 url_list 的条目应被跳过
    ]
    r = _extract_result(item)
    assert r is not None
    assert r["type"] == "image"
    assert r["images"] == [
        "https://p1.douyinpic.com/1.jpg",
        "https://p2.douyinpic.com/2.jpg",
    ]
    # 图集封面回退到首图
    assert r["cover"] == "https://p1.douyinpic.com/1.jpg"


def test_extract_image_keeps_signed_url():
    """图集 URL 原样保留（含 ~tplv 模板段与 x-signature 签名参数）。

    剥离模板段会连签名参数一起剥掉 → 裸 URL 403（生产实测），
    url_list 返回的完整地址本身就是可下载的。
    """
    item = _video_item()
    item["video"] = {}
    signed = ("https://p3-pc-sign.douyinpic.com/tos-cn-i-0813c000-ce/abc123"
              "~tplv-dy-aweme-images-v2:3000?lk3s=138a59ce&x-expires=1788253200"
              "&x-signature=oUFzD0slTsIe5SuvK%2FMEVm%2BdenQ%3D")
    item["images"] = [
        {"url_list": [signed]},
        {"url_list": ["https://p9-pc-sign.douyinpic.com/tos-cn-i-0813c000-ce/def456"]},
    ]
    r = _extract_result(item)
    assert r is not None
    assert r["images"] == [
        signed,  # 原样保留，不剥离
        "https://p9-pc-sign.douyinpic.com/tos-cn-i-0813c000-ce/def456",
    ]


def test_extract_image_videos_for_dynamic_album():
    """动态图文（live_photo_type=1）每张图提取动态视频直链到 image_videos。"""
    item = _video_item()
    item["video"] = {}
    item["images"] = [
        {"url_list": ["https://p1.douyinpic.com/1.jpg"],
         "live_photo_type": 1,
         "video": {"play_addr": {"url_list": ["https://v.douyinvod.com/dyn1.mp4"]}}},
        {"url_list": ["https://p2.douyinpic.com/2.jpg"]},  # 无动态视频
        {"url_list": ["https://p3.douyinpic.com/3.jpg"],
         "video": {"play_addr": {},
                   "bit_rate": [{"play_addr": {"url_list": ["https://v.douyinvod.com/dyn3.mp4"]}}]}},
    ]
    r = _extract_result(item)
    assert r is not None
    assert r["type"] == "image"
    assert len(r["images"]) == 3
    assert r["image_videos"] == [
        "https://v.douyinvod.com/dyn1.mp4",
        "",
        "https://v.douyinvod.com/dyn3.mp4",
    ]


def test_extract_video_no_play_addr_falls_back_to_bit_rate():
    """play_addr 缺失时从 bit_rate 兜底取地址。"""
    item = _video_item()
    item["video"] = {
        "play_addr": {},
        "bit_rate": [{"play_addr": {"url_list": ["https://v.douyin.com/hq.mp4"]}}],
    }
    r = _extract_result(item)
    assert r is not None
    assert r["video_url"] == "https://v.douyin.com/hq.mp4"


def test_extract_no_media_returns_none():
    """既无视频直链也无图集 → None。"""
    item = _video_item()
    item["video"] = {}
    assert _extract_result(item) is None


def test_extract_music_and_avatar_fallback():
    """音乐字段与头像兜底（avatar_thumb）。"""
    item = _video_item()
    item["music"] = {"title": "BGM", "author": "音乐人",
                     "play_url": {"url_list": ["https://m.douyin.com/bgm.mp3"]}}
    item["author"] = {"nickname": "A", "uid": "1", "avatar_thumb": {"url_list": ["https://t.jpg"]}}
    r = _extract_result(item)
    assert r["music"] == {"title": "BGM", "author": "音乐人", "url": "https://m.douyin.com/bgm.mp3"}
    assert r["author_avatar"] == "https://t.jpg"


def test_extract_missing_author_fields():
    """作者信息缺失时的兜底默认值。"""
    r = _extract_result(_video_item(author={}, statistics={}))
    assert r["nickname"] == "未知作者"
    assert r["like"] == 0
    assert r["author_avatar"] == ""


def test_extract_live_photo_prefers_video():
    """实况照片(aweme_type=51): 有动态视频时按视频发送。"""
    item = _video_item(aweme_type=51)
    item["images"] = [{"url_list": ["https://p1.douyinpic.com/1.jpg"]}]
    r = _extract_result(item)
    assert r is not None
    assert r["type"] == "video"
    assert r["video_url"] == "https://v.douyin.com/video.mp4"
    assert r["images"] == []


def test_extract_live_photo_without_video_falls_back_to_images():
    """实况照片无视频直链时退回图集发送。"""
    item = _video_item(aweme_type=51)
    item["video"] = {}
    item["images"] = [{"url_list": ["https://p1.douyinpic.com/1.jpg"]}]
    r = _extract_result(item)
    assert r is not None
    assert r["type"] == "image"
    assert r["images"] == ["https://p1.douyinpic.com/1.jpg"]


def test_extract_regular_image_set_still_image():
    """普通图文(aweme_type=68)即使带视频预览字段仍按图集发送。"""
    item = _video_item(aweme_type=68)
    item["images"] = [{"url_list": ["https://p1.douyinpic.com/1.jpg"]}]
    r = _extract_result(item)
    assert r is not None
    assert r["type"] == "image"
    assert r["images"] == ["https://p1.douyinpic.com/1.jpg"]


def test_extract_wrong_types_do_not_crash():
    """author/statistics/video 为错误类型(字符串)时不应 AttributeError。"""
    r = _extract_result(_video_item(author="oops", statistics="oops", video="oops"))
    assert r is None or r["nickname"] == "未知作者"


def test_resolve_accepts_douyin_full_link():
    """完整抖音链接直接提取 aweme_id(纯本地,不发请求)。"""
    import asyncio
    from neobot.plugins.web_parser.parsers.douyin_web import _resolve_aweme_id
    r = asyncio.run(_resolve_aweme_id(
        "https://www.douyin.com/video/7667129679366895241?previous_page=app_code_link"))
    assert r == "7667129679366895241"


def test_resolve_rejects_non_douyin_domain():
    """完整链接但非抖音域 → None(SSRF 防护)。"""
    import asyncio
    from neobot.plugins.web_parser.parsers.douyin_web import _resolve_aweme_id
    assert asyncio.run(_resolve_aweme_id(
        "https://evil.com/video/7667129679366895241")) is None


def test_resolve_rejects_private_ip_with_douyin_substring():
    """内网 IP 链接即使带 douyin.com 子串也被拒绝(SSRF 防护)。"""
    import asyncio
    from neobot.plugins.web_parser.parsers.douyin_web import _resolve_aweme_id
    assert asyncio.run(_resolve_aweme_id(
        "http://169.254.169.254/latest/meta-data/?x=douyin.com")) is None
    assert asyncio.run(_resolve_aweme_id(
        "http://169.254.169.254/video/7667129679366895241?x=douyin.com")) is None


def test_resolve_rejects_evil_short_domain():
    """非 v.douyin.com 短链域 → None,不发网络请求。"""
    import asyncio
    from neobot.plugins.web_parser.parsers.douyin_web import _resolve_aweme_id
    assert asyncio.run(_resolve_aweme_id("https://evil.com/S56owBTq7ic")) is None
