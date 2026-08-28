# -*- coding: utf-8 -*-
"""maimaiDX B50 插件单元测试（纯逻辑，无网络）。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from neobot.plugins.maimaidx.service import (
    build_song_list, build_best50, dan_name, cover_file_id, ra_color, level_color,
    FC_COLORS, subject_ref, mask_qq,
)
from neobot.plugins.maimaidx import _extract_at_qq


def _chart(**overrides):
    c = {
        "song_id": 11741, "title": "Cryptarithm", "type": "DX", "ds": 14.7,
        "achievements": 100.6494, "fc": "", "fs": "sync", "level": "14+",
        "level_index": 3, "level_label": "Master", "ra": 330, "rate": "sssp",
    }
    c.update(overrides)
    return c


# ── build_song_list ─────────────────────────────────────────────

def test_build_song_list_sorted_by_ra_desc():
    """dx+sd 合并后按 ra 降序，rank 从 1 开始。"""
    data = {
        "charts": {
            "dx": [_chart(song_id=1, ra=300, title="A"), _chart(song_id=2, ra=310, title="B")],
            "sd": [_chart(song_id=3, ra=280, title="C", type="SD")],
        }
    }
    songs = build_song_list(data)
    assert [s["ra"] for s in songs] == [310, 300, 280]
    assert [s["rank"] for s in songs] == [1, 2, 3]
    assert songs[0]["title"] == "B"
    assert songs[0]["song_id"] == 2


def test_build_song_list_fields():
    """展示字段完整：song_id/level_color/ra_color/rate 大写/type。"""
    s = build_song_list({"charts": {"dx": [_chart()], "sd": []}})[0]
    assert s["song_id"] == 11741
    assert s["rate"] == "SSSP"
    assert s["type"] == "DX"
    assert s["level"] == "14+"
    assert s["level_color"] == "#d32f2f"
    assert s["ra_color"] == "#ffd700"
    assert s["rate_color"] == "#ffd700"


def test_build_song_list_fc_fs_badges():
    """fc/fs 徽章合并；fcp 显示 FC+；fsd 显示 FSD；空状态无徽章。"""
    data = {"charts": {"dx": [_chart(fc="fcp", fs="fsd")], "sd": []}}
    badges = build_song_list(data)[0]["badges"]
    texts = [b["text"] for b in badges]
    assert texts == ["FC+", "FSD"]
    assert badges[0]["color"] == FC_COLORS["fcp"]

    data = {"charts": {"dx": [_chart(fc="", fs="")], "sd": []}}
    assert build_song_list(data)[0]["badges"] == []

    data = {"charts": {"dx": [_chart(fc="ap", fs="fsdp")], "sd": []}}
    texts = [b["text"] for b in build_song_list(data)[0]["badges"]]
    assert texts == ["AP", "FSD+"]


def test_build_song_list_empty():
    assert build_song_list({"charts": {"dx": [], "sd": []}}) == []


def test_build_best50_takes_top50_sorted():
    """完整成绩平铺列表 → ra 前 50，降序，装饰字段齐全。"""
    records = [_chart(song_id=i, ra=300 - i, title=f"S{i}") for i in range(60)]
    songs = build_best50(records)
    assert len(songs) == 50
    assert [s["ra"] for s in songs] == sorted([s["ra"] for s in songs], reverse=True)
    assert songs[0]["title"] == "S0"
    assert songs[-1]["ra"] == 300 - 49
    assert songs[0]["rank"] == 1
    assert songs[0]["ra_color"] == "#ffb300"  # ra 300 → 300 档色


# ── OAuth 绑定辅助 ─────────────────────────────────────────────

def test_subject_ref_stable_and_unique():
    """ref 摘要：确定性 + 跨用户唯一 + 64 位 hex。"""
    a1 = subject_ref("2221577113")
    a2 = subject_ref("2221577113")
    b = subject_ref("123456")
    assert a1 == a2
    assert a1 != b
    assert len(a1) == 64
    int(a1, 16)  # 合法 hex


def test_mask_qq():
    assert mask_qq("2221577113") == "QQ 22****13"
    assert mask_qq("123") == "QQ ****"


# ── 纯函数 ──────────────────────────────────────────────────────

def test_dan_name():
    assert dan_name(0) == "初学者"
    assert dan_name(10) == "十段"
    assert dan_name(11) == "真初段"
    assert dan_name(21) == "真皆伝"
    assert dan_name(22) == "裏皆伝"
    assert dan_name(23) == ""
    assert dan_name(-1) == ""
    assert dan_name(None) == ""


def test_cover_file_id():
    assert cover_file_id(38) == "00038"
    assert cover_file_id(1235) == "01235"
    assert cover_file_id(11741) == "11741"
    # 10001~11000 段（DX 谱面共用 SD 封面）：减 10000
    assert cover_file_id(10500) == "00500"
    assert cover_file_id(11000) == "01000"
    assert cover_file_id(10001) == "00001"
    assert cover_file_id(11001) == "11001"


def test_ra_color_boundaries():
    assert ra_color(320) == "#ffd700"
    assert ra_color(300) == "#ffb300"
    assert ra_color(280) == "#ff7043"
    assert ra_color(260) == "#ab47bc"
    assert ra_color(240) == "#42a5f5"
    assert ra_color(239) == "#78909c"
    assert ra_color(None) == "#78909c"


def test_level_color_boundaries():
    assert level_color("6") == "#66bb6a"
    assert level_color("9") == "#42a5f5"
    assert level_color("11") == "#ab47bc"
    assert level_color("12+") == "#ff9800"
    assert level_color("13") == "#ef5350"
    assert level_color("14+") == "#d32f2f"
    assert level_color("15") == "#ffd700"


# ── @某人 CQ 码解析 ─────────────────────────────────────────────

class _FakeSeg:
    def __init__(self, seg_type, data):
        self.type = seg_type
        self.data = data


class _FakeEvent:
    def __init__(self, segments):
        self.message = segments


def test_extract_at_qq_from_segments():
    """事件消息段里的 at → QQ。"""
    ev = _FakeEvent([_FakeSeg("text", {"text": "/b50 "}), _FakeSeg("at", {"qq": "2221577113"})])
    assert _extract_at_qq(ev, "/b50 ") == "2221577113"


def test_extract_at_qq_cq_regex_fallback():
    """消息段无 at 时，raw 文本里的 CQ 码兜底。"""
    ev = _FakeEvent([_FakeSeg("text", {"text": "/b50 "})])
    assert _extract_at_qq(ev, "/b50 [CQ:at,qq=123456]") == "123456"


def test_extract_at_qq_none():
    ev = _FakeEvent([_FakeSeg("text", {"text": "/b50 turou"})])
    assert _extract_at_qq(ev, "/b50 turou") is None
    assert _extract_at_qq(_FakeEvent([]), "") is None
    assert _extract_at_qq(_FakeEvent([_FakeSeg("at", {"qq": "all"})]), "") is None
