"""本地随机决定：二选一、多选一、抽签。"""
from __future__ import annotations

import random
import re
from typing import List, Optional, Sequence

from neobot.plugin_api import MessageEvent, define_plugin, platform_command

plugin_manifest = define_plugin(
    name="decide",
    description="帮你做个小决定",
    usage=(
        "/决定 A还是B - 从「还是」两边挑一个\n"
        "/选 A B C - 从多个选项里挑一个\n"
        "/抽签 - 抽一支上上签到下下签"
    ),
    version="0.1.0",
)

_LOTS = (
    ("上上签", "今天适合把喜欢的事做完。"),
    ("上签", "会有一件小好事靠近你。"),
    ("中签", "平平常常，也刚刚好。"),
    ("下签", "慢一点就好，别跟自己较劲。"),
    ("下下签", "先喝口水，剩下的明天再说。"),
)


def split_decision(text: str) -> List[str]:
    parts = [item.strip() for item in re.split(r"还是", text or "") if item.strip()]
    return parts


def split_choices(args: Sequence[str]) -> List[str]:
    if len(args) == 1 and ("、" in args[0] or "/" in args[0] or "／" in args[0]):
        raw = re.split(r"[、/／]", args[0])
        return [item.strip() for item in raw if item.strip()]
    return [item.strip() for item in args if item and item.strip()]


def choose_one(options: Sequence[str], rng: Optional[random.Random] = None) -> str:
    chooser = rng or random
    return chooser.choice(list(options))


def draw_lot(rng: Optional[random.Random] = None) -> str:
    chooser = rng or random
    name, line = chooser.choice(_LOTS)
    return f"抽到{name}\n{line}"


@platform_command(["qq", "discord"], "决定")
async def handle_decide(bot, event: MessageEvent, args: list):
    options = split_decision(" ".join(args))
    if len(options) < 2:
        await event.reply("用法：/决定 睡觉还是看群")
        return
    picked = choose_one(options)
    await event.reply(f"那就选「{picked}」吧。")


@platform_command(["qq", "discord"], "选")
async def handle_choose(bot, event: MessageEvent, args: list):
    options = split_choices(args)
    if len(options) < 2:
        await event.reply("用法：/选 火锅 烧烤 面")
        return
    picked = choose_one(options)
    await event.reply(f"抽到「{picked}」。")


@platform_command(["qq", "discord"], "抽签")
async def handle_lot(bot, event: MessageEvent, args: list):
    await event.reply(draw_lot())
