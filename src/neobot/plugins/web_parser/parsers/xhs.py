# -*- coding: utf-8 -*-
import json
import re
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import aiohttp
import orjson

from neobot.core.utils.logger import logger
from neobot.core.utils.input_validator import input_validator
from neobot.core.services.local_file_server import download_to_local
from neobot.models import MessageEvent, MessageSegment
from ..base import BaseParser
from ..utils import extract_original_text
from cachetools import TTLCache

# 小红书解析器（纯 HTTP，无需第三方解析 API / 密钥）
#
# 思路（对标 Node 版实现）：小红书笔记页是服务端渲染的，整个笔记载荷以普通 JS
# 赋值语句 `window.__INITIAL_STATE__={...}` 内联在 HTML 里（不是
# <script type="application/json"> 元素）。抓到 HTML 后做花括号配平取出这段
# JSON（载荷含 `:undefined` 哨兵，需先替换成 null 才能解析），就能拿到标题、
# 作者、视频直链或图集图片，无需浏览器、无需第三方接口。
#
# 两种笔记形态：
#   1. 视频笔记 —— 签名 MP4 在 note.video.media.stream.h264[]（h265 兜底）
#   2. 图文笔记 —— N 张图片在 note.imageList[]，按图集发送（对齐抖音流程）
#
# 媒体直链在 CDN 上有 Referer 防盗链，下载必须带
# `Referer: https://www.xiaohongshu.com/`，走本地文件服务器中转。

MOBILE_UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
)
# 实测（2026-08）：移动 UA 抓 explore 页会被 xhs_sec_server 风控拦截，
# 返回 ~21KB 无笔记数据的空壳；桌面 UA 能拿到完整 SSR 载荷（~900KB）。
# 所以桌面 UA 优先，移动 UA 仅作兜底。
DESKTOP_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)
XHS_REFERER = "https://www.xiaohongshu.com/"

# 长链接：explore / discovery/item / user/profile/{uid}/{noteId}
XHS_URL_RE = re.compile(
    r"https?://(?:www\.)?xiaohongshu\.com/"
    r"(?:explore|discovery/item|user/profile/[^\s/]+)/[A-Za-z0-9]+(?:\?[^\s]*)?"
)
# 短链接：App 内分享默认 xhslink.com，也存在 xhslink.cn；路径有 AbC123 和 o/AbC123 两种
XHS_SHORT_RE = re.compile(r"https?://xhslink\.(?:com|cn)/[A-Za-z0-9/]+")
NOTE_ID_RE = re.compile(r"xiaohongshu\.com/(?:explore|discovery/item)/([A-Za-z0-9]+)")


