"""新小功能的纯逻辑：掷骰、抽选、投票、配对、兽设、搜源过滤、加字。"""
from __future__ import annotations

import importlib
import random
from datetime import datetime, timezone
from urllib.parse import urlparse

import pytest

from neobot.core.handlers.unknown_command import suggest_command
from neobot.core.managers.command_manager import matcher
from neobot.plugins import caption, daily, decide, dice, e926_gallery, furry, fursona, fursona_roll
from neobot.plugins import image_source, music, poll, weather, web_parser

importlib.import_module("neobot.plugins.osu!_plugin")
importlib.import_module("neobot.plugins.poke_reply")
_ = web_parser
from neobot.plugins.cooldown import Cooldown
from neobot.plugins.daily_cp import pick_partner, shanghai_day
from neobot.plugins.mentions import mentioned_user_ids


class _Seg:
    def __init__(self, kind, **data):
        self.type = kind
        self.data = data


def test_dice_expression_and_limits():
    terms = dice.parse_dice_expression("2d6+3")
    assert terms == [("dice", 1, 2, 6), ("mod", 1, 3)]
    assert dice.parse_dice_expression("d20")[0] == ("dice", 1, 1, 20)
    assert dice.parse_dice_expression("1d20+2d4-1")[1][0] == "dice"
    total, details = dice.roll_terms(dice.parse_dice_expression("2d6+3"), random.Random(1))
    assert details[0].startswith("+2d6(")
    assert total == sum(int(part) for part in details[0].split("(")[1][:-1].split("+")) + 3

    with pytest.raises(dice.DiceParseError) as too_many:
        dice.parse_dice_expression("101d6", max_dice=100)
    assert too_many.value.code == "dice"
    with pytest.raises(dice.DiceParseError) as faces:
        dice.parse_dice_expression("1d1001", max_faces=1000)
    assert faces.value.code == "faces"
    with pytest.raises(dice.DiceParseError):
        dice.parse_dice_expression("2d6+")
    with pytest.raises(dice.DiceParseError):
        dice.parse_dice_expression("hello")


def test_coc_ranks():
    assert dice.coc_rank(1, 49) == "大成功"
    assert dice.coc_rank(5, 49) == "极难成功"
    assert dice.coc_rank(96, 49) == "大失败"
    assert dice.coc_rank(95, 49) == "失败"
    assert dice.coc_rank(5, 50) == "大成功"
    assert dice.coc_rank(6, 50) == "极难成功"
    assert dice.coc_rank(25, 50) == "困难成功"
    assert dice.coc_rank(50, 50) == "成功"
    assert dice.coc_rank(51, 50) == "失败"
    assert dice.coc_rank(100, 50) == "大失败"
    assert dice.coc_rank(99, 100) == "成功"
    assert dice.parse_coc_args(["图书馆使用", "60"]) == ("图书馆使用", 60)
    with pytest.raises(dice.DiceParseError):
        dice.parse_coc_args(["侦查"])


def test_decide_and_lot_are_local():
    assert decide.split_decision("睡觉还是看群") == ["睡觉", "看群"]
    assert decide.split_decision("A还是B还是C") == ["A", "B", "C"]
    assert decide.split_choices(["火锅", "烧烤"]) == ["火锅", "烧烤"]
    assert decide.split_choices(["火锅、烧烤、面"]) == ["火锅", "烧烤", "面"]
    rng = random.Random(2)
    assert decide.choose_one(["甲", "乙"], rng) in {"甲", "乙"}
    text = decide.draw_lot(random.Random(3))
    assert text.startswith("抽到")
    assert any(name in text for name, _line in decide._LOTS)


def test_fursona_roll_uses_tables_and_is_seeded():
    first = fursona_roll.roll_from_tables(random.Random(4))
    second = fursona_roll.roll_from_tables(random.Random(4))
    assert first == second
    assert "物种：" in first
    assert "毛色：" in first
    assert "性格：" in first


def test_poll_one_vote_tally_and_expiry():
    title, options = poll.parse_poll_create("午饭 火锅 烧烤 面")
    assert title == "午饭"
    assert options == ["火锅", "烧烤", "面"]
    titled, split_options = poll.parse_poll_create("午饭｜火锅｜烧烤")
    assert titled == "午饭" and split_options == ["火锅", "烧烤"]
    created = poll.new_poll("午饭", ["火锅", "烧烤"], "7", now=1000, ttl_seconds=10)
    assert poll.cast_vote(created, "8", 0) == "ok"
    assert poll.cast_vote(created, "8", 1) == "already"
    assert poll.cast_vote(created, "9", 5) == "range"
    assert poll.tally(2, created["votes"]) == [1, 0]
    assert poll.active_polls([created], now=1005) == [created]
    assert poll.active_polls([created], now=2000) == []
    assert poll.can_close(created, "7", False) is True
    assert poll.can_close(created, "8", False) is False
    assert poll.can_close(created, "8", True) is True
    text = poll.format_results(created)
    assert "火锅  1 票" in text
    with pytest.raises(ValueError):
        poll.parse_poll_create("只有题目")


