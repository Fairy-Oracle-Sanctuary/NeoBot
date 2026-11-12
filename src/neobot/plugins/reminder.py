"""定时提醒。到点在原来的群里 @ 发起人。"""
from __future__ import annotations

import asyncio
import json
import re
import secrets
import time
from datetime import datetime, timedelta
from typing import Any, Optional
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

logger = ModuleLogger("Reminder")
SHANGHAI = ZoneInfo("Asia/Shanghai")

plugin_manifest = define_plugin(
    name="reminder",
    description="到点在群里提醒你",
    usage=(
        "/提醒 30分钟 喝水\n"
        "/提醒 明天 9:00 开会\n"
        "/提醒 每天 21:00 互道晚安\n"
        "/提醒 列表\n"
        "/提醒 删除 <编号>\n"
        "别名 /schedule"
    ),
    version="0.1.0",
)

_INDEX = "neobot:reminder:ids"
_CLAIM_TTL_SECONDS = 3 * 86400
_task: Optional[asyncio.Task] = None

_LIST = re.compile(r"^(?:列表|清单|list)$", re.IGNORECASE)
_DELETE = re.compile(r"^(?:删除|取消|del|delete|rm)\s+(\S+)$", re.IGNORECASE)
_DAILY = re.compile(r"^每天\s*(\d{1,2})[:：](\d{2})\s*(.+)$")
_EVERY = re.compile(r"^每\s*(\d+)\s*(分钟|分|小时|时)\s*(.+)$")
_ABS = re.compile(r"^(今天|明天|后天)\s*(\d{1,2})[:：](\d{2})\s*(.+)$")
_REL = re.compile(r"^(\d+)\s*(分钟|分|小时|时|天)(?:后)?\s*(.+)$")


def _limits() -> tuple[int, int, int]:
    try:
        section = global_config.reminder
        return (
            max(1, int(section.max_per_user)),
            max(1, int(section.max_per_group)),
            max(1, int(section.min_interval_minutes)),
        )
    except Exception:
        return 8, 40, 30


def _redis():
    return getattr(redis_manager, "_redis", None)


def _item_key(reminder_id: str) -> str:
    return f"neobot:reminder:item:{reminder_id}"


def _user_key(user_id: int) -> str:
    return f"neobot:reminder:user:{user_id}"


def _group_key(group_id: int) -> str:
    return f"neobot:reminder:group:{group_id}"


def _as_text(value: Any) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return "" if value is None else str(value)


def parse_reminder(text: str, now: datetime) -> dict | str:
    """解析提醒正文。成功时返回待保存的字段，失败时返回给用户的那句话。"""
    body = (text or "").strip()
    if not body or _LIST.match(body):
        return {"action": "list"}
    deleted = _DELETE.match(body)
    if deleted:
        return {"action": "delete", "id": deleted.group(1)}
    if _LIST.match(body):
        return {"action": "list"}
    if body in ("列表", "清单", "list", "LIST"):
        return {"action": "list"}

    _, _, min_minutes = _limits()
    daily = _DAILY.match(body)
    if daily:
        hour, minute = int(daily.group(1)), int(daily.group(2))
        message = daily.group(3).strip()
        if not _valid_clock(hour, minute) or not message:
            return "时间要写成 21:00 这样，后面再跟上要提醒的话。"
        when = _next_clock(now, hour, minute, day_offset=0)
        if when <= now:
            when = when + timedelta(days=1)
        return {
            "action": "create",
            "kind": "daily",
            "text": message,
            "next_at": int(when.timestamp()),
            "hour": hour,
            "minute": minute,
        }

    every = _EVERY.match(body)
    if every:
        amount = int(every.group(1))
        unit = every.group(2)
        message = every.group(3).strip()
        seconds = _to_seconds(amount, unit)
        if not message:
            return "要提醒什么呀？"
        if seconds < min_minutes * 60:
            return f"循环提醒至少要间隔 {min_minutes} 分钟哦。"
        return {
            "action": "create",
            "kind": "interval",
            "text": message,
            "next_at": int((now + timedelta(seconds=seconds)).timestamp()),
            "interval_seconds": seconds,
        }

    absolute = _ABS.match(body)
    if absolute:
        day_name, hour, minute = absolute.group(1), int(absolute.group(2)), int(absolute.group(3))
        message = absolute.group(4).strip()
        if not _valid_clock(hour, minute) or not message:
            return "时间要写成 9:00 这样，后面再跟上要提醒的话。"
        offset = {"今天": 0, "明天": 1, "后天": 2}[day_name]
        when = _next_clock(now, hour, minute, day_offset=offset)
        if when <= now:
            return "这个时间已经过了，换一个吧。"
        return {
            "action": "create",
            "kind": "once",
            "text": message,
            "next_at": int(when.timestamp()),
        }

    relative = _REL.match(body)
    if relative:
        amount = int(relative.group(1))
        unit = relative.group(2)
        message = relative.group(3).strip()
        seconds = _to_seconds(amount, unit)
        if not message:
            return "要提醒什么呀？"
        if seconds < 60:
            return "太快啦，至少 1 分钟之后再提醒我。"
        return {
            "action": "create",
            "kind": "once",
            "text": message,
            "next_at": int((now + timedelta(seconds=seconds)).timestamp()),
        }

    if body in ("列表",):
        return {"action": "list"}
    return "我没看懂。可以说 /提醒 30分钟 喝水，/提醒 明天 9:00 开会，或 /提醒 每天 21:00 互道晚安。"


