# -*- coding: utf-8 -*-
"""
抖音网页版逆向解析通道（免费、极速、无第三方限流）

原理（2026-08 实测有效）：
1. ttwid：POST https://ttwid.bytedance.com/ttwid/union/register/ 拿 cookie（一次性，可缓存）
2. a_bogus：对 query 参数字符串做签名（算法见 douyin_abogus.py，来自 f2/JohnserfSeed，Apache-2.0）
3. detail：GET https://www.douyin.com/aweme/v1/web/aweme/detail?<params>&a_bogus=<sig>

关键坑：
- 抖音风控含 TLS 指纹检测（JA3/JA4）：aiohttp/requests 裸 TLS 一律 200+空 body，
  必须用 curl_cffi 的 impersonate="chrome" 模拟浏览器 TLS 指纹。
- 签名与 User-Agent / browser_fp 绑定：请求头 UA 必须与签名时一致。
- iteminfo 老接口（iesdouyin.com/web/api/v2/aweme/iteminfo）已死（status_code=11110），
  勿回退到它。
- 实测端到端 ~0.8s（短链重定向 0.5s + API 0.26s + 签名 2ms），qzqi 第三方 ~1.2s 且图文解析挂。

失败时返回 None，由调用方回退到第三方通道。
"""

import re
import time
from typing import Optional, Dict, Any
from urllib.parse import urlparse

from curl_cffi.requests import AsyncSession

from neobot.core.utils.logger import logger
from neobot.core.utils.input_validator import input_validator

from .douyin_abogus import ABogus, BrowserFingerprintGenerator

# 固定 UA：与签名绑定的浏览器指纹必须一致
_WEB_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

# 短链重定向/详情请求超时
_TIMEOUT = 10
# ttwid 缓存时长（秒）：抖音 ttwid 有效期约数天，缓存 12h 足够
_TTWID_TTL = 12 * 3600

# aweme_id 提取：/video/<id> 或 /note/<id>
_AWEME_RE = re.compile(r"/(?:video|note)/(\d{15,20})")


class _State:
    """模块级可变状态：全局会话、浏览器指纹、ttwid 缓存。"""

    session: Optional[AsyncSession] = None
    fp: str = ""
    ttwid: str = ""
    ttwid_ts: float = 0.0


def _get_session() -> AsyncSession:
    if _State.session is None:
        _State.session = AsyncSession(
            headers={"User-Agent": _WEB_UA, "Referer": "https://www.douyin.com/"},
            impersonate="chrome",
            timeout=_TIMEOUT,
        )
    return _State.session


def _get_fp() -> str:
    if not _State.fp:
        _State.fp = BrowserFingerprintGenerator.generate_fingerprint("Edge")
    return _State.fp


async def _get_ttwid() -> Optional[str]:
    """注册并缓存 ttwid cookie。"""
    now = time.monotonic()
    if _State.ttwid and now - _State.ttwid_ts < _TTWID_TTL:
        return _State.ttwid
    try:
        session = _get_session()
        resp = await session.post(
            "https://ttwid.bytedance.com/ttwid/union/register/",
            headers={"Content-Type": "application/json; charset=utf-8"},
            json={
                "region": "cn",
                "aid": 1768,
                "needFid": False,
                "service": "www.douyin.com",
                "migrate_info": {"ticket": "", "source": "node"},
                "cbUrlProtocol": "https",
                "union": True,
            },
        )
        ttwid = resp.cookies.get("ttwid")
        if not ttwid:
            logger.error("[抖音逆向] ttwid 注册失败：响应无 ttwid cookie")
            return None
        _State.ttwid = str(ttwid)
        _State.ttwid_ts = now
        logger.info("[抖音逆向] ttwid 已更新")
        return _State.ttwid
    except Exception as e:
        logger.error(f"[抖音逆向] ttwid 注册异常: {e}")
        return None


def _is_douyin_host(host: Optional[str]) -> bool:
    """host 必须是 douyin.com 或其子域（SSRF 防护：拒绝任意域名）。"""
    host = (host or "").lower()
    return host == "douyin.com" or host.endswith(".douyin.com")


async def _resolve_aweme_id(url: str) -> Optional[str]:
    """
    从链接解析 aweme_id：
    - 短链 v.douyin.com/xxx → 跟随重定向到 /video/<id> 或 /note/<id>
    - 完整链接 www.douyin.com/video/<id> 直接提取

    SSRF 防护：输入 URL 与重定向后的最终 URL 都必须是指定抖音域，
    且经 input_validator 拒绝内网/回环地址（与 get_real_url 同策略）。
    """
    m = _AWEME_RE.search(url)
    if m:
        parsed = urlparse(url)
        if _is_douyin_host(parsed.hostname) and input_validator.validate_http_url(url):
            return m.group(1)
        logger.warning(f"[抖音逆向] 拒绝非抖音域完整链接: {url[:120]}")
        return None

    try:
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower()
        if host != "v.douyin.com" and not host.endswith(".v.douyin.com"):
            logger.warning(f"[抖音逆向] 拒绝非 v.douyin.com 短链: {url[:120]}")
            return None
        session = _get_session()
        resp = await session.get(url, allow_redirects=True)
        final_url = str(resp.url)
        # 重定向后的最终地址必须仍是抖音域且非内网
        if not input_validator.validate_http_url(final_url):
            logger.warning(f"[抖音逆向] 重定向目标不通过 SSRF 校验: {final_url[:120]}")
            return None
        fparsed = urlparse(final_url)
        if not _is_douyin_host(fparsed.hostname):
            logger.warning(f"[抖音逆向] 短链重定向到非抖音域: {final_url[:120]}")
            return None
        m = _AWEME_RE.search(final_url)
        if not m:
            logger.warning(f"[抖音逆向] 短链重定向到非视频页: {final_url[:120]}")
            return None
        return m.group(1)
    except Exception as e:
        logger.error(f"[抖音逆向] 短链重定向异常: {e}")
        return None


