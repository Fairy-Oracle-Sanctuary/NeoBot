"""本群公开的兽设档案。只存文字，没有私密字段。"""
from __future__ import annotations

import json
from typing import Dict, Optional

from neobot.plugin_api import (
    MessageEvent,
    ModuleLogger,
    define_plugin,
    platform_command,
    redis_manager,
)

from .mentions import mentioned_user_ids

logger = ModuleLogger("Fursona")

plugin_manifest = define_plugin(
    name="fursona",
    description="在本群登记一份公开兽设",
    usage=(
        "/登记兽设 名字｜物种｜毛色｜一句简介 - 登记或更新，本群可见\n"
        "/兽设 - 看自己的\n"
        "/兽设 @人 - 看同一群里别人的\n"
        "/删除兽设 - 删掉自己的"
    ),
    version="0.1.0",
)

_KEY = "neobot:fursona:{group_id}"
_LIMITS = {"name": 20, "species": 20, "colors": 30, "bio": 80}


def parse_profile(text: str) -> Dict[str, str]:
    raw = (text or "").strip().replace("\n", " ")
    if "｜" in raw or "|" in raw:
        parts = [item.strip() for item in raw.replace("｜", "|").split("|")]
    else:
        parts = raw.split(maxsplit=3)
    if len(parts) < 4 or any(not item.strip() for item in parts[:4]):
        raise ValueError("usage")
    profile = {
        "name": parts[0].strip(),
        "species": parts[1].strip(),
        "colors": parts[2].strip(),
        "bio": parts[3].strip(),
    }
    for field, limit in _LIMITS.items():
        if len(profile[field]) > limit:
            raise ValueError(field)
    return profile


def format_profile(profile: Dict[str, str]) -> str:
    return (
        f"{profile.get('name', '')}的兽设\n"
        f"物种：{profile.get('species', '')}\n"
        f"毛色：{profile.get('colors', '')}\n"
        f"简介：{profile.get('bio', '')}"
    )


def _key(group_id: int) -> str:
    return _KEY.format(group_id=group_id)


def _usage() -> str:
    return (
        "登记格式：/登记兽设 名字｜物种｜毛色｜一句简介\n"
        "例如：/登记兽设 小桃｜狐狸｜蜜糖棕｜喜欢晒太阳\n"
        "这四项都会在本群公开显示，目前只登记文字。"
    )


async def _load(group_id: int, user_id: int) -> Optional[Dict[str, str]]:
    raw = await redis_manager.redis.hget(_key(group_id), str(user_id))
    if not raw:
        return None
    data = json.loads(raw)
    if not isinstance(data, dict):
        return None
    return {key: str(data.get(key, "")) for key in ("name", "species", "colors", "bio")}


@platform_command(["qq", "discord"], "登记兽设")
async def handle_register(bot, event: MessageEvent, args: list):
    group_id = getattr(event, "group_id", None)
    if not group_id:
        await event.reply("请在群里登记，这样同群的小伙伴才能看到。")
        return
    if not args:
        await event.reply(_usage())
        return
    try:
        profile = parse_profile(" ".join(args))
    except ValueError as exc:
        code = str(exc)
        if code in _LIMITS:
            await event.reply(f"有点长了，{_LIMITS[code]} 个字以内就好。")
        else:
            await event.reply(_usage())
        return
    try:
        await redis_manager.redis.hset(
            _key(int(group_id)),
            str(getattr(event, "user_id", "")),
            json.dumps(profile, ensure_ascii=False),
        )
    except Exception as exc:
        logger.error(f"[兽设] 保存失败: {type(exc).__name__}: {exc}")
        await event.reply("没能记下来，请稍后再试。")
        return
    await event.reply("记下啦。\n" + format_profile(profile))


@platform_command(["qq", "discord"], "兽设")
async def handle_view(bot, event: MessageEvent, args: list):
    group_id = getattr(event, "group_id", None)
    if not group_id:
        await event.reply("兽设档案是按群分开的，请在群里查看。")
        return
    mentions = mentioned_user_ids(getattr(event, "message", None))
    target = mentions[0] if mentions else int(getattr(event, "user_id", 0) or 0)
    try:
        profile = await _load(int(group_id), target)
    except Exception as exc:
        logger.error(f"[兽设] 读取失败: {type(exc).__name__}: {exc}")
        await event.reply("档案暂时打不开，请稍后再试。")
        return
    if not profile:
        if mentions:
            await event.reply("TA 还没有在本群登记兽设。")
        else:
            await event.reply("你还没有在本群登记。\n" + _usage())
        return
    await event.reply(format_profile(profile))


@platform_command(["qq", "discord"], "删除兽设")
async def handle_delete(bot, event: MessageEvent, args: list):
    group_id = getattr(event, "group_id", None)
    if not group_id:
        await event.reply("请在群里删除。")
        return
    try:
        await redis_manager.redis.hdel(_key(int(group_id)), str(getattr(event, "user_id", "")))
    except Exception as exc:
        logger.error(f"[兽设] 删除失败: {type(exc).__name__}: {exc}")
        await event.reply("没能删掉，请稍后再试。")
        return
    await event.reply("已经把你在本群的兽设收起来了。")
