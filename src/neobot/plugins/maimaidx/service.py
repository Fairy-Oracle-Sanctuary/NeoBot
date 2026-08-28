"""
maimaiDX 水鱼查分器数据服务

- B50 查询: POST /query/player (b50=True), 服务端算好 Best35+Recent15
- 封面: https://www.diving-fish.com/covers/{id:05d}.png, 下载后压缩并缓存到 Redis
"""
import asyncio
import base64
import io
from typing import Any, Dict, List, Optional

import aiohttp
from PIL import Image

from neobot.plugin_api import ModuleLogger, redis_manager

logger = ModuleLogger("maimaidx")

API_BASE = "https://www.diving-fish.com/api/maimaidxprober"
COVER_BASE = "https://www.diving-fish.com/covers"
# 不带浏览器 UA 会被 403
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) NeoBot/1.0"

COVER_TTL = 30 * 86400          # 封面缓存 30 天
COVER_CONCURRENCY = 8           # 封面并发下载上限
COVER_TIMEOUT = 10              # 单张下载超时（秒）
COVER_SIZE = 240                # 压缩后的封面边长
COVER_QUALITY = 85              # JPEG 质量

_REDIS_KEY = "neobot:maimai:cover:{song_id}"

# 段位: additional_rating 0-10 初学者-十段, 11-20 真初段-真十段, 21-22 真皆传-里皆传
DAN_NAMES = [
    "初学者", "初段", "二段", "三段", "四段", "五段", "六段", "七段", "八段", "九段", "十段",
    "真初段", "真二段", "真三段", "真四段", "真五段", "真六段", "真七段", "真八段", "真九段", "真十段",
    "真皆伝", "裏皆伝",
]

# 评级颜色（SSS+ 金 → 低评级灰）
RATE_COLORS = {
    "sssp": "#ffd700", "sss": "#ffab00", "ssp": "#ff9100", "ss": "#ffe082",
    "sp": "#c5e1a5", "s": "#aed581", "aa": "#4fc3f7", "a": "#90a4ae",
    "bbb": "#9e9e9e", "bb": "#9e9e9e", "b": "#9e9e9e", "c": "#757575", "d": "#616161",
}

# FC / FS 徽章颜色
FC_COLORS = {"fc": "#66bb6a", "fcp": "#42a5f5", "ap": "#ffd700", "app": "#ffab91"}
FS_COLORS = {"fs": "#26c6da", "fsp": "#ab47bc", "fsd": "#7e57c2", "fsdp": "#ec407a", "sync": "#80deea"}


def dan_name(additional_rating: Any) -> str:
    try:
        idx = int(additional_rating)
    except (TypeError, ValueError):
        return ""
    if 0 <= idx < len(DAN_NAMES):
        return DAN_NAMES[idx]
    return ""


def ra_color(ra: Any) -> str:
    try:
        r = int(ra)
    except (TypeError, ValueError):
        return "#78909c"
    if r >= 320:
        return "#ffd700"
    if r >= 300:
        return "#ffb300"
    if r >= 280:
        return "#ff7043"
    if r >= 260:
        return "#ab47bc"
    if r >= 240:
        return "#42a5f5"
    return "#78909c"


def level_color(level: Any) -> str:
    """谱面等级角标颜色"""
    try:
        text = str(level)
        num = float(text.rstrip("+"))
        plus = text.endswith("+")
    except (TypeError, ValueError):
        return "#607d8b"
    base = [
        (6, "#66bb6a"), (9, "#42a5f5"), (11, "#ab47bc"),
        (12, "#ff9800"), (13, "#ef5350"), (14, "#d32f2f"), (15, "#ffd700"),
    ]
    color = "#607d8b"
    for limit, c in base:
        if num <= limit:
            color = c
            break
    else:
        color = "#ffd700"
    return color


def cover_file_id(song_id: Any) -> str:
    """歌曲 ID → 封面文件名（补足 5 位；10001~11000 段是 DX 谱面，用其 SD 封面）"""
    sid = int(song_id)
    if 10000 < sid <= 11000:
        sid -= 10000
    return f"{sid:05d}"


class B50QueryError(Exception):
    def __init__(self, status: int, message: str):
        self.status = status
        self.message = message
        super().__init__(f"水鱼查分器返回 {status}: {message}")