def _build_params(aweme_id: str, fp: str) -> str:
    """构造 detail 接口 query 参数（顺序敏感，a_bogus 对整串签名）。"""
    return (
        f"aweme_id={aweme_id}&aid=6383&device_platform=web&channel=channel_pc_web"
        f"&pc_client_type=1&version_code=170400&version_name=17.4.0&cookie_enabled=true"
        f"&platform=PC&downlink=10&browser_name=Chrome&browser_language=zh-CN"
        f"&browser_platform=Win32&browser_version=126.0.0.0&browser_online=true"
        f"&engine_name=Blink&os_name=Windows&os_version=10&cpu_core_num=16&device_memory=8"
        f"&screen_width=1920&screen_height=1080&screen_scale=1&browser_fp={fp}"
        f"&ac=4g&network_type=wifi&priority_region=CN"
    )


def _first_url(url_list) -> str:
    """从 url_list 数组取第一个 URL。"""
    if isinstance(url_list, list) and url_list:
        return str(url_list[0])
    return ""


def _extract_result(item: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """把 aweme_detail 整理成与现有 parse() 一致的 result dict。"""
    if not isinstance(item, dict):
        return None

    author = item.get("author") or {}
    if not isinstance(author, dict):
        author = {}
    stats = item.get("statistics") or {}
    if not isinstance(stats, dict):
        stats = {}
    video = item.get("video") or {}
    if not isinstance(video, dict):
        video = {}

    # 图集/图文：images 数组（优先）；否则视频直链
    images = []
    for img in item.get("images") or []:
        url = _first_url((img or {}).get("url_list"))
        if url:
            images.append(url)

    cover = _first_url((video.get("cover") or {}).get("url_list")) or (
        images[0] if images else ""
    )
    avatar = (
        _first_url((author.get("avatar_larger") or {}).get("url_list"))
        or _first_url((author.get("avatar_thumb") or {}).get("url_list"))
        or ""
    )

    music = {}
    m = item.get("music") or {}
    if isinstance(m, dict):
        m_title = m.get("title") or ""
        m_url = _first_url((m.get("play_url") or {}).get("url_list"))
        if m_title or m_url:
            music = {"title": m_title, "author": m.get("author") or "", "url": m_url}

    base = {
        "nickname": author.get("nickname") or "未知作者",
        "desc": item.get("desc") or item.get("caption") or "无描述",
        "aweme_id": str(item.get("aweme_id") or ""),
        "like": stats.get("digg_count") or 0,
        "cover": cover,
        "time": item.get("create_time") or 0,
        "author_avatar": avatar,
        "music": music,
    }

    if images:
        return {"type": "image", "video_url": "", "video_url_HQ": "", "images": images, **base}

    video_url = _first_url((video.get("play_addr") or {}).get("url_list"))
    if not video_url:
        # 部分作品 play_addr 为空，尝试 bit_rate 里的地址
        for br in video.get("bit_rate") or []:
            video_url = _first_url((br or {}).get("play_addr", {}).get("url_list"))
            if video_url:
                break
    if not video_url:
        logger.error("[抖音逆向] detail 返回无视频直链也无图集")
        return None

    return {"type": "video", "video_url": video_url, "video_url_HQ": video_url, "images": [], **base}


async def parse_douyin_web(url: str) -> Optional[Dict[str, Any]]:
    """
    网页版逆向解析入口。返回统一 result dict；任何失败返回 None。
    """
    ttwid = await _get_ttwid()
    if not ttwid:
        return None

    aweme_id = await _resolve_aweme_id(url)
    if not aweme_id:
        return None

    fp = _get_fp()
    params = _build_params(aweme_id, fp)
    ab = ABogus(fp=fp, user_agent=_WEB_UA)
    signed_params, _, _, _ = ab.generate_abogus(params, "")

    try:
        session = _get_session()
        resp = await session.get(
            f"https://www.douyin.com/aweme/v1/web/aweme/detail?{signed_params}",
            headers={"Cookie": f"ttwid={ttwid}"},
        )
        if resp.status_code != 200:
            logger.error(f"[抖音逆向] detail HTTP {resp.status_code}")
            return None
        body = resp.text
        if not body or '"aweme_detail"' not in body:
            logger.warning("[抖音逆向] detail 返回空/被风控（签名失效或频率过高）")
            return None
        data = resp.json()
        item = data.get("aweme_detail")
        result = _extract_result(item)
        if result:
            logger.info(
                f"[抖音逆向] 解析成功 {result['type']} "
                f"aweme_id={result['aweme_id']} 耗时<{_TIMEOUT}s"
            )
        return result
    except Exception as e:
        logger.error(f"[抖音逆向] detail 请求异常: {e}")
        return None
