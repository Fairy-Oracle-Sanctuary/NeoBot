"""以图搜源。只回复链接、作者和相似度，不转发图片。"""
from __future__ import annotations

import asyncio
import re
from typing import Iterable
from urllib.parse import quote

import aiohttp

from neobot.plugin_api import (
    Bot,
    MessageEvent,
    ModuleLogger,
    define_plugin,
    global_config,
    input_validator,
    platform_command,
    platform_message,
)

from .image_refs import image_urls_from_payload, image_urls_from_segments, reply_message_id

logger = ModuleLogger("ImageSource")

plugin_manifest = define_plugin(
    name="image_source",
    description="按图片查找来源链接",
    usage=(
        "/搜源 - 附上图片、回复一张图，或等下一条图片\n"
        "只回复来源链接、作者和相似度，不会把图再发一遍"
    ),
    version="0.1.0",
)

_NSFW_HINTS = (
    "nhentai",
    "e-hentai",
    "exhentai",
    "rule34",
    "gelbooru",
    "sankaku",
    "xvideos",
    "pornhub",
    "r18",
    "r-18",
    "nsfw",
    "explicit",
)
_waiting: dict[int, asyncio.Task] = {}


def url_is_nsfw(url: str) -> bool:
    lowered = (url or "").lower()
    return any(hint in lowered for hint in _NSFW_HINTS)


def saucenao_error_message(header: dict) -> str | None:
    status = int(header.get("status") or 0)
    message = str(header.get("message") or "")
    lowered = message.lower()
    if status in (2, 3) or "limit" in lowered or "quota" in lowered or "daily" in lowered:
        return "SauceNAO 的查询额度用完了，明天再试试吧。"
    if status == -2 or "rate" in lowered:
        return "搜得太快了，稍等几秒再试。"
    if status != 0:
        return "SauceNAO 这次没有正常返回，请稍后再试。"
    long_remaining = header.get("long_remaining")
    short_remaining = header.get("short_remaining")
    if long_remaining == 0 and short_remaining == 0:
        return "SauceNAO 的查询额度用完了，明天再试试吧。"
    return None


def _author_of(data: dict) -> str:
    for key in ("creator", "author", "member_name", "artist", "author_name"):
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _links_of(data: dict) -> list[str]:
    found: list[str] = []
    ext = data.get("ext_urls") or []
    if isinstance(ext, list):
        found.extend(str(item) for item in ext)
    source = data.get("source")
    if isinstance(source, str) and source.startswith("http"):
        found.append(source)
    deduped = []
    for url in found:
        if url not in deduped:
            deduped.append(url)
    return deduped


def filter_saucenao_results(payload: dict, min_similarity: float = 55) -> tuple[str | None, list[dict]]:
    header = payload.get("header") if isinstance(payload, dict) else {}
    header = header or {}
    error = saucenao_error_message(header)
    if error and not payload.get("results"):
        return error, []
    kept = []
    for item in payload.get("results") or []:
        if not isinstance(item, dict):
            continue
        item_header = item.get("header") or {}
        if int(item_header.get("hidden") or 0) != 0:
            continue
        try:
            similarity = float(item_header.get("similarity") or 0)
        except (TypeError, ValueError):
            similarity = 0
        if similarity < min_similarity:
            continue
        data = item.get("data") or {}
        links = [url for url in _links_of(data) if not url_is_nsfw(url)]
        if not links:
            continue
        kept.append(
            {
                "similarity": similarity,
                "author": _author_of(data),
                "links": links,
            }
        )
    if error and not kept:
        return error, []
    return None, kept


def format_source_reply(results: Iterable[dict], source_name: str) -> str:
    rows = list(results)
    if not rows:
        return "没有找到可以放心转发的来源。"
    lines = [f"从 {source_name} 找到这些来源（只放链接）："]
    for index, item in enumerate(rows[:5], start=1):
        similarity = item.get("similarity")
        head = f"{index}."
        if similarity is not None:
            head += f" 相似度 {similarity:g}%"
        author = item.get("author") or ""
        if author:
            head += f"  作者：{author}"
        lines.append(head)
        for link in item.get("links") or []:
            lines.append(link)
    return "\n".join(lines)


def parse_ascii2d_html(html: str) -> list[dict]:
    """从 ascii2d 结果页抽出外链。结构变了就返回空，不猜。"""
    chunks = re.split(r'class="[^"]*\bitem-box\b', html or "")
    results = []
    seen = set()
    for chunk in chunks[1:]:
        links = re.findall(r'href="(https?://[^"]+)"[^>]*>(.*?)</a>', chunk, flags=re.S)
        external = []
        for url, text in links:
            if "ascii2d.net" in url or url_is_nsfw(url):
                continue
            title = re.sub(r"<[^>]+>", "", text)
            title = re.sub(r"\s+", " ", title).strip()
            external.append((url, title))
        if not external:
            continue
        url, _title = external[0]
        author = external[1][1] if len(external) > 1 else ""
        if url in seen:
            continue
        seen.add(url)
        results.append({"similarity": None, "author": author, "links": [url]})
        if len(results) >= 5:
            break
    return results


