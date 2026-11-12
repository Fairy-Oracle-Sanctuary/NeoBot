# -*- coding: utf-8 -*-
"""
网易云点歌。

播放服务地址来自配置：
- api_style=ncm：网易云 API 兼容接口（/search、/song/url、/song/detail）
- api_style=netease_url：旧的本地 POST /search 与 POST /song
base_url 留空时使用 public_base。连不上时给一句人话，不再默默打向 127.0.0.1。
"""
from __future__ import annotations

import re
from typing import Any, Optional
import aiohttp
from cachetools import TTLCache

from neobot.plugin_api import MessageSegment, ModuleLogger, define_plugin, global_config, platform_command, platform_message

logger = ModuleLogger("Music")

plugin_manifest = define_plugin(
    name="music",
    description="网易云点歌，也可以识别歌曲链接",
    usage=(
        "/点歌 <歌名> - 搜索并在 30 秒内用序号点播\n"
        "/点歌 <歌曲ID> - 直接发语音\n"
        "发网易云、酷狗或 YouTube 链接时，会回一张文字信息卡"
    ),
    version="0.2.0",
)

SEARCH_LIMIT = 10
SELECT_TTL = 30

_session: aiohttp.ClientSession | None = None
_pending: Any = TTLCache(maxsize=200, ttl=SELECT_TTL)

_NETEASE_QUERY = re.compile(r"music\.163\.com/[^\s]*?(?:\?|&)id=(\d+)", re.IGNORECASE)
_NETEASE_PATH = re.compile(r"music\.163\.com/(?:#/)?song/(\d+)", re.IGNORECASE)
_YOUTUBE_ID = re.compile(
    r"(?:youtube\.com/(?:watch\?[^\s]*?v=|shorts/)|youtu\.be/|music\.youtube\.com/watch\?[^\s]*?v=)([\w-]{6,})",
    re.IGNORECASE,
)
_KUGOU_HASH = re.compile(r"(?:hash=)([0-9A-Fa-f]{32})", re.IGNORECASE)


class MusicBackendError(Exception):
    """点歌服务连不上或没有按约定返回。"""


def resolve_music_endpoint(base_url: str = "", public_base: str = "", api_style: str = "ncm") -> tuple[str, str]:
    style = (api_style or "ncm").strip().lower()
    if style not in ("ncm", "netease_url"):
        style = "ncm"
    base = (base_url or "").strip().rstrip("/")
    if not base:
        base = (public_base or "").strip().rstrip("/")
    return base, style


def play_url_from_template(template: str, song_id) -> str:
    text = (template or "").strip()
    if not text or "{id}" not in text:
        return ""
    return text.replace("{id}", str(song_id))


def find_song_links(text: str) -> list[dict]:
    """从一段文字里找出网易云、酷狗、YouTube 链接。最多两条。"""
    found: list[dict] = []
    seen = set()

    def add(kind: str, key: str, page: str) -> None:
        marker = (kind, key)
        if marker in seen or len(found) >= 2:
            return
        seen.add(marker)
        found.append({"kind": kind, "key": key, "page": page})

    source = text or ""
    for pattern in (_NETEASE_QUERY, _NETEASE_PATH):
        for match in pattern.finditer(source):
            start = source.rfind("http", 0, match.start())
            page = source[start:].split()[0] if start >= 0 else f"https://music.163.com/song?id={match.group(1)}"
            add("netease", match.group(1), page)
    for match in _YOUTUBE_ID.finditer(source):
        start = source.rfind("http", 0, match.start())
        page = source[start:].split()[0] if start >= 0 else f"https://youtu.be/{match.group(1)}"
        add("youtube", match.group(1), page)
    if "kugou.com" in source.lower():
        for match in _KUGOU_HASH.finditer(source):
            start = source.rfind("http", 0, match.start())
            page = source[start:].split()[0] if start >= 0 else f"https://www.kugou.com/song/#hash={match.group(1)}"
            add("kugou", match.group(1).upper(), page)
    return found


def format_link_card(kind: str, title: str, author: str, page: str) -> str:
    names = {"netease": "网易云音乐", "kugou": "酷狗音乐", "youtube": "YouTube"}
    label = names.get(kind, "音乐")
    title = title.strip() or "未命名"
    author = author.strip() or "未知"
    return f"{label}\n{title} - {author}\n{page}"


def _settings() -> dict:
    try:
        cfg = global_config.music
    except Exception:
        cfg = None
    base_url = getattr(cfg, "base_url", "") if cfg else ""
    public_base = getattr(cfg, "public_base", "") if cfg else ""
    api_style = getattr(cfg, "api_style", "ncm") if cfg else "ncm"
    base, style = resolve_music_endpoint(base_url, public_base, api_style)
    return {
        "base": base,
        "style": style,
        "play_template": getattr(cfg, "play_url_template", "") if cfg else "",
        "link_card": bool(getattr(cfg, "link_card", True) if cfg else True),
        "timeout": int(getattr(cfg, "timeout", 12) if cfg else 12),
    }


