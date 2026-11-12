"""群投票。结果记在 Redis 里，重启还在，到点自动过期。"""
from __future__ import annotations

import json
import time
import uuid
from typing import Any, Dict, List, Optional, Sequence, Tuple

from neobot.plugin_api import (
    MessageEvent,
    ModuleLogger,
    define_plugin,
    global_config,
    platform_command,
    redis_manager,
)

logger = ModuleLogger("Poll")

plugin_manifest = define_plugin(
    name="poll",
    description="在群里发起一个小投票",
    usage=(
        "/投票 <题目> <选项1> <选项2> ... - 发起投票，也可用｜分开\n"
        "/投 1 - 给最近一场投票的第 1 项\n"
        "/投 <编号> <选项> - 群里有多场时指定是哪一场\n"
        "/投票 结果 - 看票数\n"
        "/投票 结束 - 发起人或管理员结束"
    ),
    version="0.1.0",
)

_KEY = "neobot:poll:v1:{group_id}"


def parse_poll_create(text: str, max_options: int = 8) -> Tuple[str, List[str]]:
    raw = (text or "").strip()
    if "｜" in raw or "|" in raw:
        parts = [item.strip() for item in raw.replace("｜", "|").split("|") if item.strip()]
    else:
        parts = [item.strip() for item in raw.split() if item.strip()]
    if len(parts) < 3:
        raise ValueError("usage")
    title, options = parts[0], parts[1:]
    if len(title) > 40 or any(len(item) > 20 or not item for item in options):
        raise ValueError("length")
    if len(options) > max_options:
        raise ValueError("too_many")
    if len(set(options)) != len(options):
        raise ValueError("duplicate")
    return title, options


def active_polls(polls: Sequence[Dict[str, Any]], now: float) -> List[Dict[str, Any]]:
    kept = []
    for poll in polls:
        if poll.get("closed"):
            continue
        if float(poll.get("expires_at") or 0) <= now:
            continue
        kept.append(poll)
    return kept


def tally(option_count: int, votes: Dict[str, int]) -> List[int]:
    counts = [0] * option_count
    for choice in votes.values():
        index = int(choice)
        if 0 <= index < option_count:
            counts[index] += 1
    return counts


def cast_vote(poll: Dict[str, Any], user_id: str, option_index: int) -> str:
    votes = poll.setdefault("votes", {})
    if user_id in votes:
        return "already"
    options = poll.get("options") or []
    if not 0 <= option_index < len(options):
        return "range"
    votes[user_id] = option_index
    return "ok"


def can_close(poll: Dict[str, Any], user_id: str, is_admin: bool) -> bool:
    return is_admin or str(poll.get("creator")) == str(user_id)


def format_results(poll: Dict[str, Any], index: Optional[int] = None) -> str:
    options = list(poll.get("options") or [])
    counts = tally(len(options), {str(k): int(v) for k, v in (poll.get("votes") or {}).items()})
    prefix = f"{index}. " if index else ""
    lines = [f"{prefix}「{poll.get('title', '')}」"]
    for number, (name, count) in enumerate(zip(options, counts), start=1):
        lines.append(f"{number}. {name}  {count} 票")
    lines.append(f"共 {sum(counts)} 票")
    return "\n".join(lines)


def new_poll(title: str, options: Sequence[str], creator: str, now: float, ttl_seconds: int) -> Dict[str, Any]:
    return {
        "id": uuid.uuid4().hex[:8],
        "title": title,
        "options": list(options),
        "creator": str(creator),
        "votes": {},
        "created_at": now,
        "expires_at": now + ttl_seconds,
        "closed": False,
    }


def _settings() -> Tuple[int, int, int]:
    try:
        cfg = global_config.poll
        return int(cfg.max_concurrent), int(cfg.ttl_hours), int(cfg.max_options)
    except Exception:
        return 3, 24, 8


def _key(group_id) -> str:
    return _KEY.format(group_id=group_id)


async def _load(group_id) -> List[Dict[str, Any]]:
    raw = await redis_manager.get(_key(group_id))
    if not raw:
        return []
    data = json.loads(raw)
    polls = data.get("polls") if isinstance(data, dict) else None
    return list(polls or [])


async def _save(group_id, polls: List[Dict[str, Any]], ttl_hours: int) -> None:
    payload = json.dumps({"polls": polls}, ensure_ascii=False)
    await redis_manager.set(_key(group_id), payload, ex=max(ttl_hours, 1) * 3600 + 3600)


def _require_group(event) -> Optional[int]:
    group_id = getattr(event, "group_id", None)
    if not group_id:
        return None
    return int(group_id)


async def _is_admin(bot, event) -> bool:
    try:
        member = await bot.get_group_member_info(event.group_id, event.user_id, no_cache=True)
    except Exception:
        return False
    return getattr(member, "role", "") in ("owner", "admin")


