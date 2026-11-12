"""从 e926.net 取 SFW 兽图。e926 只提供安全分级的图。"""
from __future__ import annotations

import re
from typing import Iterable, Sequence

import aiohttp

from neobot.plugin_api import (
    MessageEvent,
    MessageSegment,
    ModuleLogger,
    define_plugin,
    global_config,
    platform_command,
)

from .cooldown import Cooldown

logger = ModuleLogger("E926")

plugin_manifest = define_plugin(
    name="e926_gallery",
    description="按标签找 SFW 兽图",
    usage=(
        "/兽图 <标签...> - 从 e926 找图，可在前面加数量，例如 /兽图 2 fox\n"
        "/furry <标签> 也会走到这里；不带标签的 /furry 仍是原来的随机图"
    ),
    version="0.1.0",
)

_TAG = re.compile(r"-?[a-z0-9_:]{1,64}")
_cooldown = Cooldown()


class TagRejected(ValueError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _settings():
    try:
        cfg = global_config.e926
        blacklist = [str(item).lower() for item in (cfg.blacklist or [])]
        return {
            "user_agent": cfg.user_agent or "NeoBot/1.0 (QQ furry group bot)",
            "username": cfg.username or "",
            "api_key": cfg.api_key or "",
            "rate_limit_seconds": float(cfg.rate_limit_seconds),
            "max_count": max(1, min(int(cfg.max_count), 5)),
            "blacklist": blacklist,
        }
    except Exception:
        return {
            "user_agent": "NeoBot/1.0 (QQ furry group bot)",
            "username": "",
            "api_key": "",
            "rate_limit_seconds": 8.0,
            "max_count": 3,
            "blacklist": ["cub", "young", "child", "loli", "shota", "gore"],
        }


def tag_is_blocked(tag: str, blacklist: Iterable[str]) -> bool:
    blocked = {item.lower() for item in blacklist}
    bare = tag.lstrip("-").lower()
    if bare in blocked or bare in {"rating:e", "rating:q"}:
        return True
    parts = bare.replace(":", "_").split("_")
    return any(part in blocked for part in parts if part)


def normalize_tags(tags: Sequence[str], blacklist: Iterable[str]) -> list[str]:
    cleaned: list[str] = []
    for raw in tags:
        tag = raw.strip().lower().replace(" ", "_")
        if not tag:
            continue
        if not _TAG.fullmatch(tag):
            raise TagRejected("charset")
        if tag_is_blocked(tag, blacklist):
            raise TagRejected("blocked")
        if tag not in cleaned:
            cleaned.append(tag)
    if not cleaned:
        raise TagRejected("empty")
    return cleaned


def parse_tag_args(args: Sequence[str], max_count: int) -> tuple[int, list[str]]:
    items = list(args)
    count = 1
    if items and items[0].isdigit():
        count = int(items.pop(0))
        if count <= 0:
            raise TagRejected("count")
        count = min(count, max_count)
    return count, items


def build_query(tags: Sequence[str], blacklist: Iterable[str]) -> str:
    negatives = [f"-{item}" for item in blacklist if item]
    parts = list(tags) + negatives + ["rating:s", "order:random"]
    return " ".join(parts)


def safe_post_urls(payload: dict, blacklist: Iterable[str], limit: int) -> list[str]:
    posts = payload.get("posts") if isinstance(payload, dict) else None
    if not isinstance(posts, list):
        return []
    urls: list[str] = []
    for post in posts:
        if not isinstance(post, dict):
            continue
        if str(post.get("rating") or "") != "s":
            continue
        tag_groups = post.get("tags") or {}
        flat: list[str] = []
        if isinstance(tag_groups, dict):
            for values in tag_groups.values():
                if isinstance(values, list):
                    flat.extend(str(item) for item in values)
        if any(tag_is_blocked(tag, blacklist) for tag in flat):
            continue
        file_info = post.get("file") or {}
        url = str(file_info.get("url") or "")
        if url.startswith("https://") and url not in urls:
            urls.append(url)
        if len(urls) >= limit:
            break
    return urls


async def search_posts(tags: Sequence[str], limit: int) -> list[str]:
    settings = _settings()
    cleaned = normalize_tags(tags, settings["blacklist"])
    query = build_query(cleaned, settings["blacklist"])
    auth = None
    if settings["username"] and settings["api_key"]:
        auth = aiohttp.BasicAuth(settings["username"], settings["api_key"])
    timeout = aiohttp.ClientTimeout(total=15)
    headers = {"User-Agent": settings["user_agent"]}
    async with aiohttp.ClientSession(timeout=timeout, headers=headers, auth=auth) as session:
        async with session.get("https://e926.net/posts.json", params={"tags": query, "limit": str(limit)}) as response:
            if response.status == 429:
                raise TagRejected("rate")
            if response.status != 200:
                raise TagRejected("http")
            payload = await response.json(content_type=None)
    return safe_post_urls(payload if isinstance(payload, dict) else {}, settings["blacklist"], limit)


def _reject_text(code: str) -> str:
    if code == "blocked":
        return "这个标签不能用哦。"
    if code == "charset":
        return "标签请用英文，例如 /兽图 fox。"
    if code == "empty":
        return "请带上标签，例如 /兽图 fox。"
    if code == "count":
        return "数量要是正整数。"
    if code == "rate":
        return "e926 说太快了，歇一会儿再试。"
    if code == "cooldown":
        return "找图有点勤，稍等几秒。"
    return "e926 这次没有回应，请稍后再试。"


async def reply_tagged_posts(event: MessageEvent, args: Sequence[str]) -> None:
    settings = _settings()
    user_id = str(getattr(event, "user_id", "") or "")
    if not _cooldown.allow(user_id, settings["rate_limit_seconds"]):
        await event.reply(_reject_text("cooldown"))
        return
    try:
        count, tags = parse_tag_args(args, settings["max_count"])
        urls = await search_posts(tags, count)
    except TagRejected as exc:
        await event.reply(_reject_text(exc.code))
        return
    except Exception as exc:
        logger.error(f"[兽图] 请求失败: {type(exc).__name__}: {exc}")
        await event.reply(_reject_text("http"))
        return
    if not urls:
        await event.reply("这两个标签下暂时没有能看的图。")
        return
    segments = [MessageSegment.text("找到啦")]
    segments.extend(MessageSegment.image(url) for url in urls)
    await event.reply(segments)


@platform_command(["qq", "discord"], "兽图")
async def handle_e926(bot, event: MessageEvent, args: list):
    await reply_tagged_posts(event, args)
