"""每天的一点小事：运势和今天吃什么。

运势按「用户 + 日期」确定，同一个人同一天看到的是同一段话。
吃什么从配置的菜单里随机挑，菜单留空就用内置的一份。
"""
from __future__ import annotations

import hashlib
import random
from datetime import date
from typing import Iterable, Optional, Sequence

from neobot.plugin_api import (
    MessageEvent,
    ModuleLogger,
    define_plugin,
    global_config,
    platform_command,
)

logger = ModuleLogger("Daily")

plugin_manifest = define_plugin(
    name="daily",
    description="每天的一点小事：运势和今天吃什么",
    usage=(
        "/今日运势（别名 /运势）- 看看今天的运势，同一个人同一天结果不变\n"
        "/今天吃什么（别名 /吃什么、/今日吃什么）- 从菜单里挑一个"
    ),
    version="0.1.0",
)

_LEVELS = ("大吉", "中吉", "小吉", "平平", "小波动")
_COLORS = ("蜜桃粉", "薄荷绿", "晴空蓝", "奶油黄", "暮山紫", "暖杏色")
_ITEMS = ("一杯热牛奶", "窗台的绿植", "口袋里的糖", "刚晒过的围巾", "一枚回形针", "手写的便签")
_ADVICES = (
    "适合把拖着的小事做完，做完会很轻快。",
    "如果犹豫，就选让自己舒服的那个。",
    "今天适合给朋友发一句不为什么的问候。",
    "别赶时间，慢慢吃也会很香。",
    "想休息就休息，这不算偷懒。",
    "把喜欢的歌循环一遍刚刚好。",
)

DEFAULT_FOODS = (
    "番茄炒蛋",
    "青椒肉丝盖饭",
    "味噌拉面",
    "小笼包",
    "香菇鸡汤",
    "葱油拌面",
    "土豆炖牛腩",
    "煎饺",
    "紫菜蛋花汤配米饭",
    "沙拉鸡胸",
)


def fortune_text(user_id: int, day: str, salt: str = "") -> str:
    """同一 user_id、同一天、同一 salt 得到同一段运势。"""
    digest = hashlib.sha256(f"{salt}\n{user_id}\n{day}".encode("utf-8")).digest()

    def pick(options: Sequence[str], index: int) -> str:
        return options[digest[index] % len(options)]

    level = pick(_LEVELS, 0)
    color = pick(_COLORS, 1)
    item = pick(_ITEMS, 2)
    advice = pick(_ADVICES, 3)
    score = 55 + digest[4] % 41
    return (
        f"今日运势 · {level}\n"
        f"幸运指数 {score}\n"
        f"幸运色 {color}，幸运物 {item}\n"
        f"{advice}"
    )


def food_text(foods: Iterable[str], rng: Optional[random.Random] = None) -> str:
    pool = [item.strip() for item in foods if isinstance(item, str) and item.strip()]
    if not pool:
        pool = list(DEFAULT_FOODS)
    chooser = rng or random
    choice = chooser.choice(pool)
    return f"今天就吃「{choice}」吧。"


def _today() -> str:
    return date.today().isoformat()


def _salt() -> str:
    try:
        return global_config.daily.salt or ""
    except Exception:
        return ""


def _foods() -> list:
    try:
        return list(global_config.daily.foods or [])
    except Exception:
        return []


@platform_command(["qq", "discord"], "今日运势", "运势")
async def handle_fortune(bot, event: MessageEvent, args: list):
    user_id = int(getattr(event, "user_id", 0) or 0)
    await event.reply(fortune_text(user_id, _today(), _salt()))


@platform_command(["qq", "discord"], "今天吃什么", "吃什么", "今日吃什么")
async def handle_eat(bot, event: MessageEvent, args: list):
    await event.reply(food_text(_foods()))
    logger.debug(f"[Daily] 已回复今天吃什么 user={getattr(event, 'user_id', '')}")