@platform_command(["qq", "discord"], "投票")
async def handle_poll(bot, event: MessageEvent, args: list):
    group_id = _require_group(event)
    if not group_id:
        await event.reply("投票只能在群里用。")
        return
    max_concurrent, ttl_hours, max_options = _settings()
    head = args[0] if args else ""
    try:
        polls = await _load(group_id)
    except Exception as exc:
        logger.error(f"[投票] 读取失败: {type(exc).__name__}: {exc}")
        await event.reply("投票本子暂时打不开，请稍后再试。")
        return
    now = time.time()
    opened = active_polls(polls, now)

    if head in ("结果", "查看"):
        if opened:
            text = "\n\n".join(format_results(poll, index=i) for i, poll in enumerate(opened, start=1))
        else:
            closed = [item for item in polls if item.get("closed")]
            if not closed:
                await event.reply("现在没有进行中的投票。")
                return
            text = "最近一场已经结束：\n" + format_results(closed[-1])
        await event.reply(text)
        return

    if head == "结束":
        if not opened:
            await event.reply("现在没有进行中的投票。")
            return
        target = opened[-1]
        if len(args) >= 2 and args[1].isdigit():
            index = int(args[1]) - 1
            if not 0 <= index < len(opened):
                await event.reply(f"没有第 {args[1]} 场投票。")
                return
            target = opened[index]
        user_id = str(getattr(event, "user_id", ""))
        if not can_close(target, user_id, await _is_admin(bot, event)):
            await event.reply("只有发起人或管理员能结束这场投票。")
            return
        target["closed"] = True
        try:
            await _save(group_id, polls, ttl_hours)
        except Exception as exc:
            logger.error(f"[投票] 保存失败: {type(exc).__name__}: {exc}")
            await event.reply("结束失败了，请稍后再试。")
            return
        await event.reply("投票结束啦。\n" + format_results(target))
        return

    if not args:
        await event.reply("用法：/投票 午饭 火锅 烧烤\n或：/投票 午饭｜火锅｜烧烤")
        return
    try:
        title, options = parse_poll_create(" ".join(args), max_options=max_options)
    except ValueError as exc:
        code = str(exc)
        if code == "too_many":
            await event.reply(f"选项有点多，最多 {max_options} 个。")
        elif code == "duplicate":
            await event.reply("有重复的选项，换一个名字吧。")
        elif code == "length":
            await event.reply("题目请控制在 40 字内，每个选项 20 字内。")
        else:
            await event.reply("用法：/投票 午饭 火锅 烧烤")
        return
    if len(opened) >= max_concurrent:
        await event.reply(f"这个群已经有 {max_concurrent} 场投票了，先结束一场吧。")
        return
    poll = new_poll(title, options, str(getattr(event, "user_id", "")), now, ttl_hours * 3600)
    polls.append(poll)
    try:
        await _save(group_id, polls, ttl_hours)
    except Exception as exc:
        logger.error(f"[投票] 保存失败: {type(exc).__name__}: {exc}")
        await event.reply("投票没能记下来，请稍后再试。")
        return
    lines = [f"投票开始了：「{title}」"]
    lines.extend(f"{i}. {name}" for i, name in enumerate(options, start=1))
    lines.append(f"回复 /投 1 就记一票。{ttl_hours} 小时后自动结束。")
    await event.reply("\n".join(lines))


@platform_command(["qq", "discord"], "投")
async def handle_vote(bot, event: MessageEvent, args: list):
    group_id = _require_group(event)
    if not group_id:
        await event.reply("投票只能在群里用。")
        return
    _, ttl_hours, _ = _settings()
    if not args or not all(item.isdigit() for item in args) or len(args) > 2:
        await event.reply("用法：/投 1    有多场时：/投 2 1")
        return
    try:
        polls = await _load(group_id)
    except Exception as exc:
        logger.error(f"[投票] 读取失败: {type(exc).__name__}: {exc}")
        await event.reply("投票本子暂时打不开，请稍后再试。")
        return
    opened = active_polls(polls, time.time())
    if not opened:
        await event.reply("现在没有进行中的投票。")
        return
    if len(args) == 1:
        if len(opened) > 1:
            await event.reply("现在有多场投票，请用 /投 编号 选项，例如 /投 1 2。")
            return
        poll_index, option_index = 0, int(args[0]) - 1
    else:
        poll_index, option_index = int(args[0]) - 1, int(args[1]) - 1
    if not 0 <= poll_index < len(opened):
        await event.reply("没有这场投票。")
        return
    poll = opened[poll_index]
    status = cast_vote(poll, str(getattr(event, "user_id", "")), option_index)
    if status == "already":
        await event.reply("你已经投过啦，一个人一票。")
        return
    if status == "range":
        await event.reply("没有这个选项。")
        return
    try:
        await _save(group_id, polls, ttl_hours)
    except Exception as exc:
        logger.error(f"[投票] 保存失败: {type(exc).__name__}: {exc}")
        await event.reply("这一票没记上，请稍后再试。")
        return
    chosen = poll["options"][option_index]
    await event.reply(f"记下了，你投了「{chosen}」。")