def get_session(timeout: int = 12) -> aiohttp.ClientSession:
    global _session
    if _session is None or _session.closed:
        _session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=timeout))
    return _session


async def close_session():
    global _session
    if _session is not None and not _session.closed:
        await _session.close()


def _unavailable() -> str:
    return "点歌服务暂时连不上。管理员可以检查 config.toml 里的 [music] base_url。"


async def _request_json(method: str, url: str, *, params=None, payload=None, timeout: int = 12) -> dict:
    try:
        session = get_session(timeout)
        async with session.request(method, url, params=params, json=payload) as response:
            if response.status != 200:
                logger.error(f"[点歌] {url} HTTP {response.status}")
                raise MusicBackendError(f"http {response.status}")
            data = await response.json(content_type=None)
    except MusicBackendError:
        raise
    except Exception as exc:
        logger.error(f"[点歌] 请求失败: {type(exc).__name__}: {exc}")
        raise MusicBackendError(str(exc)) from exc
    if not isinstance(data, dict):
        raise MusicBackendError("not json")
    return data


def _song_from_ncm(item: dict) -> Optional[dict]:
    if not isinstance(item, dict) or not item.get("id"):
        return None
    artists = item.get("artists") or item.get("ar") or []
    if isinstance(artists, list):
        names = [str(artist.get("name")) for artist in artists if isinstance(artist, dict) and artist.get("name")]
        artist = "、".join(names) or "未知歌手"
    else:
        artist = str(artists or "未知歌手")
    album = item.get("album") or item.get("al") or {}
    album_name = album.get("name", "") if isinstance(album, dict) else ""
    return {
        "id": item["id"],
        "name": item.get("name") or "未知歌曲",
        "artist": artist,
        "album": album_name,
    }


async def search_songs(keywords: str, limit: int = SEARCH_LIMIT) -> list[dict]:
    settings = _settings()
    if not settings["base"]:
        raise MusicBackendError("unconfigured")
    if settings["style"] == "netease_url":
        data = await _request_json(
            "POST",
            f"{settings['base']}/search",
            payload={"keywords": keywords, "limit": limit},
            timeout=settings["timeout"],
        )
        if not data.get("success"):
            return []
        songs = []
        for item in data.get("data") or []:
            if isinstance(item, dict) and item.get("id"):
                songs.append({
                    "id": item["id"],
                    "name": item.get("name", "未知歌曲"),
                    "artist": item.get("artist_string") or item.get("artists") or "未知歌手",
                    "album": item.get("album", ""),
                })
        return songs
    data = await _request_json(
        "GET",
        f"{settings['base']}/search",
        params={"keywords": keywords, "limit": str(limit)},
        timeout=settings["timeout"],
    )
    raw = ((data.get("result") or {}).get("songs")) or []
    songs = []
    for item in raw:
        song = _song_from_ncm(item)
        if song:
            songs.append(song)
    return songs


async def resolve_song_url(song_id) -> str | None:
    settings = _settings()
    if not settings["base"]:
        raise MusicBackendError("unconfigured")
    if settings["style"] == "netease_url":
        data = await _request_json(
            "POST",
            f"{settings['base']}/song",
            payload={"id": str(song_id), "quality": "lossless"},
            timeout=settings["timeout"],
        )
        if not data.get("success"):
            return None
        url = (data.get("data") or {}).get("url")
        return url if isinstance(url, str) and url else None
    data = await _request_json(
        "GET",
        f"{settings['base']}/song/url",
        params={"id": str(song_id)},
        timeout=settings["timeout"],
    )
    rows = data.get("data") or []
    if isinstance(rows, list) and rows:
        url = rows[0].get("url") if isinstance(rows[0], dict) else None
        if isinstance(url, str) and url:
            return url
    return play_url_from_template(settings["play_template"], song_id) or None


async def _looks_like_audio(url: str, timeout: int) -> bool:
    try:
        session = get_session(timeout)
        async with session.get(url, headers={"Range": "bytes=0-1"}, allow_redirects=True) as response:
            if response.status not in (200, 206):
                return False
            ctype = (response.headers.get("Content-Type") or "").lower()
            if "text/html" in ctype or "application/json" in ctype:
                return False
            if any(token in ctype for token in ("audio", "octet-stream", "video", "mpeg")):
                return True
            final = str(response.url).split("?")[0].lower()
            return final.endswith((".mp3", ".flac", ".m4a", ".aac", ".ogg"))
    except Exception as exc:
        logger.warning(f"[点歌] 直链检查失败: {type(exc).__name__}: {exc}")
        return False