class XhsParser(BaseParser):
    """小红书笔记解析器（视频 / 图集）。"""

    # 解析失败重试：最多尝试 3 次，全部失败才报错
    max_parse_attempts = 3

    def __init__(self):
        super().__init__()
        self.name = "小红书解析器"
        self.nickname = "小红书笔记解析"
        self.url_pattern = re.compile(
            r"https?://(?:www\.)?xiaohongshu\.com/"
            r"(?:explore|discovery/item|user/profile/[^\s/]+)/[A-Za-z0-9]+(?:\?[^\s]*)?"
            r"|https?://xhslink\.(?:com|cn)/[A-Za-z0-9/]+"
        )
        # 消息去重缓存（防止同一消息重复上报被多次解析）
        self.processed_messages: TTLCache[int, bool] = TTLCache(maxsize=100, ttl=10)

    def is_short_url(self, url: str) -> bool:
        """xhslink.com / xhslink.cn 短链接。"""
        return "xhslink." in url

    def should_handle_url(self, url: str) -> bool:
        return bool(XHS_URL_RE.search(url) or XHS_SHORT_RE.search(url))

    async def get_real_url(self, short_url: str) -> Optional[str]:
        """跟随 xhslink 短链接的 302 重定向，返回真实笔记页 URL。"""
        try:
            session = self.get_session()
            headers = dict(self.HEADERS)
            headers["User-Agent"] = DESKTOP_UA
            async with session.get(
                short_url,
                allow_redirects=True,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=15),
            ) as response:
                redirected_url = str(response.url)

                # 精确校验重定向后的主机名（防止伪造 host 子串绕过）
                parsed = urlparse(redirected_url)
                host = (parsed.hostname or "").lower()
                if not input_validator.validate_http_url(redirected_url):
                    logger.warning(
                        f"[{self.name}] 短链接重定向到非 http(s) 或不安全地址，拒绝: {redirected_url}"
                    )
                    return None
                is_xhs_host = host == "xiaohongshu.com" or host.endswith(".xiaohongshu.com")
                is_note_path = (
                    parsed.path.startswith("/explore/")
                    or parsed.path.startswith("/discovery/")
                    or "/user/profile/" in parsed.path
                )
                if is_xhs_host and is_note_path:
                    logger.info(f"[{self.name}] 成功获取真实URL: {redirected_url}")
                    return redirected_url
                logger.warning(
                    f"[{self.name}] 短链接 {short_url} 重定向到了非预期页面: {redirected_url}"
                )
                return None
        except Exception as e:
            logger.error(f"[{self.name}] 获取真实URL失败: {e}")
        return None

    async def parse(self, url: str) -> Optional[Dict[str, Any]]:
        """抓取笔记页 HTML，提取 SSR 内联 JSON 并解析出笔记信息。"""
        try:
            html = await self._fetch_html(url)
            if not html:
                return None
            raw_json = extract_initial_state_json(html)
            if not raw_json:
                logger.warning(f"[{self.name}] 页面未找到 __INITIAL_STATE__ 载荷")
                return None
            return parse_note_json(raw_json)
        except Exception as e:
            logger.error(f"[{self.name}] 解析失败: {type(e).__name__}: {e}")
            return None

    async def _fetch_html(self, url: str) -> Optional[str]:
        """抓取笔记页 HTML（桌面 UA 优先，移动 UA 兜底，降低风控概率）。"""
        for ua in (DESKTOP_UA, MOBILE_UA):
            try:
                session = self.get_session()
                headers = dict(self.HEADERS)
                headers.update(
                    {
                        "User-Agent": ua,
                        "Referer": XHS_REFERER,
                        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                        "Accept-Language": "zh-CN,zh;q=0.9",
                    }
                )
                async with session.get(
                    url,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=20),
                ) as response:
                    if response.status != 200:
                        logger.warning(
                            f"[{self.name}] 页面请求失败，状态码: {response.status} (ua={ua[:20]}...)"
                        )
                        continue
                    return await response.text()
            except Exception as e:
                logger.warning(f"[{self.name}] 页面请求异常: {type(e).__name__}: {e} (ua={ua[:20]}...)")
        return None

    async def format_response(self, event: MessageEvent, data: Dict[str, Any]) -> List[Any]:
        """格式化小红书笔记响应消息（对齐抖音解析的转发卡片流程）。"""
        original_text = extract_original_text(event.message, self.url_pattern)

        text_parts = ["小红书笔记解析"]
        text_parts.append("--------------------")
        if original_text:
            text_parts.append(f" 分享内容: {original_text}")
            text_parts.append("--------------------")
        text_parts.append(f" 作者: {data['nickname']}")
        text_parts.append(f" 标题: {data['desc']}")
        if data.get("type") == "image":
            text_parts.append(f" 类型: 图集（{len(data['images'])} 张）")
        else:
            text_parts.append(" 类型: 视频")
        text_parts.append("--------------------")
        text_message = "\n".join(text_parts)

        nodes = []
        text_node = event.bot.build_forward_node(
            user_id=event.self_id,
            nickname=self.nickname,
            message=text_message,
        )
        nodes.append(text_node)

        media_success = False

        if data.get("type") == "image" and isinstance(data.get("images"), list) and data["images"]:
            # ---- 图集：每张图片单独一个转发节点（CDN 防盗链，逐张本地中转）----
            images = data["images"]
            logger.info(f"[{self.name}] 发送图集，共 {len(images)} 张")
            for idx, img_url in enumerate(images, 1):
                try:
                    local_url = await self._download_media(img_url)
                    img_node = event.bot.build_forward_node(
                        user_id=event.self_id,
                        nickname=self.nickname,
                        message=[
                            MessageSegment.text(f"图集第 {idx}/{len(images)} 张：\n"),
                            MessageSegment.image(local_url or img_url),
                        ],
                    )
                    nodes.append(img_node)
                except Exception as e:
                    logger.warning(f"[{self.name}] 无法添加图集第 {idx} 张: {e}")
            media_success = True
        else:
            # ---- 视频（媒体只在合并转发内展示，不单独直接发）----
            try:
                video_url = data.get("video_url")
                if video_url:
                    local_url = await self._download_media(video_url)
                    video_message = MessageSegment.video(local_url or video_url)
                    video_node = event.bot.build_forward_node(
                        user_id=event.self_id,
                        nickname=self.nickname,
                        message=[MessageSegment.text("视频直链：\n"), video_message],
                    )
                    nodes.append(video_node)
                    media_success = True
            except Exception as e:
                logger.error(f"[{self.name}] 无法添加视频: {e}")

        if not media_success:
            no_media_node = event.bot.build_forward_node(
                user_id=event.self_id,
                nickname=self.nickname,
                message="解析成功，但无法获取媒体直链。",
            )
            nodes.append(no_media_node)

        return nodes

    async def _download_media(self, url: str) -> Optional[str]:
        """带 Referer 防盗链头走本地文件服务器中转下载；失败回退直链。"""
        try:
            local_url = await download_to_local(
                url, timeout=120, headers={"Referer": XHS_REFERER}
            )
            if local_url:
                logger.info(f"[{self.name}] 媒体已中转下载到本地: {local_url}")
            return local_url
        except Exception as e:
            logger.warning(f"[{self.name}] 媒体中转下载失败，回退直链: {e}")
            return None


