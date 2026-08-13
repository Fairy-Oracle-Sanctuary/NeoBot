# -*- coding: utf-8 -*-
import re
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
    
    async def _parse_api_mmp(self, url: str) -> Optional[Dict[str, Any]]:
        """
        使用 mmp API 解析抖音视频/图集

        Args:
            url (str): 抖音视频URL

        Returns:
            Optional[Dict[str, Any]]: 视频信息字典，如果失败则返回None
        """
        try:
            api_url = f"https://api.mmp.cc/api/Jiexi?url={url}"

            session = self.get_session()
            async with session.get(api_url, headers=self.HEADERS, timeout=aiohttp.ClientTimeout(total=10)) as response:
                if response.status != 200:
                    logger.error(f"[{self.name}] mmp API请求失败，状态码: {response.status}")
                    return None

                response_data = await response.json()

            if not isinstance(response_data, dict):
                logger.error(f"[{self.name}] mmp API返回格式错误: {response_data}")
                return None

            if response_data.get("code") != 200:
                logger.error(f"[{self.name}] mmp API返回错误: {response_data}")
                return None

            data = response_data.get("data", {})
            if not data:
                logger.error(f"[{self.name}] mmp API返回数据为空")
                return None

            data_type = data.get("type", "video")

            # 图集: images 字段
            image_list = data.get("images")
            is_image_set = data_type == "image" or (isinstance(image_list, list) and len(image_list) > 0)

            if is_image_set:
                image_urls = image_list if isinstance(image_list, list) else []
                if image_urls:
                    logger.info(f"[{self.name}] mmp 解析为图集，共 {len(image_urls)} 张图片")
                return {
                    "type": "image",
                    "video_url": "",
                    "video_url_HQ": "",
                    "nickname": data.get("nickname", "未知作者"),
                    "desc": data.get("desc", "无描述"),
                    "aweme_id": data.get("aweme_id", ""),
                    "like": data.get("like", 0),
                    "cover": data.get("cover", ""),
                    "time": data.get("time", 0),
                    "author_avatar": data.get("author_avatar", ""),
                    "music": data.get("music", {}),
                    "images": image_urls,
                }

            # 视频
            return {
                "type": "video",
                "video_url": data.get("video_url", ""),
                "video_url_HQ": data.get("video_url_HQ", ""),
                "nickname": data.get("nickname", "未知作者"),
                "desc": data.get("desc", "无描述"),
                "aweme_id": data.get("aweme_id", ""),
                "like": data.get("like", 0),
                "cover": data.get("cover", ""),
                "time": data.get("time", 0),
                "author_avatar": data.get("author_avatar", ""),
                "music": data.get("music", {}),
                "images": [],
            }

        except Exception as e:
            logger.error(f"[{self.name}] mmp API解析失败: {e}")
            return None
    
    async def parse(self, url: str) -> Optional[Dict[str, Any]]:
        """
        解析抖音视频信息（并发请求多个API，取最快返回的有效结果）

        Args:
            url (str): 抖音视频URL

        Returns:
            Optional[Dict[str, Any]]: 视频信息字典，如果失败则返回None
        """
        # 解析整体超时（秒），对标 Java 版的 OVERALL_TIMEOUT_SECONDS
        overall_timeout = 60

        async def try_api(coro, api_name: str) -> tuple:
            try:
                result = await coro
                return (result, api_name)
            except Exception as e:
                logger.error(f"[{self.name}] {api_name} API异常: {e}")
                return (None, api_name)

        tasks = [
            try_api(self._parse_api_local(url), "local"),
            try_api(self._parse_api_xinyew(url), "xinyew"),
            try_api(self._parse_api_makuo(url), "makuo"),
            try_api(self._parse_api_xhus(url), "xhus"),
            try_api(self._parse_api_mmp(url), "mmp"),
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
                cover_node = event.bot.build_forward_node(
                    user_id=event.self_id, 
                    nickname=self.nickname, 
                    message=[
                        MessageSegment.text("抖音视频封面：\n"),
                        MessageSegment.image(data['cover'])
                    ]
                )
                nodes.append(cover_node)
            except Exception as e:
                logger.warning(f"[{self.name}] 无法添加封面图片: {e}")

        # 添加作者头像节点（如果有）
        if data.get('author_avatar'):
            try:
                avatar_node = event.bot.build_forward_node(
                    user_id=event.self_id, 
                    nickname=self.nickname, 
                    message=[
                        MessageSegment.text("作者头像：\n"),
                        MessageSegment.image(data['author_avatar'])
                    ]
                )
                nodes.append(avatar_node)
            except Exception as e:
                logger.warning(f"[{self.name}] 无法添加作者头像: {e}")

        # 添加媒体内容节点（视频直链 / 图集图片）
        media_success = False
        direct_message = None

        if data.get('type') == 'image' and isinstance(data.get('images'), list) and data['images']:
            # ---- 图集：每张图片单独一个转发节点 ----
            images = data['images']
            logger.info(f"[{self.name}] 发送图集，共 {len(images)} 张")
            for idx, img_url in enumerate(images, 1):
                try:
                    img_node = event.bot.build_forward_node(
                        user_id=event.self_id,
                        nickname=self.nickname,
                        message=[
                            MessageSegment.text(f"图集第 {idx}/{len(images)} 张：\n"),
                            MessageSegment.image(img_url)
                        ]
                    )
                    nodes.append(img_node)
                except Exception as e:
                    logger.warning(f"[{self.name}] 无法添加图集第 {idx} 张: {e}")
            # 直接发送第一张
            if images:
                try:
                    await event.reply(MessageSegment.image(images[0]))
                except Exception as e:
                    logger.error(f"[{self.name}] 直接发送图集首图失败: {e}")
            media_success = True
            direct_message = MessageSegment.image(images[0]) if images else None

        else:
            # ---- 视频 ----
            try:
                if data.get('video_url'):
                    video_url = data['video_url']
                    # 先尝试下载到本地文件服务器中转（NapCat 独立容器时，直链可能
                    # 因防盗链/时效无法直接下载）；失败则回退原始直链
                    try:
                        local_url = await download_to_local(video_url, timeout=120)
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