def _settings() -> dict:
    try:
        cfg = global_config.saucenao
        return {
            "api_key": (cfg.api_key or "").strip(),
            "min_similarity": float(cfg.min_similarity),
            "num_results": int(cfg.num_results),
            "ascii2d_fallback": bool(cfg.ascii2d_fallback),
            "timeout": int(cfg.timeout),
        }
    except Exception:
        return {
            "api_key": "",
            "min_similarity": 55,
            "num_results": 6,
            "ascii2d_fallback": True,
            "timeout": 15,
        }


async def _saucenao(url: str, settings: dict) -> tuple[str | None, list[dict]]:
    params = {
        "output_type": "2",
        "api_key": settings["api_key"],
        "db": "999",
        "numres": str(settings["num_results"]),
        "hide": "3",
        "url": url,
    }
    timeout = aiohttp.ClientTimeout(total=settings["timeout"])
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.get("https://saucenao.com/search.php", params=params) as response:
            if response.status in (429, 503):
                return "SauceNAO 的查询额度用完了，明天再试试吧。", []
            payload = await response.json(content_type=None)
    if not isinstance(payload, dict):
        return "SauceNAO 这次没有正常返回，请稍后再试。", []
    return filter_saucenao_results(payload, min_similarity=settings["min_similarity"])


async def _ascii2d(url: str, timeout_seconds: int) -> list[dict]:
    target = "https://ascii2d.net/search/url/" + quote(url, safe="")
    headers = {"User-Agent": "Mozilla/5.0 NeoBot/1.0"}
    timeout = aiohttp.ClientTimeout(total=timeout_seconds)
    async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
        async with session.get(target, allow_redirects=True) as response:
            if response.status != 200:
                return []
            html = await response.text(errors="replace")
    return parse_ascii2d_html(html)


async def lookup_sources(url: str) -> str:
    if not input_validator.validate_http_url(url):
        return "这张图的地址不能用。"
    settings = _settings()
    pieces = []
    if not settings["api_key"]:
        pieces.append("SauceNAO 还没配置。管理员可以在 config.toml 的 [saucenao] api_key 里填上。")
    else:
        try:
            error, results = await _saucenao(url, settings)
        except Exception as exc:
            logger.error(f"[搜源] SauceNAO 失败: {type(exc).__name__}: {exc}")
            error, results = "SauceNAO 这次没有正常返回，请稍后再试。", []
        if results:
            return format_source_reply(results, "SauceNAO")
        if error:
            pieces.append(error)
        else:
            pieces.append("SauceNAO 没有找到可以放心转发的来源。")
    if settings["ascii2d_fallback"]:
        try:
            fallback = await _ascii2d(url, settings["timeout"])
        except Exception as exc:
            logger.warning(f"[搜源] ascii2d 失败: {type(exc).__name__}: {exc}")
            fallback = []
        if fallback:
            return format_source_reply(fallback, "ascii2d")
        pieces.append("备用的 ascii2d 这次也没搜到。")
    return "\n".join(pieces) if pieces else "没有找到来源。"


async def _resolve_url(bot: Bot, event: MessageEvent) -> str:
    urls = image_urls_from_segments(getattr(event, "message", None))
    if urls:
        return urls[0]
    reply_id = reply_message_id(getattr(event, "message", None))
    if not reply_id or not hasattr(bot, "get_msg"):
        return ""
    try:
        payload = await bot.get_msg(int(reply_id))
    except Exception as exc:
        logger.warning(f"[搜源] 读取回复消息失败: {type(exc).__name__}: {exc}")
        return ""
    found = image_urls_from_payload(payload)
    return found[0] if found else ""


async def _wait_next(event: MessageEvent, timeout: int = 30) -> None:
    user_id = int(getattr(event, "user_id", 0) or 0)
    await event.reply(f"请在 {timeout} 秒内发一张要搜源的图片。")
    task = asyncio.current_task()
    _waiting[user_id] = task
    try:
        await asyncio.sleep(timeout)
        if _waiting.get(user_id) is task:
            _waiting.pop(user_id, None)
            await event.reply("等太久了，请重新发 /搜源。")
    except asyncio.CancelledError:
        return


@platform_message(["qq", "discord"], block=False)
async def handle_followup_image(bot: Bot, event: MessageEvent):
    user_id = int(getattr(event, "user_id", 0) or 0)
    if user_id not in _waiting:
        return
    urls = image_urls_from_segments(getattr(event, "message", None))
    if not urls:
        return
    task = _waiting.pop(user_id, None)
    if task is not None:
        task.cancel()
    await event.reply(await lookup_sources(urls[0]))


@platform_command(["qq", "discord"], "搜源")
async def handle_source(bot: Bot, event: MessageEvent, args: list):
    url = await _resolve_url(bot, event)
    if not url:
        asyncio.create_task(_wait_next(event))
        return
    await event.reply("在找来源，只回链接，不转发图片。")
    await event.reply(await lookup_sources(url))