def test_daily_cp_is_stable_and_skips_opt_out():
    day = shanghai_day(datetime(2026, 11, 11, 16, 30, tzinfo=timezone.utc))
    assert day == "2026-11-12"
    members = [1, 2, 3, 4]
    first = pick_partner(1, members, [], day, 9, salt="s")
    again = pick_partner(1, members, [], day, 9, salt="s")
    assert first == again
    assert first in {2, 3, 4}
    assert pick_partner(1, members, [first], day, 9, salt="s") != first
    assert pick_partner(1, [1, 2], [2], day, 9) is None
    assert pick_partner(1, members, [1], day, 9) is None
    other_day = pick_partner(1, members, [], "2026-11-13", 9, salt="s")
    assert other_day in {2, 3, 4}


def test_fursona_profile_parse_and_format():
    profile = fursona.parse_profile("小桃｜狐狸｜蜜糖棕｜喜欢晒太阳")
    assert profile["name"] == "小桃"
    assert profile["bio"] == "喜欢晒太阳"
    spaced = fursona.parse_profile("小桃 狐狸 蜜糖棕 喜欢晒太阳")
    assert spaced["species"] == "狐狸"
    text = fursona.format_profile(profile)
    assert "物种：狐狸" in text
    assert "简介：喜欢晒太阳" in text
    with pytest.raises(ValueError):
        fursona.parse_profile("只有名字")
    with pytest.raises(ValueError):
        fursona.parse_profile("名｜种｜色｜" + "很" * 90)


def test_fortune_can_target_a_mention():
    event = type("E", (), {})()
    event.user_id = 1
    event.message = [_Seg("at", qq="2"), _Seg("text", text="看看")]
    assert daily.fortune_subject(event) == (2, True)
    event.message = []
    assert daily.fortune_subject(event) == (1, False)
    assert mentioned_user_ids([_Seg("at", qq="all"), _Seg("at", qq="3")]) == [3]


def test_weather_resolves_city_names():
    codes = {"南京": "101190101", "北京": "101010100", "南京市": "101190101"}
    assert weather.resolve_city("南京", codes) == ("101190101", "南京")
    assert weather.resolve_city("101010100", codes)[0] == "101010100"
    assert weather.resolve_city("没有这个城", codes) == (None, None)


def test_furry_urls_are_unique():
    urls = furry.unique_furry_urls(3, ["a", "a", "b", "c"])
    assert len(urls) == 3
    assert len(set(urls)) == 3
    assert all("cb=" in url for url in urls)


def test_e926_tags_reject_unsafe_and_keep_safe_posts():
    blacklist = ["cub", "young", "gore"]
    assert e926_gallery.normalize_tags(["Fox", "cute"], blacklist) == ["fox", "cute"]
    with pytest.raises(e926_gallery.TagRejected):
        e926_gallery.normalize_tags(["young"], blacklist)
    with pytest.raises(e926_gallery.TagRejected):
        e926_gallery.normalize_tags(["中文"], blacklist)
    count, tags = e926_gallery.parse_tag_args(["2", "fox"], max_count=3)
    assert count == 2 and tags == ["fox"]
    payload = {
        "posts": [
            {"rating": "s", "tags": {"general": ["fox"]}, "file": {"url": "https://static1.e926.net/a.jpg"}},
            {"rating": "e", "tags": {"general": ["fox"]}, "file": {"url": "https://static1.e926.net/b.jpg"}},
            {"rating": "s", "tags": {"general": ["cub"]}, "file": {"url": "https://static1.e926.net/c.jpg"}},
        ]
    }
    assert e926_gallery.safe_post_urls(payload, blacklist, 3) == ["https://static1.e926.net/a.jpg"]


