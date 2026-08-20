# -*- coding: utf-8 -*-
import asyncio
import re
import time
import orjson
import abc
import aiohttp
from typing import Optional, Dict, Any, List, Union, Tuple

from cachetools import TTLCache
from neobot.plugin_api import logger, define_plugin
from neobot.models import MessageEvent


class BaseParser(metaclass=abc.ABCMeta):
    """
    解析器基类，定义所有web解析器共有的方法和属性
    """
    
    # 插件元信息
    plugin_manifest = define_plugin(
        name="web_parser",
        description="Web链接解析插件",
        usage="自动解析各种Web链接",
    )
    

    
    # 请求头
    HEADERS = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }
    
    # 全局共享的ClientSession
    _session: Optional[aiohttp.ClientSession] = None

    # 命中链接时是否给原消息回应 OK 表情（不需要反馈的解析器可覆盖为 False）
    react_ok_on_handle: bool = True

    # OK 表情的 QQ emoji_id（NapCat 扩展 API set_msg_emoji_like 使用）
    _OK_EMOJI_ID = 86

    # 解析最多尝试次数（含首次）：B站/抖音设 3，全部失败才回错误提示
    max_parse_attempts: int = 1

    # 重试间隔（秒），按已失败次数取，避免连续快速失败
    _retry_delays = (1.0, 2.0, 4.0)
    
    def __init__(self):
        """
        初始化解析器
        """
        self.name = "Base Parser"
        self.url_pattern = re.compile(r"https?://[^\s]+")
        # 消息去重缓存（防止同一消息重复上报被多次解析），有界：最多 100 条、10 秒过期
        self.processed_messages: TTLCache[int, bool] = TTLCache(maxsize=100, ttl=10)
        # 相同失败提示的冷却记录: {(目标, 文案): 上次发送时间}
        self._error_reply_cooldown: Dict[Tuple[str, str], float] = {}
        self._error_reply_cooldown_seconds = 120.0

    def _get_event_target(self, event) -> str:
        """获取事件的发送目标（群号优先，其次用户ID）。"""
        return str(getattr(event, "group_id", None) or getattr(event, "user_id", None) or "unknown")

    async def reply_with_error_cooldown(self, event: MessageEvent, text: str) -> bool:
        """
        发送失败提示，但同一目标在冷却时间内不重复发送完全相同的文案。

        日志显示同样的“无法解析短链接。”等文案在同一群重复发送时会被
        NapCat 以 retcode 1200 (EventChecker Failed) 拒绝，冷却可以避免
        无效重复发送。返回是否实际发送。
        """
        key = (self._get_event_target(event), text)
        now = time.monotonic()
        last_sent = self._error_reply_cooldown.get(key, 0.0)
        if now - last_sent < self._error_reply_cooldown_seconds:
            logger.debug(f"[{self.name}] 相同失败提示在冷却期内，跳过重复回复: {text[:40]}")
            return False

        # 限制记录数量，防止长期运行内存无限增长
        if len(self._error_reply_cooldown) > 256:
            oldest_keys = sorted(
                self._error_reply_cooldown,
                key=self._error_reply_cooldown.get,
            )[:128]
            for old_key in oldest_keys:
                del self._error_reply_cooldown[old_key]

        self._error_reply_cooldown[key] = now
        await event.reply(text)
        return True

    async def react_ok(self, event: MessageEvent) -> bool:
        """
        给收到的消息回应一个 OK 表情（NapCat 扩展 API set_msg_emoji_like）。

        仅群消息可靠；私聊或失败时静默跳过，不影响解析流程。
        """
        try:
            message_id = getattr(event, "message_id", None)
            if not message_id:
                return False
            await event.bot.call_api(
                "set_msg_emoji_like",
                {"message_id": message_id, "emoji_id": self._OK_EMOJI_ID},
            )
            return True
        except Exception as e:
            logger.debug(f"[{self.name}] 表情回应失败: {type(e).__name__}: {e}")
            return False
    
    @classmethod
    def get_session(cls) -> aiohttp.ClientSession:
        """
        获取或创建全局的aiohttp ClientSession
        
        Returns:
            aiohttp.ClientSession: 客户端会话对象
        """
        if cls._session is None or cls._session.closed:
            cls._session = aiohttp.ClientSession(headers=cls.HEADERS)
        return cls._session
    
    @abc.abstractmethod
    async def parse(self, url: str) -> Optional[Dict[str, Any]]:
        """
        解析URL获取信息
        
        Args:
            url (str): 要解析的URL
            
        Returns:
            Optional[Dict[str, Any]]: 解析结果，如果失败则返回None
        """
        pass
    
    @abc.abstractmethod
    async def get_real_url(self, short_url: str) -> Optional[str]:
        """
        获取短链接的真实URL
        
        Args:
            short_url (str): 短链接
            
        Returns:
            Optional[str]: 真实URL，如果失败则返回None
        """
        pass
    
    @abc.abstractmethod
    async def format_response(self, event: MessageEvent, data: Dict[str, Any]) -> List[Any]:
        """
        格式化响应消息
        
        Args:
            event (MessageEvent): 消息事件对象
            data (Dict[str, Any]): 解析结果数据
            
        Returns:
            List[Any]: 消息段列表
        """
        pass
    
    def extract_url_from_json_segments(self, segments):
        """
        从消息的JSON段中提取URL
        
        Args:
            segments: 消息段列表
            
        Returns:
            Optional[str]: 提取到的URL或None
        """
        for segment in segments:
            if segment.type == "json":
                logger.info(f"[{self.name}] 检测到JSON CQ码: {segment.data}")
                try:
                    json_data = orjson.loads(segment.data.get("data", "{}"))
                    short_url = json_data.get("meta", {}).get("detail_1", {}).get("qqdocurl")
                    if short_url:
                        logger.success(f"[{self.name}] 成功从JSON卡片中提取到链接: {short_url}")
                        return short_url
                except (orjson.JSONDecodeError, KeyError) as e:
                    logger.error(f"[{self.name}] 解析JSON失败: {e}")
                    continue
        return None
    
    def extract_url_from_text_segments(self, segments):
        """
        从消息的文本段中提取URL，会合并所有文本段来处理被分割的链接。
        
        Args:
            segments: 消息段列表
            
        Returns:
            Optional[str]: 提取到的URL或None
        """
        # 1. 拼接所有文本段内容，保留空格
        full_text = "".join([segment.data.get("text", "") for segment in segments if segment.type == "text"])
        
        # 2. 使用解析器自身的url_pattern进行匹配，通常是匹配到第一个空格为止
        match = self.url_pattern.search(full_text)
        
        if match:
            extracted_url = match.group(0)
            # 清理一下链接末尾可能误包含的标点符号
            extracted_url = re.sub(r'[,.!?]$', '', extracted_url)
            logger.success(f"[{self.name}] 成功从合并后的文本中提取到链接: {extracted_url}")
            return extracted_url
            
        return None
    
    async def process_url(self, event: MessageEvent, url: str):
        """
        处理URL，获取信息并回复。

        短链接解析与信息解析各自最多尝试 max_parse_attempts 次，
        全部失败后才回复错误提示。
        
        Args:
            event (MessageEvent): 消息事件对象
            url (str): 待处理的URL
        """
        try:
            # 检查是否是短链接
            real_url = url
            if self.is_short_url(url):
                for attempt in range(1, self.max_parse_attempts + 1):
                    real_url = await self.get_real_url(url)
                    if real_url:
                        break
                    if attempt < self.max_parse_attempts:
                        delay = self._retry_delays[min(attempt - 1, len(self._retry_delays) - 1)]
                        logger.warning(
                            f"[{self.name}] 短链接解析第 {attempt}/{self.max_parse_attempts} 次失败，"
                            f"{delay:.0f}s 后重试"
                        )
                        await asyncio.sleep(delay)
                if not real_url:
                    logger.error(f"[{self.name}] 重试 {self.max_parse_attempts} 次后仍无法从 {url} 获取真实URL。")
                    await self.reply_with_error_cooldown(event, "无法解析短链接。")
                    return
            
            # 解析URL（最多尝试 max_parse_attempts 次）
            data = None
            for attempt in range(1, self.max_parse_attempts + 1):
                data = await self.parse(real_url)
                if data:
                    break
                if attempt < self.max_parse_attempts:
                    delay = self._retry_delays[min(attempt - 1, len(self._retry_delays) - 1)]
                    logger.warning(
                        f"[{self.name}] 信息解析第 {attempt}/{self.max_parse_attempts} 次失败，"
                        f"{delay:.0f}s 后重试"
                    )
                    await asyncio.sleep(delay)
            if not data:
                logger.error(f"[{self.name}] 重试 {self.max_parse_attempts} 次后仍无法从 {real_url} 解析信息。")
                await self.reply_with_error_cooldown(event, "无法获取链接信息，可能是接口变动或链接不存在。")
                return
            
            # 格式化响应
            response = await self.format_response(event, data)
            if response:
                # 发送响应
                await event.bot.send_forwarded_messages(target=event, nodes=response)
            else:
                await self.reply_with_error_cooldown(event, "解析成功，但无法生成响应。")
                
        except Exception as e:
            logger.error(f"[{self.name}] 处理链接时发生错误: {type(e).__name__}: {e}")
            await self.reply_with_error_cooldown(event, "处理链接时发生错误，请稍后再试。")
    
    def is_short_url(self, url: str) -> bool:
        """
        判断是否是短链接
        
        Args:
            url (str): URL
            
        Returns:
            bool: 是否是短链接
        """
        short_domains = ["b23.tv", "v.douyin.com", "t.cn", "url.cn"]
        return any(domain in url for domain in short_domains)
    
    async def handle_message(self, event: MessageEvent):
        """
        处理消息，检测链接并解析
        
        Args:
            event (MessageEvent): 消息事件对象
        """
        # 消息去重
        if event.message_id in self.processed_messages:
            return
        self.processed_messages[event.message_id] = True
        
        # 忽略机器人自己发送的消息
        if event.user_id == event.self_id:
            return
            
        # 1. 优先解析JSON卡片中的链接
        url_to_process = self.extract_url_from_json_segments(event.message)
        
        # 2. 如果未在JSON卡片中找到链接，则在文本消息中查找
        if not url_to_process:
            url_to_process = self.extract_url_from_text_segments(event.message)

        # 3. 如果找到了链接，则进行处理
        if url_to_process and self.should_handle_url(url_to_process):
            if self.react_ok_on_handle:
                await self.react_ok(event)
            await self.process_url(event, url_to_process)
    
    def should_handle_url(self, url: str) -> bool:
        """
        判断是否应该处理该URL
        
        Args:
            url (str): URL
            
        Returns:
            bool: 是否应该处理
        """
        # 基类默认实现，子类应覆盖此方法
        return bool(self.url_pattern.search(url))
    
    @staticmethod
    def format_count(num: Union[int, str]) -> str:
        """
        格式化数字为易读形式
        
        Args:
            num (Union[int, str]): 要格式化的数字
            
        Returns:
            str: 格式化后的字符串
        """
        try:
            n = int(num)
            if n < 10000:
                return str(n)
            return f"{n / 10000:.1f}万"
        except (ValueError, TypeError):
            return str(num)