def _fmt_song(idx: int, song: dict) -> str:
    return f"{idx}. {song['name']} - {song['artist']}"


async def _play_song(ctx, song_id, label: str = ""):
    try:
        url = await resolve_song_url(song_id)
    except MusicBackendError:
        await ctx.reply(_unavailable())
        return
    if not url:
        await ctx.reply(f"找到了这首歌{label}，但没有拿到播放链接。")
        return
    timeout = _settings()["timeout"]
    if not await _looks_like_audio(url, timeout):
        await ctx.reply(f"这首歌的播放链接暂时不可用{label}。")
        return
    try:
        await ctx.reply(MessageSegment.record(url))
        logger.info(f"[点歌] 已发送语音 {label}")
    except Exception as exc:
        await ctx.reply(f"语音发送失败了{label}。")
        logger.error(f"[点歌] 发送失败: {type(exc).__name__}: {exc}")


@platform_command(["qq"], "点歌")
async def handle_diange(bot, ctx, args: list[str]):
    query = " ".join(args).strip() if args else ""
    if not query:
        await ctx.reply(
            "点歌用法：\n"
            "  /点歌 <歌曲名>  搜索\n"
            "  /点歌 <序号>    在30秒内选歌\n"
            "  /点歌 <歌曲ID>  直接发语音"
        )
        return
    user_id = getattr(ctx, "user_id", None)
    if query.isdigit():
        pending = _pending.get(user_id) if user_id is not None else None
        idx = int(query)
        if pending and 1 <= idx <= len(pending):
            song = pending[idx - 1]
            await _play_song(ctx, song["id"], label=f"（{song['name']}）")
            return
        await _play_song(ctx, idx, label=f"（ID {idx}）")
        return
    try:
        result = await search_songs(query)
    except MusicBackendError:
        await ctx.reply(_unavailable())
        return
    if not result:
        await ctx.reply(f"没有找到与「{query}」相关的歌曲。")
        return
    if user_id is not None:
        _pending[user_id] = result
    lines = [f"搜索「{query}」："] + [_fmt_song(i, song) for i, song in enumerate(result, 1)]
    lines.append(f"{SELECT_TTL} 秒内回复 /点歌 <序号> 就能听。")
    await ctx.reply("\n".join(lines))


async def song_detail(song_id: str) -> tuple[str, str]:
    settings = _settings()
    if not settings["base"] or settings["style"] != "ncm":
        return "", ""
    data = await _request_json(
        "GET",
        f"{settings['base']}/song/detail",
        params={"ids": song_id},
        timeout=settings["timeout"],
    )
    songs = data.get("songs") or []
    song = _song_from_ncm(songs[0]) if songs else None
    if not song:
        return "", ""
    return song["name"], song["artist"]


async def youtube_oembed(page: str) -> tuple[str, str]:
    endpoint = "https://www.youtube.com/oembed"
    data = await _request_json("GET", endpoint, params={"url": page, "format": "json"}, timeout=8)
    return str(data.get("title") or ""), str(data.get("author_name") or "")


async def kugou_detail(song_hash: str) -> tuple[str, str]:
    data = await _request_json(
        "GET",
        "https://wwwapi.kugou.com/yy/index.php",
        params={"r": "play/getdata", "hash": song_hash},
        timeout=8,
    )
    info = data.get("data") or {}
    if not isinstance(info, dict):
        return "", ""
    return str(info.get("audio_name") or info.get("song_name") or ""), str(info.get("author_name") or "")


def _message_text(event) -> str:
    raw = getattr(event, "raw_message", "") or ""
    if raw:
        return raw
    parts = []
    for segment in getattr(event, "message", None) or []:
        if getattr(segment, "type", None) == "text":
            parts.append(str((getattr(segment, "data", None) or {}).get("text") or ""))
    return "".join(parts)


@platform_message(["qq", "discord"], block=False)
async def handle_song_link(bot, event):
    settings = _settings()
    if not settings["link_card"]:
        return
    text = _message_text(event).strip()
    if not text or text.startswith("/"):
        return
    links = find_song_links(text)
    if not links:
        return
    cards = []
    for link in links:
        title, author = "", ""
        try:
            if link["kind"] == "netease":
                title, author = await song_detail(link["key"])
            elif link["kind"] == "youtube":
                title, author = await youtube_oembed(link["page"])
            elif link["kind"] == "kugou":
                title, author = await kugou_detail(link["key"])
        except Exception as exc:
            logger.info(f"[点歌] 链接卡片降级: {type(exc).__name__}: {exc}")
        if not title:
            title = "歌曲" if link["kind"] != "youtube" else "视频"
        cards.append(format_link_card(link["kind"], title, author, link["page"]))
    if cards:
        await event.reply("\n\n".join(cards))