# ─── 纯解析函数（便于单测）───────────────────────────────────────────────────────


def extract_note_id(url: str) -> Optional[str]:
    """从长链接中提取笔记 ID。"""
    m = NOTE_ID_RE.search(url)
    return m.group(1) if m else None


def extract_initial_state_json(html: str) -> Optional[str]:
    """从 HTML 中提取 `window.__INITIAL_STATE__={...}` 的 JSON 文本。

    XHS 的 SSR 载荷以普通 JS 赋值语句内联（不是 <script type="application/json">），
    只能从起始 `{` 做花括号配平（跳过字符串字面量，避免引号里的 `{`/`}` 干扰）
    找到配对的右括号。载荷里含 `:undefined` 哨兵（SSR 未清洗），JSON 解析会失败，
    解析前统一替换成 `:null`。取不到返回 None。
    """
    marker = "window.__INITIAL_STATE__="
    marker_idx = html.find(marker)
    if marker_idx < 0:
        return None
    start = html.find("{", marker_idx + len(marker))
    if start < 0:
        return None

    depth = 0
    in_str = None
    escape = False
    for i in range(start, len(html)):
        ch = html[i]
        if in_str:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == in_str:
                in_str = None
            continue
        if ch in ('"', "'"):
            in_str = ch
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                raw = html[start : i + 1]
                return re.sub(r":\s*undefined\b", ":null", raw)
    return None


def parse_note_json(raw_json: str) -> Optional[Dict[str, Any]]:
    """解析 SSR 载荷 JSON，返回统一结构的笔记信息字典。"""
    try:
        data = orjson.loads(raw_json)
    except Exception:
        try:
            data = json.loads(raw_json)
        except Exception as e:
            logger.error(f"[小红书解析器] 载荷 JSON 解析失败: {e}")
            return None

    note = None
    # 1. noteDetailMap：取第一个值里的 note 字段
    note_detail_map = deep_find(data, "noteDetailMap")
    if isinstance(note_detail_map, dict):
        first = next(iter(note_detail_map.values()), None)
        if isinstance(first, dict):
            note = first.get("note")
    # 2. 深度遍历找 note 对象（title + video/imageList + user 特征）
    if not isinstance(note, dict):
        note = deep_find_note(data)
    if not isinstance(note, dict):
        return None
    return parse_note_object(note)