def test_saucenao_hides_nsfw_and_reports_quota():
    payload = {
        "header": {"status": 0, "long_remaining": 10, "short_remaining": 3},
        "results": [
            {
                "header": {"similarity": "90.5", "hidden": 0},
                "data": {"ext_urls": ["https://www.pixiv.net/artworks/1"], "creator": "桃"},
            },
            {
                "header": {"similarity": "99", "hidden": 2},
                "data": {"ext_urls": ["https://example.com/nsfw"], "creator": "x"},
            },
            {
                "header": {"similarity": "80", "hidden": 0},
                "data": {"ext_urls": ["https://nhentai.net/g/1"], "author": "no"},
            },
        ],
    }
    error, kept = image_source.filter_saucenao_results(payload, min_similarity=55)
    assert error is None
    assert len(kept) == 1
    assert kept[0]["author"] == "桃"
    assert urlparse(kept[0]["links"][0]).hostname == "www.pixiv.net"
    text = image_source.format_source_reply(kept, "SauceNAO")
    assert "相似度" in text
    assert "作者：桃" in text
    assert "https://" in text
    quota = image_source.saucenao_error_message({"status": 3, "message": "daily limit"})
    assert "额度" in quota
    html = """
    <div class="row item-box">
      <a href="https://www.pixiv.net/artworks/9">题目</a>
      <a href="https://www.pixiv.net/users/8">作者甲</a>
      <a href="https://ascii2d.net/self">忽略</a>
    </div>
    <div class="row item-box">
      <a href="https://nhentai.net/g/1">不要</a>
    </div>
    """
    parsed = image_source.parse_ascii2d_html(html)
    assert parsed[0]["links"] == ["https://www.pixiv.net/artworks/9"]
    assert parsed[0]["author"] == "作者甲"
    assert all(urlparse(item["links"][0]).hostname != "nhentai.net" for item in parsed)


def test_caption_wraps_and_renders_cjk():
    font_path = str(caption._FONT)
    font = caption.ImageFont.truetype(font_path, size=20, index=0)
    lines = caption.wrap_text("今天想贴贴一下", font, max_width=40)
    assert len(lines) > 1
    size, laid = caption.layout_caption("短", 400, font_path)
    long_size, long_lines = caption.layout_caption("这是一句比较长的加字用来检查会不会换行缩小", 180, font_path)
    assert size >= long_size or len(long_lines) >= len(laid)
    from PIL import Image
    import io

    buffer = io.BytesIO()
    Image.new("RGB", (80, 40), (20, 20, 20)).save(buffer, format="PNG")
    rendered = caption.render_caption_image(buffer.getvalue(), "贴贴", font_path, max_chars=36)
    assert rendered[:2] == b"\xff\xd8"
    with pytest.raises(caption.CaptionError):
        caption.normalize_caption("字" * 40, max_chars=36)


def test_music_links_and_endpoint_choice():
    links = music.find_song_links(
        "听 https://music.163.com/#/song?id=3404293607 和 https://youtu.be/dQw4w9WgXcQ"
    )
    kinds = {item["kind"]: item["key"] for item in links}
    assert kinds["netease"] == "3404293607"
    assert kinds["youtube"] == "dQw4w9WgXcQ"
    y_link = music.find_song_links("https://y.music.163.com/m/song?id=99")
    assert y_link[0]["key"] == "99"
    path_link = music.find_song_links("https://music.163.com/song/88")
    assert path_link[0]["key"] == "88"
    watch = music.find_song_links("https://www.youtube.com/watch?v=abcdefghijk")
    assert watch[0]["kind"] == "youtube"
    kugou = music.find_song_links("https://www.kugou.com/song/#hash=6C7A0C6C1E6C4A0E8F0A0C6C1E6C4A0E")
    assert kugou[0]["kind"] == "kugou"
    assert music.find_song_links("随便聊聊 hash=6C7A0C6C1E6C4A0E8F0A0C6C1E6C4A0E") == []
    base, style = music.resolve_music_endpoint("", "https://example.test", "ncm")
    assert base == "https://example.test" and style == "ncm"
    base, style = music.resolve_music_endpoint("http://127.0.0.1:5000", "https://example.test", "netease_url")
    assert base == "http://127.0.0.1:5000" and style == "netease_url"
    assert music.play_url_from_template("https://play.example/u?id={id}", 12).endswith("id=12")
    card = music.format_link_card("youtube", "歌", "人", "https://youtu.be/x")
    assert "YouTube" in card and "https://youtu.be/x" in card


def test_cooldown_and_new_commands_are_hintable():
    limiter = Cooldown()
    assert limiter.allow("g", 10, now=0) is True
    assert limiter.allow("g", 10, now=5) is False
    assert limiter.allow("g", 10, now=10) is True
    names = list(matcher.message_handler.platform_commands.get("qq", {}))
    for command in (
        "r", "骰", "coc", "决定", "选", "抽签", "随机兽设", "抽种",
        "投票", "投", "加字", "今日CP", "CP退出", "CP加入",
        "登记兽设", "兽设", "删除兽设", "搜源", "兽图", "moe", "点歌",
    ):
        assert command in names
    assert suggest_command("随机兽", names) == "随机兽设"
    assert suggest_command("今日猪猪", names) is None
    assert "查仓库" in names
    assert matcher.message_handler.platform_commands["qq"]["查仓库"]["func"].__module__.endswith("web_parser")
    assert matcher.message_handler.platform_commands["qq"]["osu"]["func"].__module__.endswith("osu!_plugin")
