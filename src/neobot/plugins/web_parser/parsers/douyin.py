# -*- coding: utf-8 -*-
import re
import time
import aiohttp
import asyncio
from typing import Optional, Dict, Any, List
from urllib.parse import urlparse

from neobot.core.utils.logger import logger
from neobot.core.utils.input_validator import input_validator
from neobot.core.config_loader import global_config as config
from neobot.core.services.local_file_server import download_to_local
from neobot.models import MessageEvent, MessageSegment
from ..base import BaseParser
from ..utils import extract_original_text
from .douyin_web import parse_douyin_web
from cachetools import TTLCache


class DouyinParser(BaseParser):
    """
    抖音视频解析器
    """

    # 解析失败重试：最多尝试 3 次，全部失败才报错
    max_parse_attempts = 3
    
    def __init__(self):
        super().__init__()
        self.name = "抖音解析器"
        self.url_pattern = re.compile(r"https?://v\.douyin\.com/[a-zA-Z0-9_-]+/?", re.IGNORECASE)
        self.short_pattern = re.compile(r"(?:https?://)?v\.douyin\.com/[a-zA-Z0-9_-]+/?", re.IGNORECASE)
        self.nickname = "抖音视频解析"
        # 消息去重缓存
        self.processed_messages: TTLCache[int, bool] = TTLCache(maxsize=100, ttl=10)
    
    async def _parse_api_xhus(self, url: str) -> Optional[Dict[str, Any]]:
        """
        使用 xhus API 解析抖音视频/图集

        Args:
            url (str): 抖音视频URL

        Returns:
            Optional[Dict[str, Any]]: 视频信息字典，如果失败则返回None
        """
        try:
            api_url = f"http://api.xhus.cn/api/douyin?url={url}"

            session = self.get_session()
            async with session.get(api_url, headers=self.HEADERS, timeout=aiohttp.ClientTimeout(total=10)) as response:
                if response.status != 200:
                    logger.error(f"[{self.name}] xhus API请求失败，状态码: {response.status}")
                    return None

                response_data = await response.json()

            if not isinstance(response_data, dict):
                logger.error(f"[{self.name}] xhus API返回格式错误: {response_data}")
                return None

            if response_data.get("code") != 200:
                logger.error(f"[{self.name}] xhus API返回错误: {response_data}")
                return None

            data = response_data.get("data", {})
            if not data:
                logger.error(f"[{self.name}] xhus API返回数据为空")
                return None

            # 检测类型：images 为空列表 → 视频，有内容 → 图集
            image_list = data.get("images")
            is_image_set = isinstance(image_list, list) and len(image_list) > 0

            # 视频时 url 是播放地址；图集时 url 是无意义文本，真正有用的在 images 数组
            video_url = "" if is_image_set else data.get("url", "")

            result = {
                "type": "image" if is_image_set else "video",
                "video_url": video_url,
                "video_url_HQ": video_url,
                "nickname": data.get("author", "未知作者"),
                "desc": data.get("title", "无描述"),
                "aweme_id": data.get("uid", ""),
                "like": data.get("like", 0),
                "cover": data.get("cover", ""),
                "time": data.get("time", 0),
                "author_avatar": data.get("avatar", ""),
                "music": data.get("music", {}),
                "images": image_list if is_image_set else [],
            }

            if is_image_set:
                logger.info(f"[{self.name}] xhus 解析为图集，共 {len(image_list)} 张图片")
            return result

        except Exception as e:
            logger.error(f"[{self.name}] xhus API解析失败: {e}")
            return None

    async def _parse_api_local(self, url: str) -> Optional[Dict[str, Any]]:
        """
        使用 douyin2api 服务（https://dy-api.d1ck.top）解析抖音视频/图集。

        密钥从配置 `[douyin].api_key` 读取（也支持环境变量 DOUYIN_API_KEY），
        留空时跳过该通道，避免影响其余解析 API 的并发兜底。

        Args:
            url (str): 抖音视频URL

        Returns:
            Optional[Dict[str, Any]]: 视频信息字典，如果失败则返回None
        """
        try:
            api_key = (getattr(config.douyin, "api_key", "") or "").strip()
            if not api_key:
                logger.warning(f"[{self.name}] 未配置 douyin.api_key，跳过 douyin2api 解析通道")
                return None

            api_url = "https://dy-api.d1ck.top/api/parse"
            # 服务地址为固定公网 HTTPS 域名，无 SSRF 面

            headers = dict(self.HEADERS)
            headers["Content-Type"] = "application/json"
            headers["X-API-Key"] = api_key

            session = self.get_session()
            async with session.post(
                api_url,
                headers=headers,
                json={"url": url},
                timeout=aiohttp.ClientTimeout(total=15),
            ) as response:
                if response.status == 401:
                    logger.error(f"[{self.name}] douyin2api 鉴权失败（401），请检查 config [douyin].api_key")
                    return None
                if response.status != 200:
                    logger.error(f"[{self.name}] douyin2api 请求失败，状态码: {response.status}")
                    return None
                response_data = await response.json()

            if not isinstance(response_data, dict) or not response_data.get("success"):
                code = response_data.get("code") if isinstance(response_data, dict) else None
                message = response_data.get("message") if isinstance(response_data, dict) else ""
                logger.error(f"[{self.name}] douyin2api 返回错误: code={code}, message={message}")
                return None

            data = response_data.get("data")
            if not isinstance(data, dict):
                logger.error(f"[{self.name}] douyin2api: 缺少 data")
                return None

            base = {
                "nickname": data.get("author", "未知作者"),
                "desc": data.get("title", "无描述"),
                "aweme_id": data.get("author_uid", ""),
                "like": 0,
                "cover": data.get("cover_url", ""),
                "time": 0,
                "author_avatar": data.get("avatar_url", ""),
            }
            music_url = data.get("music_url") or ""

            # 图集：type=gallery 或 slides 非空
            slides = data.get("slides")
            if data.get("type") == "gallery" or (isinstance(slides, list) and slides):
                image_urls = []
                for slide in slides or []:
                    if isinstance(slide, dict) and slide.get("image_url"):
                        image_urls.append(slide["image_url"])
                if image_urls:
                    logger.info(f"[{self.name}] douyin2api 解析为图集，共 {len(image_urls)} 张图片")
                    return {
                        "type": "image",
                        "video_url": "",
                        "video_url_HQ": "",
                        "images": image_urls,
                        "music": {"url": music_url} if music_url else {},
                        **base,
                    }

            # 视频
            video_url = data.get("video_url", "")
            if not video_url or not isinstance(video_url, str):
                logger.error(f"[{self.name}] douyin2api: data.video_url 为空")
                return None

            return {
                "type": "video",
                "video_url": video_url,
                "video_url_HQ": video_url,
                "images": [],
                "music": {"url": music_url} if music_url else {},
                **base,
            }

        except Exception as e:
            logger.error(f"[{self.name}] douyin2api 解析失败: {e}")
            return None

    async def _parse_api_xinyew(self, url: str) -> Optional[Dict[str, Any]]:
        """
        使用 xinyew API 解析抖音视频
        返回格式: { "data": { "title": ..., "author": ..., "video_url": ... } }

        Args:
            url (str): 抖音视频URL

        Returns:
            Optional[Dict[str, Any]]: 视频信息字典，如果失败则返回None
        """
        try:
            api_url = f"https://api.xinyew.cn/api/douyinjx?url={url}"

            session = self.get_session()
            async with session.get(api_url, headers=self.HEADERS, timeout=aiohttp.ClientTimeout(total=15)) as response:
                if response.status != 200:
                    logger.error(f"[{self.name}] xinyew API请求失败，状态码: {response.status}")
                    return None

                response_data = await response.json()

            if not isinstance(response_data, dict):
                logger.error(f"[{self.name}] xinyew API返回格式错误: {response_data}")
                return None

            data = response_data.get("data")
            if not isinstance(data, dict):
                logger.error(f"[{self.name}] xinyew API: 缺少 data")
                return None

            video_url = data.get("video_url", "")
            if not video_url or not isinstance(video_url, str):
                logger.error(f"[{self.name}] xinyew API: data.video_url 为空")
                return None

            return {
                "type": "video",
                "video_url": video_url,
                "video_url_HQ": video_url,
                "nickname": data.get("author", "未知作者"),
                "desc": data.get("title", "无描述"),
                "aweme_id": "",
                "like": 0,
                "cover": "",
                "time": 0,
                "author_avatar": "",
                "music": {},
                "images": [],
            }

        except Exception as e:
            logger.error(f"[{self.name}] xinyew API解析失败: {e}")
            return None

    async def _parse_api_makuo(self, url: str) -> Optional[Dict[str, Any]]:
        """
        使用 makuo API 解析抖音视频

        Args:
            url (str): 抖音视频URL

        Returns:
            Optional[Dict[str, Any]]: 视频信息字典，如果失败则返回None
        """
        try:
            api_url = f"https://api.makuo.cc/api/get.video.douyin?token=MeCWQQbYm-8jsbsyoWNEug&url={url}&type=json"

            session = self.get_session()
            async with session.get(api_url, headers=self.HEADERS, timeout=aiohttp.ClientTimeout(total=15)) as response:
                if response.status != 200:
                    logger.error(f"[{self.name}] makuo API请求失败，状态码: {response.status}")
                    return None

                response_data = await response.json()

            if not isinstance(response_data, dict):
                logger.error(f"[{self.name}] makuo API返回格式错误: {response_data}")
                return None

            data = response_data.get("data")
            if not isinstance(data, dict):
                logger.error(f"[{self.name}] makuo API: 缺少 data")
                return None

            video_url = data.get("video_url", "")
            if not video_url or not isinstance(video_url, str):
                logger.error(f"[{self.name}] makuo API: data.video_url 为空")
                return None

            return {
                "type": "video",
                "video_url": video_url,
                "video_url_HQ": video_url,
                "nickname": data.get("author", "未知作者"),
                "desc": data.get("title", "无描述"),
                "aweme_id": "",
                "like": 0,
                "cover": "",
                "time": 0,
                "author_avatar": "",
                "music": {},
                "images": [],
            }

        except Exception as e:
            logger.error(f"[{self.name}] makuo API解析失败: {e}")
            return None
    
    async def _parse_api_qzqi_douyin(self, url: str) -> Optional[Dict[str, Any]]:
        """
        使用远梦API（https://api.qzqi.com）的 DouYinVideo 接口解析抖音内容，
        支持短视频 / 图集 / 实况（无水印）。

        密钥从配置 `[douyin].qzqi_api_key` 读取（也支持环境变量
        DOUYIN_QZQI_APIKEY），留空时跳过该通道。

        注意：该接口的响应字段文档未公开完整示例，本方法采用健壮容错解析，
        对常见的 data 包裹、video/images/live 字段做了多重兼容。

        Args:
            url (str): 抖音视频URL

        Returns:
            Optional[Dict[str, Any]]: 视频信息字典，如果失败则返回None
        """
        try:
            api_key = (getattr(config.douyin, "qzqi_api_key", "") or "").strip()
            if not api_key:
                logger.warning(
                    f"[{self.name}] 未配置 douyin.qzqi_api_key，跳过 qzqi DouYinVideo 解析通道"
                )
                return None

            api_url = "https://api.qzqi.com/api/v1/DouYinVideo"
            params = {"url": url, "apikey": api_key}

            session = self.get_session()
            async with session.get(
                api_url,
                params=params,
                headers=self.HEADERS,
                timeout=aiohttp.ClientTimeout(total=15),
            ) as response:
                if response.status != 200:
                    logger.error(f"[{self.name}] qzqi DouYinVideo 请求失败，状态码: {response.status}")
                    return None
                try:
                    response_data = await response.json()
                except Exception:
                    logger.error(f"[{self.name}] qzqi DouYinVideo 返回非JSON响应")
                    return None

            if not isinstance(response_data, dict):
                logger.error(f"[{self.name}] qzqi DouYinVideo 返回格式错误: {response_data}")
                return None

            # 提取业务数据：可能直接是 data 段，也可能整段就是数据
            data = response_data.get("data")
            if data is None:
                data = response_data
            if not isinstance(data, dict):
                logger.error(f"[{self.name}] qzqi DouYinVideo 缺少 data: {response_data}")
                return None

            # 通用字段提取（兼容多种命名）
            nickname = data.get("author") or data.get("author_name") or data.get("nickname") or "未知作者"
            desc = data.get("desc") or data.get("title") or data.get("content") or "无描述"
            cover = data.get("cover") or data.get("cover_url") or data.get("pic") or data.get("image") or ""
            like = data.get("like") or data.get("digg_count") or data.get("likes") or 0
            data_type = data.get("type") or data.get("aweme_type") or ""

            # 音乐：audio_url / music 字段统一整理
            audio_url = (
                data.get("audio_url")
                or (data.get("music") or {}).get("url")
                or (data.get("music") or {}).get("play_url")
                or ""
            )
            music = data.get("music") or {}
            if audio_url:
                music = {
                    "url": audio_url,
                    "title": (music.get("title") if isinstance(music, dict) else None) or data.get("music_title") or "",
                    "author": (music.get("author") if isinstance(music, dict) else None) or "",
                }

            # 视频直链（qzqi 完整格式：videos 数组或 video_url 单串）
            videos = data.get("videos")
            video_url = (
                data.get("video_url")
                or (videos[0] if isinstance(videos, list) and videos else "")
                or data.get("video")
                or data.get("url")
                or data.get("play_addr")
                or data.get("play_url")
                or ""
            ).strip()

            # 图集：images 列表 / pics / image_list / slides
            image_list = (
                data.get("images")
                or data.get("image_list")
                or data.get("pics")
                or data.get("slides")
                or []
            )
            image_urls = []
            for item in (image_list if isinstance(image_list, list) else []):
                if isinstance(item, str):
                    image_urls.append(item)
                elif isinstance(item, dict):
                    for k in ("url", "image_url", "src", "download_url"):
                        if item.get(k):
                            image_urls.append(item[k])
                            break

            # 类型判定：
            #   - 有视频直链时优先作为视频（含 live_photo 实况照片，动态效果更佳）
            #   - 否则若有图集图片则作为图集
            if video_url:
                return {
                    "type": "video",
                    "video_url": video_url,
                    "video_url_HQ": video_url,
                    "nickname": nickname,
                    "desc": desc,
                    "aweme_id": data.get("aweme_id") or data.get("id") or data.get("video_id") or "",
                    "like": like,
                    "cover": cover,
                    "time": data.get("time") or data.get("create_time") or 0,
                    "author_avatar": data.get("avatar") or data.get("author_avatar") or "",
                    "music": music,
                    "images": image_urls if data_type in ("image", "note", "live_photo") else [],
                }

            if image_urls:
                logger.info(f"[{self.name}] qzqi DouYinVideo 解析为图集，共 {len(image_urls)} 张图片")
                return {
                    "type": "image",
                    "video_url": "",
                    "video_url_HQ": "",
                    "nickname": nickname,
                    "desc": desc,
                    "aweme_id": data.get("aweme_id") or data.get("id") or data.get("video_id") or "",
                    "like": like,
                    "cover": cover,
                    "time": data.get("time") or data.get("create_time") or 0,
                    "author_avatar": data.get("avatar") or data.get("author_avatar") or "",
                    "music": music,
                    "images": image_urls,
                }

            logger.error(f"[{self.name}] qzqi DouYinVideo 未找到视频直链/图集")
            return None

        except Exception as e:
            logger.error(f"[{self.name}] qzqi DouYinVideo 解析失败: {e}")
            return None
    
    async def parse(self, url: str) -> Optional[Dict[str, Any]]:
        """
        解析抖音视频信息：优先尝试主解析通道（网页版逆向 → qzqi DouYinVideo），
        全部失败后才并发尝试备用通道（douyin2api / xinyew / xhus / makuo）。

        网页版逆向通道（2026-08 新增）：免费、端到端 ~0.8s（短链重定向 0.5s +
        API 0.26s + 签名 2ms），不依赖第三方限流，图文/视频/实况全支持。
        aiohttp 裸 TLS 会被风控吞响应，必须走 curl_cffi impersonate=chrome
        （见 douyin_web.py）。

        Args:
            url (str): 抖音视频URL

        Returns:
            Optional[Dict[str, Any]]: 视频信息字典，如果失败则返回None
        """
        # 解析整体超时（秒），对标 Java 版的 OVERALL_TIMEOUT_SECONDS
        overall_timeout = 60
        parse_start = time.monotonic()

        # ---- 主通道：依次串行尝试，命中即返回 ----
        primary_channels = [
            ("douyin_web", parse_douyin_web(url)),
            ("qzqi", self._parse_api_qzqi_douyin(url)),
        ]
        for idx, (api_name, coro) in enumerate(primary_channels):
            try:
                result = await coro
            except Exception as e:
                logger.error(f"[{self.name}] {api_name} API异常: {e}")
                result = None
            if result:
                # 关闭后续未执行的协程，避免 asyncio "never awaited" 泄漏警告
                for _, leftover in primary_channels[idx + 1:]:
                    leftover.close()
                logger.info(f"[{self.name}] 使用 {api_name} API 成功解析")
                result["_api_name"] = api_name
                result["_parse_cost_ms"] = int((time.monotonic() - parse_start) * 1000)
                return result

        # ---- 备用通道：并发兜底 ----
        async def try_api(coro, api_name: str) -> tuple:
            try:
                result = await coro
                return (result, api_name)
            except Exception as e:
                logger.error(f"[{self.name}] {api_name} API异常: {e}")
                return (None, api_name)

        tasks = [
            try_api(self._parse_api_local(url), "douyin2api"),
            try_api(self._parse_api_xinyew(url), "xinyew"),
            try_api(self._parse_api_xhus(url), "xhus"),
            try_api(self._parse_api_makuo(url), "makuo"),
        ]

        try:
            for coro in asyncio.as_completed(tasks, timeout=overall_timeout):
                try:
                    result, api_name = await coro
                except asyncio.TimeoutError:
                    logger.error(f"[{self.name}] 等待API结果超时")
                    break
                if result:
                    logger.info(f"[{self.name}] 使用 {api_name} API 成功解析")
                    result["_api_name"] = api_name
                    result["_parse_cost_ms"] = int((time.monotonic() - parse_start) * 1000)
                    return result
        except asyncio.TimeoutError:
            logger.error(f"[{self.name}] 所有API解析超过 {overall_timeout}s 未返回有效结果")

        logger.error(f"[{self.name}] 所有API解析均失败")
        return None
    
    async def get_real_url(self, short_url: str) -> Optional[str]:
        """
        获取抖音短链接的真实URL
        
        Args:
            short_url (str): 抖音短链接
            
        Returns:
            Optional[str]: 真实URL，如果失败则返回None
        """
        try:
            session = self.get_session()
            async with session.get(short_url, allow_redirects=True, timeout=aiohttp.ClientTimeout(total=10)) as response:
                redirected_url = str(response.url)
                
                # 精确校验重定向后的主机名（防止伪造 host 子串绕过，如 evil.com/douyin.com/video/…）
                parsed = urlparse(redirected_url)
                host = (parsed.hostname or "").lower()
                if not input_validator.validate_http_url(redirected_url):
                    logger.warning(f"[{self.name}] 短链接重定向到非 http(s) 或不安全地址，拒绝: {redirected_url}")
                    return None
                is_douyin_host = host == "douyin.com" or host.endswith(".douyin.com")
                # 检查重定向后的URL是否是有效的视频或图文页
                if is_douyin_host and ("/video/" in parsed.path or "/note/" in parsed.path):
                    logger.info(f"[{self.name}] 成功获取真实URL: {redirected_url}")
                    return redirected_url
                else:
                    logger.warning(f"[{self.name}] 短链接 {short_url} 重定向到了非预期的页面: {redirected_url}")
                    return None
                        
        except Exception as e:
            logger.error(f"[{self.name}] 获取真实URL失败: {e}")
        return None
    
    # 抖音 CDN 防盗链:下载必须带浏览器 UA + douyin Referer,
    # 否则生产环境(douyinvod/douyinpic)直接 403 拒绝裸请求
    _CDN_HEADERS = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
        "Referer": "https://www.douyin.com/",
    }

    async def format_response(self, event: MessageEvent, data: Dict[str, Any]) -> List[Any]:
        """
        格式化抖音视频响应消息
        
        Args:
            event (MessageEvent): 消息事件对象
            data (Dict[str, Any]): 视频信息
            
        Returns:
            List[Any]: 消息段列表
        """
        # 构建回复消息，包含原分享中的文本内容（如果有）
        original_text = extract_original_text(event.message, self.url_pattern)

        # 构建回复消息
        text_parts = ["抖音视频解析"]
        text_parts.append("--------------------")

        # 解析接口与耗时（parse() 注入的 _api_name / _parse_cost_ms）
        api_name = data.get("_api_name", "")
        cost_ms = int(data.get("_parse_cost_ms", 0) or 0)
        if api_name:
            api_display = {
                "douyin_web": "网页逆向",
                "qzqi": "远梦API",
                "douyin2api": "douyin2api",
                "xinyew": "xinyew",
                "xhus": "xhus",
                "makuo": "makuo",
            }.get(api_name, api_name)
            cost_str = f"{cost_ms / 1000:.1f}s" if cost_ms >= 1000 else f"{cost_ms}ms"
            text_parts.append(f" 解析接口: {api_display}")
            text_parts.append(f" 解析耗时: {cost_str}")
            text_parts.append("--------------------")
        
        if original_text:
            text_parts.append(f" 分享内容: {original_text}")
            text_parts.append("--------------------")
        
        text_parts.append(f" 作者: {data['nickname']}")
        text_parts.append(f" 抖音号: {data['aweme_id']}")
        text_parts.append(f" 标题: {data['desc']}")
        text_parts.append(f" 点赞: {self.format_count(data['like'])}")
        text_parts.append(f" 类型: {data['type']}")
        
        # 如果是音乐，添加音乐信息
        if data.get('music'):
            music_info = data['music']
            text_parts.append("--------------------")
            text_parts.append(" 背景音乐:")
            text_parts.append(f"    标题: {music_info.get('title', '')}")
            text_parts.append(f"    作者: {music_info.get('author', '')}")
        
        text_parts.append("--------------------")
        
        text_message = "\n".join(text_parts)
        
        # 准备转发消息节点
        nodes = []

        # 添加文本信息节点
        text_node = event.bot.build_forward_node(
            user_id=event.self_id, 
            nickname=self.nickname, 
            message=text_message
        )
        nodes.append(text_node)

        # 添加封面图片节点（如果有）
        if data.get('cover'):
            try:
                cover_url = data['cover']
                try:
                    cover_url = (await download_to_local(cover_url, timeout=30, headers=self._CDN_HEADERS)) or cover_url
                except Exception:
                    pass
                cover_node = event.bot.build_forward_node(
                    user_id=event.self_id, 
                    nickname=self.nickname, 
                    message=[
                        MessageSegment.text("抖音视频封面：\n"),
                        MessageSegment.image(cover_url)
                    ]
                )
                nodes.append(cover_node)
            except Exception as e:
                logger.warning(f"[{self.name}] 无法添加封面图片: {e}")

        # 添加作者头像节点（如果有）
        if data.get('author_avatar'):
            try:
                avatar_url = data['author_avatar']
                try:
                    avatar_url = (await download_to_local(avatar_url, timeout=30, headers=self._CDN_HEADERS)) or avatar_url
                except Exception:
                    pass
                avatar_node = event.bot.build_forward_node(
                    user_id=event.self_id, 
                    nickname=self.nickname, 
                    message=[
                        MessageSegment.text("作者头像：\n"),
                        MessageSegment.image(avatar_url)
                    ]
                )
                nodes.append(avatar_node)
            except Exception as e:
                logger.warning(f"[{self.name}] 无法添加作者头像: {e}")

        # 添加媒体内容节点（视频直链 / 图集图片）
        media_success = False
        direct_message = None

        if data.get('type') == 'image' and isinstance(data.get('images'), list) and data['images']:
            # ---- 图集：每张图片单独一个转发节点（同样走本地中转防防盗链 403）----
            images = data['images']
            logger.info(f"[{self.name}] 发送图集，共 {len(images)} 张")
            local_images = []
            for img_url in images:
                try:
                    local_url = await download_to_local(img_url, timeout=60, headers=self._CDN_HEADERS)
                    local_images.append(local_url or img_url)
                except Exception:
                    local_images.append(img_url)
            for idx, img_url in enumerate(local_images, 1):
                try:
                    img_node = event.bot.build_forward_node(
                        user_id=event.self_id,
                        nickname=self.nickname,
                        message=[
                            MessageSegment.text(f"图集第 {idx}/{len(local_images)} 张：\n"),
                            MessageSegment.image(img_url)
                        ]
                    )
                    nodes.append(img_node)
                except Exception as e:
                    logger.warning(f"[{self.name}] 无法添加图集第 {idx} 张: {e}")
            # 直接发送第一张
            if local_images:
                try:
                    await event.reply(MessageSegment.image(local_images[0]))
                except Exception as e:
                    logger.error(f"[{self.name}] 直接发送图集首图失败: {e}")
            media_success = True
            direct_message = MessageSegment.image(local_images[0]) if local_images else None

        else:
            # ---- 视频 ----
            try:
                if data.get('video_url'):
                    video_url = data['video_url']
                    # 先尝试下载到本地文件服务器中转（NapCat 独立容器时，直链可能
                    # 因防盗链/时效无法直接下载）；失败则回退原始直链
                    try:
                        local_url = await download_to_local(video_url, timeout=120, headers=self._CDN_HEADERS)
                        if local_url:
                            logger.info(f"[{self.name}] 视频已中转下载到本地: {local_url}")
                            video_url = local_url
                    except Exception as e:
                        logger.warning(f"[{self.name}] 视频中转下载失败，回退直链: {e}")
                    video_message = MessageSegment.video(video_url)
                    direct_message = video_message

                    video_node = event.bot.build_forward_node(
                        user_id=event.self_id,
                        nickname=self.nickname,
                        message=[
                            MessageSegment.text("视频直链：\n"),
                            video_message
                        ]
                    )
                    nodes.append(video_node)
                    media_success = True
            except Exception as e:
                logger.error(f"[{self.name}] 无法添加视频: {e}")

        if not media_success:
            no_media_node = event.bot.build_forward_node(
                user_id=event.self_id,
                nickname=self.nickname,
                message="解析成功，但无法获取媒体直链。"
            )
            nodes.append(no_media_node)

        # 同时直接发送媒体（如果获取到直链）
        if direct_message:
            try:
                await event.reply(direct_message)
            except Exception as e:
                logger.error(f"[{self.name}] 直接发送媒体失败: {e}")

        return nodes
    
    def should_handle_url(self, url: str) -> bool:
        """
        判断是否应该处理该URL
        
        Args:
            url (str): URL
            
        Returns:
            bool: 是否应该处理
        """
        # 检查是否是抖音相关域名
        return ('douyin.com' in url or bool(self.url_pattern.search(url)) or bool(self.short_pattern.search(url)))