def _valid_clock(hour: int, minute: int) -> bool:
    return 0 <= hour <= 23 and 0 <= minute <= 59


def _to_seconds(amount: int, unit: str) -> int:
    if unit in ("分钟", "分"):
        return amount * 60
    if unit in ("小时", "时"):
        return amount * 3600
    if unit == "天":
        return amount * 86400
    return 0


def _next_clock(now: datetime, hour: int, minute: int, day_offset: int) -> datetime:
    base = (now + timedelta(days=day_offset)).replace(hour=hour, minute=minute, second=0, microsecond=0)
    return base


def describe_when(item: dict, now: datetime) -> str:
    kind = item.get("kind")
    if kind == "daily":
        return f"每天 {int(item.get('hour', 0)):02d}:{int(item.get('minute', 0)):02d}"
    if kind == "interval":
        seconds = int(item.get("interval_seconds") or 0)
        if seconds % 3600 == 0:
            return f"每 {seconds // 3600} 小时"
        return f"每 {max(seconds // 60, 1)} 分钟"
    when = datetime.fromtimestamp(int(item["next_at"]), SHANGHAI)
    if when.date() == now.date():
        day = "今天"
    elif when.date() == (now + timedelta(days=1)).date():
        day = "明天"
    else:
        day = f"{when.month}月{when.day}日"
    return f"{day} {when.hour:02d}:{when.minute:02d}"


def format_list(items: list[dict], now: datetime) -> str:
    if not items:
        return "还没有提醒。试试 /提醒 30分钟 喝水"
    lines = ["你在这个群的提醒："]
    for item in items:
        lines.append(f"{item['id']}  {describe_when(item, now)}  {item.get('text', '')}")
    lines.append("删掉一条：/提醒 删除 编号")
    return "\n".join(lines)


def _confirm(item: dict, now: datetime) -> str:
    when = describe_when(item, now)
    return f"记下啦，{when} 我会 @你：{item['text']}\n编号 {item['id']}"


async def _load(client, reminder_id: str) -> Optional[dict]:
    raw = await client.get(_item_key(reminder_id))
    if not raw:
        return None
    try:
        data = json.loads(_as_text(raw))
    except ValueError:
        return None
    if isinstance(data, dict):
        return data
    return None


async def _set_nx(client, key: str, value: str, ex: Optional[int] = None) -> bool:
    """占住一个键。键已经存在时返回 False。"""
    try:
        if ex is None:
            result = await client.set(key, value, nx=True)
        else:
            result = await client.set(key, value, nx=True, ex=ex)
    except TypeError:
        if await client.get(key):
            return False
        if ex is None:
            await client.set(key, value)
        else:
            await client.set(key, value, ex=ex)
        return True
    return bool(result)


