# -*- coding: utf-8 -*-
"""小红书解析器的单元测试（纯解析函数，不触网）。"""
import json

from neobot.plugins.web_parser.parsers.xhs import (
    XHS_SHORT_RE,
    XHS_URL_RE,
    XhsParser,
    extract_initial_state_json,
    extract_note_id,
    parse_note_json,
    parse_note_object,
    pick_title,
    pick_video_url,
)


def test_long_url_patterns():
    # explore / discovery/item / user/profile 三种长链接形态
    assert XHS_URL_RE.search("https://www.xiaohongshu.com/explore/64abc123")
    assert XHS_URL_RE.search("https://www.xiaohongshu.com/explore/64abc123?xsec_token=ABC")
    assert XHS_URL_RE.search("https://www.xiaohongshu.com/discovery/item/64abc123")
    assert XHS_URL_RE.search("https://www.xiaohongshu.com/user/profile/123456/64abc123")
    # 文本中混排也能提取
    assert XHS_URL_RE.search("看看这个 https://www.xiaohongshu.com/explore/AbC123 好赞").group(0).startswith("https://www.xiaohongshu.com/explore/AbC123")


def test_short_url_patterns():
    assert XHS_SHORT_RE.search("https://xhslink.com/AbC123")
    assert XHS_SHORT_RE.search("http://xhslink.com/o/AbC123")
    assert XHS_SHORT_RE.search("https://xhslink.cn/AbC123")


def test_should_handle_url():
    parser = XhsParser()
    assert parser.should_handle_url("https://www.xiaohongshu.com/explore/64abc123")
    assert parser.should_handle_url("https://xhslink.com/AbC123")
    assert parser.should_handle_url("https://xhslink.cn/o/AbC123")
    # 伪装的 host 子串不应命中
    assert not parser.should_handle_url("https://example.com/xiaohongshu.com/explore/1")
    assert not parser.should_handle_url("https://douyin.com/video/1")


def test_is_short_url():
    parser = XhsParser()
    assert parser.is_short_url("https://xhslink.com/AbC123")
    assert parser.is_short_url("http://xhslink.cn/o/AbC123")
    assert not parser.is_short_url("https://www.xiaohongshu.com/explore/1")


def test_extract_note_id():
    assert extract_note_id("https://www.xiaohongshu.com/explore/64abc123") == "64abc123"
    assert extract_note_id("https://www.xiaohongshu.com/discovery/item/64abc123?xsec_token=X") == "64abc123"
    assert extract_note_id("https://xhslink.com/AbC123") is None


def test_extract_initial_state_basic():
    html = '<html><script>window.__INITIAL_STATE__={"user":{"nickname":"测试"},"note":{}}</script></html>'
    raw = extract_initial_state_json(html)
    assert raw == '{"user":{"nickname":"测试"},"note":{}}'


def test_extract_initial_state_skips_braces_in_strings():
    # 字符串字面量里的花括号不应干扰配平
    html = 'window.__INITIAL_STATE__={"a":"{b}c","c":{"d":1}}'
    raw = extract_initial_state_json(html)
    assert raw == '{"a":"{b}c","c":{"d":1}}'


def test_extract_initial_state_handles_escaped_quotes():
    html = 'window.__INITIAL_STATE__={"a":"x\\"y","c":1}'
    raw = extract_initial_state_json(html)
    assert raw == '{"a":"x\\"y","c":1}'


def test_extract_initial_state_replaces_undefined():
    # XHS SSR 载荷含 :undefined 哨兵，必须替换成 null 才能解析
    html = 'window.__INITIAL_STATE__={"a":1,"b":undefined,"c":{"d": undefined}}'
    raw = extract_initial_state_json(html)
    assert ":null" in raw and "undefined" not in raw
    # 替换后必须是合法 JSON
    assert json.loads(raw) == {"a": 1, "b": None, "c": {"d": None}}


def test_extract_initial_state_missing_marker():
    assert extract_initial_state_json("<html>no payload here</html>") is None


