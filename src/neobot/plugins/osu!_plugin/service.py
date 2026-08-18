import os
import re
import aiohttp
from dataclasses import dataclass
from typing import Optional

from ossapi import Ossapi, Beatmap


@dataclass
class BeatmapMeta:
    bid: int
    sid: int
    mode: str
    mode_int: int
    artist: str
    title: str
    version: str
    mapper: str
    official_sr: float
    status: str
    total_length: int
    cs: float
    od: float
    ar: float
    hp: float
    bpm: float
    cover_url: str = ""


_client_error_state: Optional[str] = None
_client_last_error: Optional[str] = None


def get_osu_client() -> Optional[Ossapi]:
    global _client_error_state, _client_last_error
    # 凭据必须通过环境变量注入，禁止硬编码默认值（曾泄露真实 secret 到 git）
    client_id = os.environ.get("OSU_CLIENT_ID", "")
    client_secret = os.environ.get("OSU_CLIENT_SECRET", "")

    if not client_id or not client_secret:
        _client_error_state = "missing_credentials"
        _client_last_error = "osu! API 凭据未配置，请检查 OSU_CLIENT_ID / OSU_CLIENT_SECRET 环境变量"
        return None

    try:
        client = Ossapi(int(client_id), client_secret)
        _client_error_state = None
        return client
    except Exception as e:
        _client_error_state = "auth_failed"
        _client_last_error = f"osu! API 鉴权失败: {e}"
        return None


LINK_PATTERNS = [
    re.compile(r"osu\.ppy\.sh/beatmapsets/(\d+)(?:#(?:osu|taiko|fruits|mania)/(\d+))?"),
    re.compile(r"osu\.ppy\.sh/b(?:eatmaps)?/(\d+)"),
    re.compile(r"bid[=:\s]*(\d+)", re.IGNORECASE),
    re.compile(r"^(\d{4,12})$"),
]


def parse_beatmap_id(text: str) -> Optional[int]:
    text = text.strip()
    for pattern in LINK_PATTERNS:
        m = pattern.search(text)
        if m:
            groups = m.groups()
            if groups[-1] and groups[-1].isdigit():
                return int(groups[-1])
            if groups[0] and groups[0].isdigit():
                return int(groups[0])
    return None


BEATMAP_STATUS_WARNINGS = {
    "graveyard": "⚠️ 该谱面已被移入坟场 (Graveyard)，可能无法获取完整数据",
    "wip": "⚠️ 该谱面处于 WIP 状态，尚未完成",
    "pending": "ℹ️ 该谱面处于 Pending 状态，尚未正式上架",
    "loved": "♥️ 该谱面为 Loved 社区心选谱面",
    "approved": "ℹ️ 该谱面为 Approved 状态",
    "qualified": "ℹ️ 该谱面处于 Qualified 状态",
}


def _check_beatmap_status(meta: BeatmapMeta) -> Optional[str]:
    status_key = str(meta.status).lower()
    return BEATMAP_STATUS_WARNINGS.get(status_key)


def _resolve_beatmapset(b: Beatmap):
    try:
        bs = b.beatmapset
    except Exception:
        return None
    if callable(bs):
        try:
            return bs()
        except Exception:
            return None
    return bs


def beatmap_to_meta(b: Beatmap) -> BeatmapMeta:
    bs = _resolve_beatmapset(b)
    cover_url = ""
    if bs and hasattr(bs, "covers"):
        try:
            cover_url = bs.covers.cover or ""
        except Exception:
            pass
    return BeatmapMeta(
        bid=b.id,
        sid=b.beatmapset_id,
        mode=str(b.mode.value) if hasattr(b.mode, "value") else str(b.mode),
        mode_int=b.mode_int,
        artist=bs.artist if bs else "",
        title=bs.title if bs else "",
        version=b.version,
        mapper=bs.creator if bs else "",
        official_sr=b.difficulty_rating,
        status=str(b.status.value) if hasattr(b.status, "value") else str(b.status),
        total_length=b.total_length,
        cs=b.cs,
        od=b.accuracy,
        ar=b.ar,
        hp=b.drain,
        bpm=b.bpm,
        cover_url=cover_url,
    )


@dataclass
class FetchResult:
    meta: Optional[BeatmapMeta] = None
    error: Optional[str] = None
    error_code: Optional[str] = None
    warning: Optional[str] = None


async def fetch_beatmap_meta(bid: int) -> FetchResult:
    client = get_osu_client()
    if client is None:
        return FetchResult(error=_client_last_error, error_code="client_error")

    try:
        b = client.beatmap(bid)
        if not b:
            return FetchResult(
                error=f"谱面 ID {bid} 不存在，可能是 ID 错误或谱面已被删除",
                error_code="not_found",
            )
        meta = beatmap_to_meta(b)
        warning = _check_beatmap_status(meta)
        return FetchResult(meta=meta, warning=warning)
    except Exception as e:
        detail = str(e)
        if "404" in detail or "not found" in detail.lower():
            return FetchResult(
                error=f"谱面 ID {bid} 不存在，请检查 ID 是否正确",
                error_code="not_found",
            )
        if "401" in detail or "unauthorized" in detail.lower() or "403" in detail:
            return FetchResult(
                error="osu! API 鉴权失败，凭据可能已过期，请联系管理员更新",
                error_code="auth_expired",
            )
        if "429" in detail or "rate" in detail.lower():
            return FetchResult(
                error="osu! API 请求频率超限 (429)，请稍后再试",
                error_code="rate_limited",
            )
        return FetchResult(
            error=f"osu! API 请求失败: {detail}",
            error_code="api_error",
        )
    except Exception as e:
        return FetchResult(
            error=f"获取谱面信息时发生异常: {e}",
            error_code="internal_error",
        )


@dataclass
class DownloadResult:
    osu_text: Optional[str] = None
    error: Optional[str] = None
    error_code: Optional[str] = None


async def download_osu_text(bid: int) -> DownloadResult:
    url = f"https://osu.ppy.sh/osu/{bid}"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status == 200:
                    text = await resp.text(encoding="utf-8")
                    return DownloadResult(osu_text=text)
                if resp.status == 404:
                    return DownloadResult(
                        error=f"谱面文件 ({url}) 不存在 (HTTP 404)，该谱面可能已被删除或未提交",
                        error_code="download_404",
                    )
                if resp.status == 429:
                    return DownloadResult(
                        error="下载请求频率超限 (HTTP 429)，请稍后再试",
                        error_code="download_429",
                    )
                if resp.status >= 500:
                    return DownloadResult(
                        error=f"osu! 服务器错误 (HTTP {resp.status})，请稍后再试",
                        error_code="download_server_error",
                    )
                return DownloadResult(
                    error=f"下载谱面文件失败 (HTTP {resp.status})",
                    error_code="download_http_error",
                )
    except aiohttp.ClientTimeout:
        return DownloadResult(
            error="下载谱面文件超时 (15s)，osu! 服务器可能响应缓慢",
            error_code="download_timeout",
        )
    except aiohttp.ClientError as e:
        return DownloadResult(
            error=f"下载网络异常: {e}",
            error_code="download_network_error",
        )
    except Exception as e:
        return DownloadResult(
            error=f"下载谱面文件时发生异常: {e}",
            error_code="download_internal_error",
        )
