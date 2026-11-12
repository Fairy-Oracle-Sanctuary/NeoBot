"""随机一份 SFW 兽设草稿，只在本地表里抽。"""
from __future__ import annotations

import random
from typing import Optional, Sequence

from neobot.plugin_api import MessageEvent, define_plugin, platform_command

plugin_manifest = define_plugin(
    name="fursona_roll",
    description="随机一份可公开的兽设草稿",
    usage="/随机兽设（别名 /抽种）- 随机物种、毛色、性格和一个小特点",
    version="0.1.0",
)

SPECIES = (
    "狐狸", "狼", "猫", "雪豹", "虎", "狮子", "熊", "兔子", "鹿", "龙",
    "鸟", "水獭", "浣熊", "山羊", "马", "蛇", "鲨鱼", "熊猫", "仓鼠", "考拉",
)
PRIMARY_COLORS = ("奶油白", "蜜糖棕", "炭灰", "暮灰", "晴空蓝", "薄荷绿", "暖杏", "浅金", "雾粉", "深棕")
SECONDARY_COLORS = ("耳尖白", "尾巴尖黑", "胸口浅色", "爪垫粉", "脊背深一号", "眼周一圈浅毛")
PERSONALITIES = ("软乎乎", "话不多", "爱凑热闹", "慢热", "认真", "有点呆", "好奇心重", "喜欢被摸耳朵")
TRAITS = (
    "左耳有个很小的缺口",
    "尾巴尖是白色的",
    "口袋里总有一颗糖",
    "下雨天会先找屋檐",
    "喜欢收集瓶盖",
    "走路时尾巴会轻轻摇",
    "听到喜欢的歌会站住",
    "围巾总是围得松松的",
)


def roll_fursona(rng: Optional[random.Random] = None) -> str:
    chooser = rng or random
    species = chooser.choice(SPECIES)
    primary = chooser.choice(PRIMARY_COLORS)
    secondary = chooser.choice(SECONDARY_COLORS)
    personality = chooser.choice(PERSONALITIES)
    trait = chooser.choice(TRAITS)
    return format_fursona(species, primary, secondary, personality, trait)


def format_fursona(
    species: str,
    primary: str,
    secondary: str,
    personality: str,
    trait: str,
) -> str:
    return (
        "随机兽设\n"
        f"物种：{species}\n"
        f"毛色：{primary}，{secondary}\n"
        f"性格：{personality}\n"
        f"小特点：{trait}\n"
        "只是玩的草稿，想留下来可以用 /登记兽设。"
    )


def roll_from_tables(
    rng: random.Random,
    species: Sequence[str] = SPECIES,
    primary: Sequence[str] = PRIMARY_COLORS,
    secondary: Sequence[str] = SECONDARY_COLORS,
    personalities: Sequence[str] = PERSONALITIES,
    traits: Sequence[str] = TRAITS,
) -> str:
    return format_fursona(
        rng.choice(list(species)),
        rng.choice(list(primary)),
        rng.choice(list(secondary)),
        rng.choice(list(personalities)),
        rng.choice(list(traits)),
    )


@platform_command(["qq", "discord"], "随机兽设", "抽种")
async def handle_roll(bot, event: MessageEvent, args: list):
    await event.reply(roll_fursona())
