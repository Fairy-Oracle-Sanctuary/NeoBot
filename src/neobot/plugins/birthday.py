"""群里的生日。只记月和日，不记年份，也不算年龄。"""
from __future__ import annotations

import asyncio
import hashlib
import re
from datetime import date, datetime
from typing import Optional
from zoneinfo import ZoneInfo

from neobot.plugin_api import (
    MessageSegment,
    ModuleLogger,
    bot_manager,
    define_plugin,
    global_config,
    on_shutdown,
    on_startup,
    platform_command,
    redis_manager,
)

logger = ModuleLogger("Birthday")
SHANGHAI = ZoneInfo("Asia/Shanghai")

plugin_manifest = define_plugin(
    name="birthday",
    description="记住这个群里的生日，当天送一句祝福",
    usage=(
        "/登记生日 MM-DD - 只记月和日，例如 03-14\n"
        "/删除生日\n"
        "/生日列表 - 这个群接下来 30 天的生日"
    ),
    version="0.1.0",
)

_GROUPS = "neobot:birthday:groups"
_task: Optional[asyncio.Task] = None
_MMDD = re.compile(r"^(\d{1,2})-(\d{1,2})$")
_WISHES = (
    "生日快乐，今天也闪闪发光。",
    "生日快乐！记得吃点甜的。",
    "生日快乐，愿今天的风都是软的。",
    "生日快乐，被喜欢着的一天开始啦。",
)


def _settings() -> tuple[int, int, int]:
    try:
        section = global_config.birthday
        hour = min(23, max(0, int(section.hour)))
        window = min(12, max(1, int(section.window_hours)))
        lookahead = min(366, max(1, int(section.lookahead_days)))
        return hour, window, lookahead
    except Exception:
        return 9, 3, 30


def _redis():
    return getattr(redis_manager, "_redis", None)


def _group_key(group_id: int) -> str:
    return f"neobot:birthday:{group_id}"


def _sent_key(day: date, group_id: int, user_id: int) -> str:
    return f"neobot:birthday:sent:{day.strftime('%Y%m%d')}:{group_id}:{user_id}"


def parse_birthday(text: str) -> str | None:
    """只接受 MM-DD。带年份的写法返回 None，调用方另说一句。"""
    raw = (text or "").strip()
    if re.search(r"\d{4}", raw):
        return None
    matched = _MMDD.fullmatch(raw)
    if not matched:
        return None
    month, day = int(matched.group(1)), int(matched.group(2))
    if month == 2 and day == 29:
        return "02-29"
    try:
        date(2000, month, day)
    except ValueError:
        return None
    return f"{month:02d}-{day:02d}"


def contains_year(text: str) -> bool:
    return bool(re.search(r"\d{4}", (text or "")))


def celebration_date(mmdd: str, year: int) -> Optional[date]:
    month, day = (int(part) for part in mmdd.split("-", 1))
    try:
        return date(year, month, day)
    except ValueError:
        if month == 2 and day == 29:
            return date(year, 2, 28)
        return None


def upcoming(records: list[tuple[str, str]], today: date, days: int = 30) -> list[tuple[int, str, str]]:
    """返回 (还有几天, user_id, MM-DD)，只含窗口内的。"""
    found = []
    for user_id, mmdd in records:
        this_year = celebration_date(mmdd, today.year)
        if this_year is None:
            continue
        if this_year < today:
            this_year = celebration_date(mmdd, today.year + 1)
        if this_year is None:
            continue
        delta = (this_year - today).days
        if 0 <= delta <= days:
            found.append((delta, str(user_id), mmdd))
    found.sort()
    return found


def wish_text(user_id: int, day: date) -> str:
    digest = hashlib.sha256(f"{user_id}:{day.isoformat()}".encode("utf-8")).digest()
    return _WISHES[digest[0] % len(_WISHES)]


def is_birthday_today(mmdd: str, today: date) -> bool:
    target = celebration_date(mmdd, today.year)
    return target == today


def in_send_window(now: datetime) -> bool:
    hour, window, _lookahead = _settings()
    moment = now.astimezone(SHANGHAI)
    return hour <= moment.hour < hour + window


def format_upcoming(rows: list[tuple[int, str, str]], names: dict[str, str]) -> str:
    if not rows:
        return "接下来 30 天没有生日，安静地可爱着。"
    lines = ["接下来的生日："]
    for delta, user_id, mmdd in rows:
        name = names.get(user_id) or user_id
        when = "就是今天" if delta == 0 else f"{delta} 天后"
        lines.append(f"{name}  {mmdd}  {when}")
    return "\n".join(lines)


async def _hgetall(client, key: str) -> dict[str, str]:
    data = await client.hgetall(key)
    cleaned = {}
    for field, value in (data or {}).items():
        name = field.decode() if isinstance(field, bytes) else str(field)
        raw = value.decode() if isinstance(value, bytes) else str(value)
        cleaned[name] = raw
    return cleaned


