"""话痨榜。只记每个群每天每人说了几句，不记内容。"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

from neobot.plugin_api import (
    ModuleLogger,
    define_plugin,
    global_config,
    platform_command,
    platform_message,
    redis_manager,
)

logger = ModuleLogger("Chatty")
SHANGHAI = ZoneInfo("Asia/Shanghai")

plugin_manifest = define_plugin(
    name="chatty",
    description="看看谁今天话最多，只记条数",
    usage=(
        "/今日话痨 - 今天这个群的前 10 名\n"
        "/本周话痨 - 最近 7 天的前 10 名\n"
        "/我的发言 - 看看自己今天说了几句"
    ),
    version="0.1.0",
)


def _settings() -> tuple[int, int]:
    try:
        section = global_config.chatty
        return max(1, int(section.top_n)), max(7, int(section.retain_days))
    except Exception:
        return 10, 8


def _redis():
    return getattr(redis_manager, "_redis", None)


def today(now: Optional[datetime] = None) -> datetime:
    moment = now or datetime.now(SHANGHAI)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=SHANGHAI)
    return moment.astimezone(SHANGHAI)


def day_key(group_id: int, day: datetime) -> str:
    return f"neobot:chatty:{group_id}:{day.strftime('%Y%m%d')}"


def recent_days(now: Optional[datetime] = None, count: int = 7) -> list[datetime]:
    start = today(now)
    return [start - timedelta(days=offset) for offset in range(count)]


def rank_counts(counts: dict, top_n: int = 10) -> list[tuple[str, int]]:
    rows = []
    for user_id, raw in (counts or {}).items():
        try:
            value = int(raw)
        except (TypeError, ValueError):
            continue
        if value > 0:
            rows.append((str(user_id), value))
    rows.sort(key=lambda item: (-item[1], item[0]))
    return rows[:top_n]


def format_board(title: str, rows: list[tuple[str, str, int]]) -> str:
    if not rows:
        return f"{title}\n还没有发言记录。"
    lines = [title]
    for index, (_user_id, name, count) in enumerate(rows, start=1):
        lines.append(f"{index}. {name} · {count} 句")
    return "\n".join(lines)


async def _enabled(group_id) -> bool:
    from neobot.plugins.group_manage import is_feature_enabled
    return await is_feature_enabled(group_id, "chatty")


async def _hgetall(client, key: str) -> dict:
    data = await client.hgetall(key)
    if not data:
        return {}
    cleaned = {}
    for field, value in data.items():
        name = field.decode() if isinstance(field, bytes) else str(field)
        raw = value.decode() if isinstance(value, bytes) else value
        cleaned[name] = raw
    return cleaned


async def _collect(client, group_id: int, days: list[datetime]) -> dict[str, int]:
    totals: dict[str, int] = {}
    for day in days:
        for user_id, raw in (await _hgetall(client, day_key(group_id, day))).items():
            try:
                totals[user_id] = totals.get(user_id, 0) + int(raw)
            except (TypeError, ValueError):
                continue
    return totals


async def _name(bot, group_id: int, user_id: str) -> str:
    try:
        member = await bot.get_group_member_info(int(group_id), int(user_id))
    except Exception:
        return user_id
    card = getattr(member, "card", "") or ""
    nickname = getattr(member, "nickname", "") or ""
    return card or nickname or user_id


@platform_message(["qq"], priority=1, block=False)
async def count_message(event):
    group_id = getattr(event, "group_id", None)
    user_id = getattr(event, "user_id", None)
    if not group_id or not user_id:
        return
    if user_id == getattr(event, "self_id", None):
        return
    if not await _enabled(group_id):
        return
    client = _redis()
    if client is None:
        return
    _top, retain_days = _settings()
    key = day_key(int(group_id), today())
    try:
        await client.hincrby(key, str(user_id), 1)
        await client.expire(key, retain_days * 86400)
    except Exception as exc:
        logger.debug(f"[话痨] 计数失败: {type(exc).__name__}")


async def _reply_board(bot, event, days: int, title: str) -> None:
    group_id = getattr(event, "group_id", None)
    if not group_id:
        await event.reply("话痨榜只在群里看。")
        return
    if not await _enabled(group_id):
        await event.reply("这个群关掉了话痨榜。")
        return
    client = _redis()
    if client is None:
        await event.reply("计数本子暂时打不开，等一下再看吧。")
        return
    top_n, _retain = _settings()
    totals = await _collect(client, int(group_id), recent_days(count=days))
    ranked = rank_counts(totals, top_n)
    rows = []
    for user_id, count in ranked:
        rows.append((user_id, await _name(bot, int(group_id), user_id), count))
    await event.reply(format_board(title, rows))


@platform_command(["qq"], "今日话痨")
async def handle_today(bot, event, args):
    await _reply_board(bot, event, 1, "今日话痨 TOP")


@platform_command(["qq"], "本周话痨")
async def handle_week(bot, event, args):
    await _reply_board(bot, event, 7, "本周话痨 TOP")


@platform_command(["qq"], "我的发言")
async def handle_mine(bot, event, args):
    group_id = getattr(event, "group_id", None)
    user_id = getattr(event, "user_id", None)
    if not group_id:
        await event.reply("到群里再问我呀。")
        return
    if not await _enabled(group_id):
        await event.reply("这个群关掉了话痨榜。")
        return
    client = _redis()
    if client is None:
        await event.reply("计数本子暂时打不开，等一下再看吧。")
        return
    totals = await _collect(client, int(group_id), recent_days(count=1))
    mine = totals.get(str(user_id), 0)
    ordered = rank_counts(totals, top_n=len(totals) or 1)
    place = next((index for index, (uid, _count) in enumerate(ordered, start=1) if uid == str(user_id)), None)
    if place is None:
        await event.reply("你今天还没说话呢。")
        return
    await event.reply(f"你今天说了 {mine} 句，排第 {place}。")