async def fetch_b50(identifier: Dict[str, Any]) -> Dict[str, Any]:
    """
    查询玩家 B50。

    identifier: {"username": str} 或 {"qq": str}
    返回水鱼 /query/player 原始响应: nickname/rating/plate/additional_rating/charts.{dx,sd}
    仅对「允许公开查询」的玩家有效, 隐私玩家抛 B50QueryError(403/400)。
    """
    payload = {"b50": True, **identifier}
    async with aiohttp.ClientSession() as session:
        async with session.post(
            f"{API_BASE}/query/player",
            json=payload,
            headers={"User-Agent": UA, "Accept": "application/json"},
            timeout=aiohttp.ClientTimeout(total=20),
        ) as resp:
            if resp.status != 200:
                try:
                    body = await resp.json()
                except Exception:
                    body = {}
                raise B50QueryError(resp.status, body.get("message", "") or f"HTTP {resp.status}")
            return await resp.json()


def _compress_cover(data: bytes) -> str:
    """PNG → 240x240 JPEG(base64)。失败返回空串。"""
    try:
        im = Image.open(io.BytesIO(data))
        if im.mode != "RGB":
            im = im.convert("RGB")
        im = im.resize((COVER_SIZE, COVER_SIZE), Image.Resampling.LANCZOS)
        buf = io.BytesIO()
        im.save(buf, format="JPEG", quality=COVER_QUALITY, optimize=True)
        return base64.b64encode(buf.getvalue()).decode()
    except Exception as e:
        logger.warning(f"封面压缩失败: {e}")
        return ""


async def _download_cover_b64(song_id: Any) -> str:
    url = f"{COVER_BASE}/{cover_file_id(song_id)}.png"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                url, headers={"User-Agent": UA}, timeout=aiohttp.ClientTimeout(total=COVER_TIMEOUT)
            ) as resp:
                if resp.status != 200:
                    return ""
                data = await resp.read()
                if not data:
                    return ""
                return _compress_cover(data)
    except Exception as e:
        logger.warning(f"封面下载失败 {url}: {e}")
        return ""


async def get_cover_b64(song_id: Any) -> str:
    """带 Redis 缓存的封面 base64（已压缩）。失败返回空串, 由模板显示占位。"""
    key = _REDIS_KEY.format(song_id=int(song_id))
    client = None
    try:
        client = redis_manager.redis
        cached = client.get(key)  # type: ignore[no-any-return]
        if cached:
            return cached.decode() if isinstance(cached, bytes) else str(cached)
    except Exception as e:
        logger.warning(f"封面缓存读取失败: {e}")

    b64 = await _download_cover_b64(song_id)
    if b64 and client is not None:
        try:
            client.set(key, b64, ex=COVER_TTL)
        except Exception as e:
            logger.warning(f"封面缓存写入失败: {e}")
    return b64


async def fetch_covers_b64(song_ids: List[Any]) -> Dict[int, str]:
    """并发取封面（限并发），返回 {song_id: base64}"""
    sem = asyncio.Semaphore(COVER_CONCURRENCY)

    async def one(sid: Any) -> tuple:
        async with sem:
            return int(sid), await get_cover_b64(sid)

    results = await asyncio.gather(*(one(s) for s in song_ids))
    return dict(results)


def build_song_list(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """charts.dx + charts.sd 合并, 按 ra 降序, 附展示字段"""
    songs = []
    for chart in data.get("charts", {}).get("dx", []) + data.get("charts", {}).get("sd", []):
        songs.append(chart)
    songs.sort(key=lambda s: s.get("ra", 0), reverse=True)

    out = []
    for rank, s in enumerate(songs, start=1):
        rate = s.get("rate", "")
        fc = s.get("fc", "")
        fs = s.get("fs", "")
        badges = []
        if fc in FC_COLORS:
            badges.append({"text": fc.upper() if fc != "fcp" else "FC+", "color": FC_COLORS[fc]})
        if fs in FS_COLORS:
            labels = {"fs": "FS", "fsp": "FS+", "fsd": "FSD", "fsdp": "FSD+", "sync": "SYNC"}
            badges.append({"text": labels.get(fs, fs.upper()), "color": FS_COLORS[fs]})
        out.append({
            "rank": rank,
            "song_id": int(s.get("song_id", 0)),
            "title": s.get("title", ""),
            "type": s.get("type", ""),              # DX / SD
            "level": s.get("level", ""),
            "level_color": level_color(s.get("level", "")),
            "ds": s.get("ds", 0),
            "achievements": s.get("achievements", 0),
            "ra": s.get("ra", 0),
            "ra_color": ra_color(s.get("ra", 0)),
            "rate": rate.upper(),
            "rate_color": RATE_COLORS.get(rate, "#9e9e9e"),
            "badges": badges,
        })
    return out
