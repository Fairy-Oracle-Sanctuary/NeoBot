# -*- coding: utf-8 -*-
"""
进程内消息总线：入站消息分发 / 出站发送通知。
适配器只做平台↔总线转换；转发/翻译/去重等业务逻辑订阅总线。
"""
import asyncio
from typing import Awaitable, Callable, Dict, List

from neobot.core.utils.logger import ModuleLogger

from .message import PlatformMessage

logger = ModuleLogger("MessageBus")

Handler = Callable[[PlatformMessage], Awaitable[None]]


class MessageBus:
    def __init__(self):
        self._incoming: Dict[str, List[Handler]] = {}
        self._outgoing: List[Handler] = []
        self._lock = asyncio.Lock()

    def on_incoming(self, platform: str = "", key: str = None) -> Callable[[Handler], Handler]:
        """订阅某平台（或全部平台）的入站消息。

        key: 订阅唯一标识。热重载后以同 key 重新注册会自动替换旧订阅，
             避免 importlib.reload 重新执行模块顶层代码时订阅者无限累积。
        """

        def decorator(func: Handler) -> Handler:
            if key is not None:
                # 移除同 key 旧订阅（旧闭包按标识识别并丢弃）
                self._incoming.setdefault(platform, [])
                self._incoming[platform] = [
                    h for h in self._incoming[platform] if getattr(h, "_bus_key", None) != key
                ]
            setattr(func, "_bus_key", key)
            self._incoming.setdefault(platform, []).append(func)
            return func

        return decorator

    def on_outgoing(self, key: str = None) -> Callable[[Handler], Handler]:
        """订阅出站发送通知（适配器发送后触发）。

        key: 订阅唯一标识，同 key 重新注册自动替换旧订阅（热重载去重）。
        """

        def decorator(func: Handler) -> Handler:
            if key is not None:
                self._outgoing = [
                    h for h in self._outgoing if getattr(h, "_bus_key", None) != key
                ]
            setattr(func, "_bus_key", key)
            self._outgoing.append(func)
            return func

        return decorator

    async def publish_incoming(self, msg: PlatformMessage) -> None:
        """发布入站消息（错误隔离，单个订阅者失败不影响其他）。"""
        handlers = list(self._incoming.get("", []))
        handlers += list(self._incoming.get(msg.platform, []))
        for handler in handlers:
            try:
                await handler(msg)
            except Exception as e:
                logger.error(f"消息总线订阅者异常: {type(e).__name__}: {e}")

    async def publish_outgoing(self, msg: PlatformMessage) -> None:
        """发布出站发送通知。"""
        for handler in list(self._outgoing):
            try:
                await handler(msg)
            except Exception as e:
                logger.error(f"出站订阅者异常: {type(e).__name__}: {e}")


message_bus = MessageBus()
