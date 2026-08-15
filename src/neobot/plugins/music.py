# -*- coding: utf-8 -*-
"""
网易云音乐点歌插件

联动本地网易云无损解析服务（Netease_url，运行于 192.168.1.11:5000，host 网络下
以 http://127.0.0.1:5000 访问），提供：

- /点歌 <歌曲名>  : 搜索歌曲，返回候选列表，并给用户打 30 秒的选择标记
- /点歌 <序号>    : 在 30 秒标记有效期内，从候选列表中选歌并发语音
- /点歌 <歌曲ID>  : 直接按歌曲 ID 解析并发回一条语音消息

语音消息通过 OneBot record 段发送，NapCat 会下载音频并转码为 QQ 语音。
"""
from typing import Any

import aiohttp
from cachetools import TTLCache

from neobot.core.managers.command_manager import matcher
from neobot.core.utils.logger import logger
from neobot.models.message import MessageSegment

# ---------- 配置 ----------
# 网易云解析服务地址（neobot 为 host 网络，与网易云服务同主机）：
#   部署在 192.168.1.11 -> host 网络下容器内等价 127.0.0.1
NETEASE_BASE = "http://127.0.0.1:5000"
# 点歌默认音质（无损 FLAC）
DEFAULT_QUALITY = "lossless"
# 单次搜索返回给用户的候选数量
SEARCH_LIMIT = 10
# 选歌标记有效期（秒）
SELECT_TTL = 30

# ---------- 会话与状态 ----------
# 全局共享 aiohttp session
_session: aiohttp.ClientSession | None = None


def get_session() -> aiohttp.ClientSession:
    """获取或创建全局 aiohttp session。"""
    global _session
    if _session is None or _session.closed:
        _session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=20)
        )
    return _session


async def close_session():
    """进程退出时关闭会话。"""
    global _session
    if _session is not None and not _session.closed:
        await _session.close()


# 选歌标记：user_id -> 搜索结果列表（TTL=30s）
_pending: Any = TTLCache(maxsize=200, ttl=SELECT_TTL)


# ---------- 网易云 API 客户端 ----------
async def _post_json(path: str, payload: dict) -> dict | None:
    """向网易云解析服务发送 POST JSON 请求，返回 dict；失败返回 None。"""
    url = f"{NETEASE_BASE}{path}"
    try:
        async with get_session().post(
            url, json=payload, headers={"Content-Type": "application/json"}
        ) as resp:
            if resp.status != 200:
                logger.error(f"[点歌] {path} 请求失败: HTTP {resp.status}")
                return None
            return await resp.json(content_type=None)
    except Exception as e:
        logger.error(f"[点歌] {path} 请求异常: {e}")
        return None


async def search_songs(keywords: str, limit: int = SEARCH_LIMIT):
    """搜索歌曲，返回 [{id, name, artist_string, album, picUrl}]。"""
    data = await _post_json("/search", {"keywords": keywords, "limit": limit})
    if not data or not data.get("success"):
        return []
    raw = data.get("data") or []
    songs = []
    for item in raw:
        if isinstance(item, dict) and item.get("id"):
            songs.append({
                "id": item["id"],
                "name": item.get("name", "未知歌曲"),
                "artist": item.get("artist_string") or item.get("artists") or "未知歌手",
                "album": item.get("album", ""),
            })
    return songs


async def resolve_song_url(song_id) -> str | None:
    """解析歌曲播放直链（默认 exhigh mp3）。返回音频 URL 或 None。"""
    data = await _post_json("/song", {"id": str(song_id), "quality": DEFAULT_QUALITY})
    if not data or not data.get("success"):
        return None
    d = data.get("data") or {}
    url = d.get("url")
    return url if isinstance(url, str) and url else None


# ---------- 展示 ----------
def _fmt_song(idx: int, song: dict) -> str:
    """格式化单条候选。"""
    return f"{idx}. {song['name']} - {song['artist']}"


# ---------- 指令 ----------
@matcher.platform_command(["qq"], "点歌")
async def handle_diange(bot, ctx, args: list[str]):
    """处理 /点歌 指令：搜索 / 选歌 / 按 ID 发语音。"""
    query = " ".join(args).strip() if args else ""

    if not query:
        await ctx.reply(
            "🎵 点歌用法：\n"
            "  /点歌 <歌曲名>  搜索\n"
            "  /点歌 <序号>    在30秒内选歌\n"
            "  /点歌 <歌曲ID>  直接发语音"
        )
        return

    user_id = getattr(ctx, "user_id", None)

    # 纯数字：可能是选歌序号，也可能是歌曲 ID
    if query.isdigit():
        pending = _pending.get(user_id) if user_id is not None else None
        idx = int(query)

        # 有30秒标记且序号在范围内 → 选歌
        if pending and 1 <= idx <= len(pending):
            song = pending[idx - 1]
            await _play_song(ctx, song["id"], label=f"({idx}→{song['name']})")
            return

        # 视为歌曲 ID → 直接解析发语音
        await _play_song(ctx, idx, label=f"(ID {idx})")
        return

    # 非数字 → 搜索
    result = await search_songs(query)
    if not result:
        await ctx.reply(f"没有找到与「{query}」相关的歌曲。")
        return

    # 保存候选并打 30s 标记
    if user_id is not None:
        _pending[user_id] = result

    lines = [f"🎵 搜索「{query}」的结果："] + [
        _fmt_song(i, s) for i, s in enumerate(result, 1)
    ]
    lines.append(f"在 {SELECT_TTL} 秒内回复 /点歌 <序号> 即可点这首歌~")
    await ctx.reply("\n".join(lines))


async def _play_song(ctx, song_id, label: str = ""):
    """解析并发送歌曲语音。"""
    url = await resolve_song_url(song_id)
    if not url:
        await ctx.reply(f"❌ 无法获取歌曲直链{label}，可能是 cookie 过期或歌曲受限。")
        return
    try:
        segment = MessageSegment.record(url)
        await ctx.reply(segment)
        logger.info(f"[点歌] 已发送语音 {label} url={url[:80]}")
    except Exception as e:
        await ctx.reply(f"❌ 语音发送失败{label}: {e}")
