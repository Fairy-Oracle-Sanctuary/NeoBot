"""今日 CP：同一天、同一个群、同一个人，配对固定。"""
from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Iterable, Optional
from zoneinfo import ZoneInfo

from neobot.plugin_api import (
    MessageEvent,
    MessageSegment,
    ModuleLogger,
    define_plugin,
    global_config,
    platform_command,
    redis_manager,
)

from .mentions import mentioned_user_ids

logger = ModuleLogger("DailyCp")

plugin_manifest = define_plugin(
    name="daily_cp",
    description="今天在本群里配对一位小伙伴",
    usage=(
        "/今日CP - 看你今天的配对，同一天不会变\n"
        "/今日CP @人 - 看 TA 今天的配对\n"
        "/CP退出 - 不再被抽到\n"
        "/CP加入 - 重新加入配对"
    ),
    version="0.1.0",
)

_SHANGHAI = ZoneInfo("Asia/Shanghai")
_OPTOUT = "neobot:cp:optout:{group_id}"


def shanghai_day(now: Optional[datetime] = None) -> str:
    moment = now or datetime.now(_SHANGHAI)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=_SHANGHAI)
    return moment.astimezone(_SHANGHAI).date().isoformat()


def pick_partner(
    user_id: int,
    member_ids: Iterable[int],
    opted_out: Iterable[int],
    day: str,
    group_id: int,
    salt: str = "",
) -> Optional[int]:
    """按日期、群、用户确定一位同伴。退出的人不会被抽到，也不会抽到自己。"""
    blocked = {int(item) for item in opted_out}
    if int(user_id) in blocked:
        return None
    pool = sorted({int(item) for item in member_ids if int(item) != int(user_id) and int(item) not in blocked})
    if not pool:
        return None
    digest = hashlib.sha256(f"{salt}|{day}|{group_id}|{user_id}".encode("utf-8")).digest()
    return pool[int.from_bytes(digest[:8], "big") % len(pool)]


def _salt() -> str:
    try:
        return global_config.daily_cp.salt or ""
    except Exception:
        return ""


def _optout_key(group_id: int) -> str:
    return _OPTOUT.format(group_id=group_id)


async def _opted_out(group_id: int) -> set[int]:
    members = await redis_manager.redis.smembers(_optout_key(group_id))
    return {int(item) for item in members or [] if str(item).isdigit()}


async def _member_ids(bot, group_id: int, self_id: int) -> list[int]:
    members = await bot.get_group_member_list(group_id)
    found = []
    for member in members or []:
        user_id = int(getattr(member, "user_id", 0) or 0)
        if user_id and user_id != int(self_id):
            found.append(user_id)
    return found


def _reply_pair(who: str, partner_id: int) -> list:
    return [
        MessageSegment.text(f"{who}"),
        MessageSegment.at(partner_id),
        MessageSegment.text("\n同一天再看还是这位，明天会换。"),
    ]


@platform_command(["qq", "discord"], "今日CP")
async def handle_cp(bot, event: MessageEvent, args: list):
    group_id = getattr(event, "group_id", None)
    if not group_id:
        await event.reply("今日CP 只能在群里用。")
        return
    caller = int(getattr(event, "user_id", 0) or 0)
    mentions = mentioned_user_ids(getattr(event, "message", None))
    target = mentions[0] if mentions else caller
    try:
        opted = await _opted_out(int(group_id))
        members = await _member_ids(bot, int(group_id), int(getattr(event, "self_id", 0) or getattr(bot, "self_id", 0) or 0))
    except Exception as exc:
        logger.error(f"[今日CP] 读取失败: {type(exc).__name__}: {exc}")
        await event.reply("没能拿到群成员，稍后再试。")
        return
    if target not in members and target != caller:
        await event.reply("对方不在这个群里。")
        return
    if target in opted:
        if target == caller:
            await event.reply("你已经退出今日CP了。想回来的话用 /CP加入。")
        else:
            await event.reply("TA 退出了今日CP，没有配对。")
        return
    partner = pick_partner(target, members, opted, shanghai_day(), int(group_id), _salt())
    if partner is None:
        await event.reply("群里暂时没有可以配对的小伙伴。")
        return
    who = "你今天的 CP 是 " if target == caller else "TA 今天的 CP 是 "
    await event.reply(_reply_pair(who, partner))


@platform_command(["qq", "discord"], "CP退出")
async def handle_leave(bot, event: MessageEvent, args: list):
    group_id = getattr(event, "group_id", None)
    if not group_id:
        await event.reply("这个指令只能在群里用。")
        return
    try:
        await redis_manager.redis.sadd(_optout_key(int(group_id)), str(getattr(event, "user_id", "")))
    except Exception as exc:
        logger.error(f"[今日CP] 退出失败: {type(exc).__name__}: {exc}")
        await event.reply("没能记下来，请稍后再试。")
        return
    await event.reply("好，之后不会再抽到你。想回来用 /CP加入。")


@platform_command(["qq", "discord"], "CP加入")
async def handle_join(bot, event: MessageEvent, args: list):
    group_id = getattr(event, "group_id", None)
    if not group_id:
        await event.reply("这个指令只能在群里用。")
        return
    try:
        await redis_manager.redis.srem(_optout_key(int(group_id)), str(getattr(event, "user_id", "")))
    except Exception as exc:
        logger.error(f"[今日CP] 加入失败: {type(exc).__name__}: {exc}")
        await event.reply("没能记下来，请稍后再试。")
        return
    await event.reply("欢迎回来，今天起又可以被抽到啦。")