def test_parse_video_note():
    payload = {
        "note": {
            "noteDetailMap": {
                "64abc123": {
                    "note": {
                        "title": "测试视频笔记",
                        "desc": "正文内容",
                        "user": {"nickname": "博主A"},
                        "video": {
                            "media": {
                                "stream": {
                                    "h264": [
                                        {"masterUrl": "http://sns-video-hw.xhscdn.com/big.mp4", "size": 1024000},
                                        {"masterUrl": "http://sns-video-hw.xhscdn.com/mid.mp4", "size": 512000},
                                    ],
                                    "h265": [{"masterUrl": "http://sns-video-hw.xhscdn.com/small.mp4", "size": 256000}],
                                }
                            }
                        },
                        "imageList": [],
                    }
                }
            }
        }
    }
    result = parse_note_json(json.dumps(payload))
    assert result is not None
    assert result["type"] == "video"
    # 取最小清晰度直链，且 http 统一升级为 https
    assert result["video_url"] == "https://sns-video-hw.xhscdn.com/small.mp4"
    assert result["nickname"] == "博主A"
    assert result["desc"] == "测试视频笔记"
    assert result["images"] == []


def test_parse_image_note():
    payload = {
        "note": {
            "noteDetailMap": {
                "64abc123": {
                    "note": {
                        "title": "",
                        "desc": "[话题]测试图集[话题]#\n第二行正文",
                        "user": {"nickName": "博主B"},
                        "video": None,
                        "imageList": [
                            {"urlDefault": "http://sns-img-hw.xhscdn.com/1.jpg"},
                            {"url": "http://sns-img-hw.xhscdn.com/2.jpg"},
                            {"infoList": [{"url": "http://sns-img-hw.xhscdn.com/3.jpg"}]},
                            {},
                        ],
                    }
                }
            }
        }
    }
    result = parse_note_json(json.dumps(payload))
    assert result is not None
    assert result["type"] == "image"
    assert result["images"] == [
        "https://sns-img-hw.xhscdn.com/1.jpg",
        "https://sns-img-hw.xhscdn.com/2.jpg",
        "https://sns-img-hw.xhscdn.com/3.jpg",
    ]
    # title 为空时取 desc 第一行，去掉 [话题] 标记
    assert result["desc"] == "[话题]测试图集#"
    assert result["nickname"] == "博主B"
    assert result["video_url"] == ""


def test_parse_note_deep_find_fallback():
    # 无 noteDetailMap 时深度遍历也能找到 note 对象
    payload = {"data": {"feed": {"nested": {"title": "深层标题", "user": {}, "imageList": [{"urlDefault": "http://x/1.jpg"}]}}}}
    result = parse_note_json(json.dumps(payload))
    assert result is not None
    assert result["desc"] == "深层标题"
    assert result["type"] == "image"


def test_parse_note_no_media():
    assert parse_note_object({"title": "x", "user": {}, "video": None, "imageList": []}) is None


def test_pick_title():
    assert pick_title("标题", "正文") == "标题"
    assert pick_title("", "第一行\n第二行") == "第一行"
    assert pick_title(None, "  \n第二行") == "第二行"
    # [话题]# 标记清理
    assert pick_title("", "[话题]第一行[话题]#") == "[话题]第一行#"
    # 超过 60 字截断（60 字 + …）
    long_desc = "长" * 70
    truncated = pick_title(None, long_desc)
    assert len(truncated) == 61 and truncated.endswith("…")


def test_pick_video_url_empty():
    assert pick_video_url(None) == ""
    assert pick_video_url({"media": {"stream": {}}}) == ""
    # 无 masterUrl 时用 backupUrls 兜底
    assert pick_video_url(
        {"media": {"stream": {"h264": [{"backupUrls": ["http://cdn.com/backup.mp4"]}]}}}
    ) == "https://cdn.com/backup.mp4"


def test_parse_invalid_json():
    assert parse_note_json("not json at all") is None