def parse_note_object(note: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """从单个 note 对象提取标题/作者/视频直链或图集图片。"""
    title = pick_title(note.get("title"), note.get("desc"))
    user = note.get("user") or {}
    author = user.get("nickname") or user.get("nickName") or "未知作者"

    video_url = pick_video_url(note.get("video"))
    if video_url:
        return {
            "type": "video",
            "video_url": video_url,
            "video_url_HQ": video_url,
            "nickname": author,
            "desc": title,
            "aweme_id": "",
            "like": 0,
            "cover": "",
            "time": 0,
            "author_avatar": "",
            "music": {},
            "images": [],
        }

    images = pick_image_urls(note.get("imageList"))
    if images:
        return {
            "type": "image",
            "video_url": "",
            "video_url_HQ": "",
            "nickname": author,
            "desc": title,
            "aweme_id": "",
            "like": 0,
            "cover": "",
            "time": 0,
            "author_avatar": "",
            "music": {},
            "images": images,
        }

    logger.warning("[小红书解析器] note 既无视频也无图片")
    return None


def pick_title(raw_title: Optional[str], raw_desc: Optional[str]) -> str:
    """标题选取：title 优先；图文笔记 title 常为空，退到 desc 第一非空行。

    去掉 `[话题]#` 标记（XHS 内部的话题类型标记，从不展示给用户），
    超过 60 字截断。
    """
    cleaned = lambda s: re.sub(r"\[话题\]#", "#", s).strip()
    t = (raw_title or "").strip()
    if t:
        return cleaned(t)
    first_line = ""
    for line in (raw_desc or "").splitlines():
        line = line.strip()
        if line:
            first_line = line
            break
    c = cleaned(first_line)
    return c if len(c) <= 60 else c[:60] + "…"


def pick_video_url(video: Any) -> str:
    """从 note.video.media.stream.h264/h265 里挑最小清晰度直链。"""
    if not isinstance(video, dict):
        return ""
    stream = (video.get("media") or {}).get("stream") or {}
    candidates = []
    for key in ("h264", "h265"):
        for item in stream.get(key) or []:
            if isinstance(item, dict) and (
                item.get("masterUrl") or (item.get("backupUrls") or [None])[0]
            ):
                candidates.append(item)
    candidates.sort(key=lambda c: (c.get("size") or c.get("weight") or 0))
    if not candidates:
        return ""
    c = candidates[0]
    url = c.get("masterUrl") or (c.get("backupUrls") or [""])[0] or ""
    return url.replace("http://", "https://") if url else ""


def pick_image_urls(image_list: Any) -> List[str]:
    """从 note.imageList 提取图片直链（urlDefault / url / infoList 兜底）。"""
    if not isinstance(image_list, list):
        return []
    urls = []
    for img in image_list:
        if not isinstance(img, dict):
            continue
        url = img.get("urlDefault") or img.get("url") or ""
        if not url:
            for info in img.get("infoList") or []:
                if isinstance(info, dict) and info.get("url"):
                    url = info["url"]
                    break
        if url:
            urls.append(url.replace("http://", "https://"))
    return urls


def deep_find(root: Any, key: str, depth: int = 0) -> Any:
    """深度优先查找指定 key 的子对象（如 noteDetailMap）。"""
    if not isinstance(root, dict) or depth > 8:
        return None
    if key in root:
        return root[key]
    for value in root.values():
        found = deep_find(value, key, depth + 1)
        if found is not None:
            return found
    return None


def deep_find_note(root: Any, depth: int = 0) -> Optional[Dict[str, Any]]:
    """深度优先找含 title + video/imageList + user 特征的 note 对象。"""
    if not isinstance(root, dict) or depth > 8:
        return None
    if (
        isinstance(root.get("title"), str)
        and ("video" in root or "imageList" in root)
        and "user" in root
    ):
        return root
    for value in root.values():
        found = deep_find_note(value, depth + 1)
        if found:
            return found
    return None