def _claim_key(item: dict) -> str:
    return f"neobot:reminder:fired:{item['id']}:{int(item.get('next_at') or 0)}"


async def _claim_occurrence(client, item: dict) -> bool:
    """发送前先占住这一次。崩溃后下一轮不会再发同一下。"""
    return await _set_nx(client, _claim_key(item), "1", ex=_CLAIM_TTL_SECONDS)


async def _release_occurrence(client, item: dict) -> None:
    try:
        await client.delete(_claim_key(item))
    except Exception:
        return


async def _unique_id(client) -> str:
    """分配一个还没被占用的编号。随机值撞车时换一个。"""
    for attempt in range(32):
        if attempt == 0:
            candidate = secrets.token_hex(3)
        else:
            candidate = f"{secrets.token_hex(2)}{attempt:02x}"
        if await _set_nx(client, _item_key(candidate), "{}"):
            return candidate
    candidate = f"{int(time.time() * 1000):x}{secrets.token_hex(2)}"
    await client.set(_item_key(candidate), "{}")
    return candidate


async def _save(client, item: dict) -> None:
    await client.set(_item_key(item["id"]), json.dumps(item, ensure_ascii=False))
    await client.sadd(_INDEX, item["id"])
    await client.sadd(_user_key(item["user_id"]), item["id"])
    await client.sadd(_group_key(item["group_id"]), item["id"])


async def _delete(client, item: dict) -> None:
    await client.delete(_item_key(item["id"]))
    await client.srem(_INDEX, item["id"])
    await client.srem(_user_key(item["user_id"]), item["id"])
    await client.srem(_group_key(item["group_id"]), item["id"])


async def _ids(client, key: str) -> list[str]:
    members = await client.smembers(key)
    return [_as_text(item) for item in (members or [])]


def _scheduled_today(item: dict, moment: datetime) -> datetime:
    return moment.replace(
        hour=int(item.get("hour") or 0),
        minute=int(item.get("minute") or 0),
        second=0,
        microsecond=0,
    )


async def _finish_occurrence(client, item: dict, moment: datetime) -> None:
    if item.get("kind") == "once":
        await _delete(client, item)
        return
    _advance(item, moment)
    await _save(client, item)


def _advance(item: dict, now: datetime) -> None:
    if item.get("kind") == "daily":
        when = _next_clock(now, int(item["hour"]), int(item["minute"]), 0)
        if when <= now:
            when = when + timedelta(days=1)
        item["next_at"] = int(when.timestamp())
    elif item.get("kind") == "interval":
        step = int(item.get("interval_seconds") or 3600)
        nxt = int(now.timestamp()) + step
        item["next_at"] = nxt
    item["fails"] = 0


async def reminder_tick(now: Optional[datetime] = None, sender=None) -> int:
    """发送到期提醒。返回成功发出的条数。"""
    from neobot.plugins.group_manage import is_feature_enabled

    client = _redis()
    if client is None:
        return 0
    moment = now or datetime.now(SHANGHAI)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=SHANGHAI)
    fired = 0
    for reminder_id in await _ids(client, _INDEX):
        item = await _load(client, reminder_id)
        if not item:
            await client.srem(_INDEX, reminder_id)
            continue
        if int(item.get("next_at") or 0) > int(moment.timestamp()):
            continue
        group_id = int(item["group_id"])
        if not await is_feature_enabled(group_id, "reminder"):
            continue
        due = datetime.fromtimestamp(int(item["next_at"]), SHANGHAI)
        if item.get("kind") == "daily" and due.date() < moment.date():
            today_slot = _scheduled_today(item, moment)
            if today_slot <= moment:
                # 今天的点已经过了，机器人当时不在。同一天只补一次，不把缺的几天都补上。
                item["next_at"] = int(today_slot.timestamp())
            else:
                _advance(item, moment)
                await _save(client, item)
                continue
        if not await _claim_occurrence(client, item):
            await _finish_occurrence(client, item, moment)
            continue
        try:
            if sender is None:
                await _send_with_bot(group_id, int(item["user_id"]), item.get("text") or "")
            else:
                await sender(group_id, int(item["user_id"]), item.get("text") or "")
        except Exception as exc:
            await _release_occurrence(client, item)
            logger.warning(f"[提醒] 发送失败 {reminder_id}: {type(exc).__name__}: {exc}")
            item["fails"] = int(item.get("fails") or 0) + 1
            if item.get("kind") == "once" and item["fails"] >= 3:
                await _delete(client, item)
            elif item.get("kind") == "once":
                item["next_at"] = int(moment.timestamp()) + 60
                await _save(client, item)
            else:
                _advance(item, moment)
                await _save(client, item)
            continue
        fired += 1
        await _finish_occurrence(client, item, moment)
    return fired