async def birthday_tick(now: Optional[datetime] = None, sender=None, member_present=None) -> int:
    """到点给还在群里的寿星一句祝福。返回发出的条数。"""
    from neobot.plugins.group_manage import is_feature_enabled

    client = _redis()
    if client is None:
        return 0
    moment = now or datetime.now(SHANGHAI)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=SHANGHAI)
    moment = moment.astimezone(SHANGHAI)
    if not in_send_window(moment):
        return 0
    today = moment.date()
    groups = await client.smembers(_GROUPS)
    sent = 0
    for group_raw in groups or []:
        group_id = int(group_raw.decode() if isinstance(group_raw, bytes) else group_raw)
        if not await is_feature_enabled(group_id, "birthday"):
            continue
        records = await _hgetall(client, _group_key(group_id))
        for user_raw, mmdd in records.items():
            if not is_birthday_today(mmdd, today):
                continue
            user_id = int(user_raw)
            marker = _sent_key(today, group_id, user_id)
            if await client.get(marker):
                continue
            try:
                if member_present is None:
                    present = await _member_in_group(group_id, user_id)
                else:
                    present = await member_present(group_id, user_id)
            except Exception:
                present = False
            if not present:
                continue
            text = wish_text(user_id, today)
            try:
                if sender is None:
                    await _send_with_bot(group_id, user_id, text)
                else:
                    await sender(group_id, user_id, text)
            except Exception as exc:
                logger.warning(f"[生日] 发送失败: {type(exc).__name__}: {exc}")
                continue
            await client.set(marker, "1", ex=3 * 86400)
            sent += 1
    return sent


async def _member_in_group(group_id: int, user_id: int) -> bool:
    bots = bot_manager.get_all_bots()
    if not bots:
        return False
    try:
        info = await bots[0].get_group_member_info(group_id, user_id)
    except Exception:
        return False
    return info is not None


async def _send_with_bot(group_id: int, user_id: int, text: str) -> None:
    bots = bot_manager.get_all_bots()
    if not bots:
        raise RuntimeError("还没有连上的机器人")
    await bots[0].send_group_msg(
        group_id,
        [MessageSegment.at(user_id), MessageSegment.text(f" {text}")],
    )


async def _loop() -> None:
    await asyncio.sleep(5)
    while True:
        try:
            await birthday_tick()
        except Exception as exc:
            logger.error(f"[生日] 轮询失败: {type(exc).__name__}: {exc}")
        await asyncio.sleep(60)


@on_startup
async def start_birthday() -> None:
    global _task
    if _task is not None and not _task.done():
        return
    _task = asyncio.create_task(_loop())
    logger.info("[生日] 已开始记着大家的日子")


@on_shutdown
async def stop_birthday() -> None:
    global _task
    if _task is not None:
        _task.cancel()
        _task = None


async def _require_group(event):
    group_id = getattr(event, "group_id", None)
    if not group_id:
        await event.reply("生日要在群里登记，我才知道去哪个群说祝福。")
        return None
    from neobot.plugins.group_manage import is_feature_enabled
    if not await is_feature_enabled(group_id, "birthday"):
        await event.reply("这个群的生日祝福被收起来了。")
        return None
    client = _redis()
    if client is None:
        await event.reply("生日本子暂时找不到，等一下再试吧。")
        return None
    return client


@platform_command(["qq"], "登记生日")
async def handle_register(bot, event, args):
    client = await _require_group(event)
    if client is None:
        return
    text = " ".join(args).strip()
    if contains_year(text):
        await event.reply("只要月和日就好，比如 03-14，不用告诉我年份。")
        return
    mmdd = parse_birthday(text)
    if not mmdd:
        await event.reply("写成 /登记生日 03-14 这样哦。")
        return
    group_id = int(event.group_id)
    user_id = int(event.user_id)
    await client.hset(_group_key(group_id), str(user_id), mmdd)
    await client.sadd(_GROUPS, str(group_id))
    await event.reply(f"记下啦，每年 {mmdd} 我会在这个群跟你说生日快乐。")


@platform_command(["qq"], "删除生日")
async def handle_delete(bot, event, args):
    client = await _require_group(event)
    if client is None:
        return
    group_id = int(event.group_id)
    removed = await client.hdel(_group_key(group_id), str(int(event.user_id)))
    if not removed:
        await event.reply("你在这个群还没登记生日。")
        return
    left = await client.hlen(_group_key(group_id))
    if not left:
        await client.srem(_GROUPS, str(group_id))
    await event.reply("这个群里的生日登记删掉啦。")


@platform_command(["qq"], "生日列表")
async def handle_list(bot, event, args):
    client = await _require_group(event)
    if client is None:
        return
    group_id = int(event.group_id)
    records = await _hgetall(client, _group_key(group_id))
    _hour, _window, lookahead = _settings()
    rows = upcoming(list(records.items()), datetime.now(SHANGHAI).date(), lookahead)
    names = {}
    for _delta, user_id, _mmdd in rows:
        try:
            member = await bot.get_group_member_info(group_id, int(user_id))
            names[user_id] = getattr(member, "card", "") or getattr(member, "nickname", "") or user_id
        except Exception:
            names[user_id] = user_id
    await event.reply(format_upcoming(rows, names))