async def _send_with_bot(group_id: int, user_id: int, text: str) -> None:
    bots = bot_manager.get_all_bots()
    if not bots:
        raise RuntimeError("还没有连上的机器人")
    await bots[0].send_group_msg(
        group_id,
        [MessageSegment.at(user_id), MessageSegment.text(f" 到点啦：{text}")],
    )


async def _loop() -> None:
    await asyncio.sleep(2)
    while True:
        try:
            await reminder_tick()
        except Exception as exc:
            logger.error(f"[提醒] 轮询失败: {type(exc).__name__}: {exc}")
        await asyncio.sleep(20)


@on_startup
async def start_reminder() -> None:
    global _task
    if _task is not None and not _task.done():
        return
    _task = asyncio.create_task(_loop())
    logger.info("[提醒] 已开始守着提醒本子")


@on_shutdown
async def stop_reminder() -> None:
    global _task
    if _task is not None:
        _task.cancel()
        _task = None


@platform_command(["qq"], "提醒", "schedule")
async def handle_reminder(bot, event, args):
    group_id = getattr(event, "group_id", None)
    user_id = getattr(event, "user_id", None)
    if not group_id:
        await event.reply("提醒要在群里约，我才能到时候@你。")
        return
    from neobot.plugins.group_manage import is_feature_enabled
    if not await is_feature_enabled(group_id, "reminder"):
        await event.reply("这个群的提醒被收起来了，让管理员用 /群管 开 定时提醒。")
        return
    client = _redis()
    if client is None:
        await event.reply("提醒本子暂时找不到，等一下再试吧。")
        return

    now = datetime.now(SHANGHAI)
    parsed = parse_reminder(" ".join(args), now)
    if isinstance(parsed, str):
        await event.reply(parsed)
        return
    action = parsed.get("action")
    if action == "list":
        owned = []
        for reminder_id in await _ids(client, _user_key(int(user_id))):
            item = await _load(client, reminder_id)
            if item and int(item.get("group_id") or 0) == int(group_id):
                owned.append(item)
        owned.sort(key=lambda item: int(item.get("next_at") or 0))
        await event.reply(format_list(owned, now))
        return
    if action == "delete":
        item = await _load(client, parsed["id"])
        if not item or int(item.get("user_id") or 0) != int(user_id) or int(item.get("group_id") or 0) != int(group_id):
            await event.reply("没有这条提醒，或它不是你在这个群约的。")
            return
        await _delete(client, item)
        await event.reply(f"删掉啦：{parsed['id']}")
        return

    per_user, per_group, _min_interval = _limits()
    user_count = int(await client.scard(_user_key(int(user_id))) or 0)
    group_count = int(await client.scard(_group_key(int(group_id))) or 0)
    if user_count >= per_user:
        await event.reply(f"你的提醒已经排满啦（最多 {per_user} 条），先删掉一条再约吧。")
        return
    if group_count >= per_group:
        await event.reply("这个群的提醒本子写满了。")
        return
    reminder_id = await _unique_id(client)
    item = {
        "id": reminder_id,
        "group_id": int(group_id),
        "user_id": int(user_id),
        "text": parsed["text"],
        "kind": parsed["kind"],
        "next_at": parsed["next_at"],
        "fails": 0,
    }
    if "hour" in parsed:
        item["hour"] = parsed["hour"]
        item["minute"] = parsed["minute"]
    if "interval_seconds" in parsed:
        item["interval_seconds"] = parsed["interval_seconds"]
    await _save(client, item)
    await event.reply(_confirm(item, now))
