"""
WebSocket 核心通信模块

该模块定义了 `WS` 类，负责与 OneBot v11 实现（如 NapCat）建立和管理
WebSocket 连接。它是整个机器人框架的底层通信基础。

主要职责包括：
- 建立 WebSocket 连接并处理认证。
- 实现断线自动重连机制。
- 监听并接收来自 OneBot 的事件和 API 响应。
- 分发事件给 `CommandManager` 进行处理。
- 提供 `call_api` 方法，用于异步发送 API 请求并等待响应。
"""
import asyncio
import orjson
from typing import TYPE_CHECKING, Any, Dict, Optional, cast
import uuid
import threading

if TYPE_CHECKING:
    from .bot import Bot

import websockets
from websockets.legacy.client import WebSocketClientProtocol

from neobot.models.events.factory import EventFactory

from .config_loader import global_config
from .utils.executor import CodeExecutor
from .utils.logger import ModuleLogger
from .utils.exceptions import (
    WebSocketError, WebSocketConnectionError
)
from .utils.error_codes import ErrorCode, create_error_response


class WS:
    """
    WebSocket 客户端，负责与 OneBot v11 实现进行底层通信。
    """

    def __init__(self, code_executor: Optional[CodeExecutor] = None) -> None:
        """
        初始化 WebSocket 客户端。

        从全局配置中读取 WebSocket URI、访问令牌（Token）和重连间隔。
        
        :param code_executor: 代码执行器实例
        """
        # 读取参数
        cfg = global_config.napcat_ws
        self.url = cfg.uri
        self.token = cfg.token
        self.reconnect_interval = cfg.reconnect_interval

        # 初始化状态
        self.ws: Optional[WebSocketClientProtocol] = None
        self._pending_requests: Dict[str, asyncio.Future] = {}  # echo: future
        self.bot: 'Bot' | None = None
        self.self_id: int | None = None
        self.code_executor = code_executor
        
        # 线程安全锁
        self._pending_requests_lock = threading.RLock()

        # 后台任务集合：跟踪 fire-and-forget 任务，断线/关闭时统一取消，避免僵尸任务累积
        self._background_tasks: set = set()

        # 创建模块专用日志记录器
        self.logger = ModuleLogger("WebSocket")

    def _spawn_task(self, coro) -> asyncio.Task:
        """创建后台任务并登记引用，任务完成后自动移除（避免僵尸任务累积）。"""
        task = asyncio.create_task(coro)
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)
        return task

    def _cancel_background_tasks(self) -> None:
        """取消所有后台任务（断线重连/关闭时调用）。"""
        tasks = list(self._background_tasks)
        for task in tasks:
            task.cancel()
        self._background_tasks.clear()

    @staticmethod
    def _truncate_params_for_log(params: Optional[Dict[Any, Any]], max_len: int = 200) -> str:
        """截断/脱敏 params 用于日志输出，避免超大消息（如 base64:// 图片段）撑大日志，并防止 token 等敏感字段泄露。"""
        if not params:
            return "{}"
        # 命中这些子串的键视为敏感字段，一律脱敏
        sensitive_keys = (
            "token", "password", "passwd", "secret", "authorization", "auth",
            "api_key", "apikey", "access_key", "access_token", "cookie",
            "session", "credential", "sessdata", "bili_jct", "buvid3",
        )
        parts = []
        for k, v in params.items():
            key_lower = str(k).lower()
            if any(s in key_lower for s in sensitive_keys):
                parts.append(f"{k}=<redacted>")
            elif isinstance(v, str) and len(v) > max_len:
                parts.append(f"{k}={v[:max_len]}...<truncated {len(v)} chars>")
            elif isinstance(v, (list, dict)):
                s = str(v)
                if len(s) > max_len:
                    parts.append(f"{k}={s[:max_len]}...<truncated>")
                else:
                    parts.append(f"{k}={s}")
            else:
                parts.append(f"{k}={v}")
        return "{" + ", ".join(parts) + "}"

    async def connect(self) -> None:
        """
        启动并管理 WebSocket 连接。

        这是一个无限循环，负责建立连接。如果连接断开，它会根据配置的
        `reconnect_interval` 时间间隔后自动尝试重新连接。
        """
        headers = {"Authorization": f"Bearer {self.token}"} if self.token else {}

        while True:
            try:
                self.logger.info(f"正在尝试连接至 NapCat: {self.url}")
                async with websockets.connect(
                    self.url,
                    additional_headers=headers,
                    # NapCat 在本机，绝不能走 http_proxy 等代理环境变量，
                    # 否则会被错误地导向 mihomo 端口而连不上
                    proxy=None,
                ) as websocket_raw:
                    websocket = cast(WebSocketClientProtocol, websocket_raw)
                    self.ws = websocket
                    self.logger.success("连接成功！")
                    await self._listen_loop(websocket)

            except (
                websockets.exceptions.ConnectionClosed,
                ConnectionRefusedError,
            ) as e:
                conn_error = WebSocketConnectionError(
                    message=f"WebSocket连接失败: {str(e)}",
                    code=ErrorCode.WS_CONNECTION_FAILED,
                    original_error=e
                )
                self.logger.error(f"连接失败: {conn_error.message}")
                self.logger.log_custom_exception(conn_error)
            except Exception as e:
                error = WebSocketError(
                    message=f"WebSocket运行异常: {str(e)}",
                    code=ErrorCode.WS_MESSAGE_ERROR,
                    original_error=e
                )
                self.logger.exception(f"运行异常: {error.message}")
                self.logger.log_custom_exception(error)

            # 连接已断开：取消旧连接遗留的后台任务（如仍在处理事件的 on_event），避免僵尸任务累积
            self._cancel_background_tasks()
            # 立即 resolve 挂起的 API 请求，避免它们滞留等待 30s 超时
            with self._pending_requests_lock:
                pending = self._pending_requests
                self._pending_requests = {}
            for future in pending.values():
                if not future.done():
                    future.set_result(create_error_response(
                        code=ErrorCode.WS_DISCONNECTED,
                        message="WebSocket连接已断开",
                        data={}
                    ))

            self.logger.info(f"{self.reconnect_interval}秒后尝试重连...")
            await asyncio.sleep(self.reconnect_interval)

    async def _listen_loop(self, websocket_connection: WebSocketClientProtocol) -> None:
        """
        核心监听循环，处理所有接收到的 WebSocket 消息。

        此循环会持续从 WebSocket 连接中读取消息，并根据消息内容
        判断是 API 响应还是上报的事件，然后分发给相应的处理逻辑。

        Args:
            websocket_connection: 当前活动的 WebSocket 连接对象。
        """
        async for message in websocket_connection:
            try:
                data = orjson.loads(message)

                # 1. 处理 API 响应
                # 如果消息中包含 echo 字段，说明是 API 调用的响应
                echo_id = data.get("echo")
                if echo_id and echo_id in self._pending_requests:
                    with self._pending_requests_lock:
                        future = self._pending_requests.pop(echo_id)
                        if not future.done():
                            future.set_result(data)
                    continue

                # 2. 处理上报事件
                # 如果消息中包含 post_type 字段，说明是 OneBot 上报的事件
                if "post_type" in data:
                    # 使用 _spawn_task 异步执行并登记引用，避免阻塞接收循环且防止僵尸任务累积
                    self._spawn_task(self.on_event(data))

            except orjson.JSONDecodeError as e:
                error = WebSocketError(
                    message=f"JSON解析失败: {str(e)}",
                    code=ErrorCode.WS_MESSAGE_ERROR,
                    original_error=e
                )
                self.logger.error(f"解析消息异常: {error.message}")
                # 如果message是bytes类型，需要先解码
                decoded_message = message.decode('utf-8') if isinstance(message, bytes) else message
                self.logger.debug(f"原始消息: {decoded_message}")
            except Exception as e:
                error = WebSocketError(
                    message=f"处理消息异常: {str(e)}",
                    code=ErrorCode.WS_MESSAGE_ERROR,
                    original_error=e
                )
                self.logger.exception(f"解析消息异常: {error.message}")
                self.logger.log_custom_exception(error)

    async def on_event(self, event_data: Dict[str, Any]) -> None:
        """
        事件处理和分发层。

        当接收到一个 OneBot 事件时，此方法负责：
        1. 使用 `EventFactory` 将原始 JSON 数据解析成对应的事件对象。
        2. 为事件对象注入 `Bot` 实例，以便在插件中可以调用 API。
        3. 打印格式化的事件日志。
        4. 将事件对象传递给 `CommandManager` (`matcher`) 进行后续处理。

        Args:
            event_data (dict): 从 WebSocket 接收到的原始事件字典。
        """
        try:
            # 使用工厂创建事件对象
            event = EventFactory.create_event(event_data)

            # 尝试初始化 Bot 实例 (如果尚未初始化且事件包含 self_id)
            # 只要事件中包含 self_id，我们就可以初始化 Bot，不必非要等待 meta_event
            if self.bot is None and hasattr(event, 'self_id'):
                from .bot import Bot
                self.self_id = event.self_id
                self.bot = Bot(self)
                self.logger.success(f"Bot 实例初始化完成: self_id={self.self_id}")
                
                # 注册到 BotManager
                from .managers.bot_manager import bot_manager
                bot_manager.register_bot(self.bot)

                # 将代码执行器注入到 Bot 和执行器自身
                if self.code_executor:
                    self.bot.code_executor = self.code_executor
                    self.code_executor.bot = self.bot
                    self.logger.info("代码执行器已成功注入 Bot 实例。")

            # 如果 bot 尚未初始化，则不处理后续事件
            if self.bot is None:
                self.logger.warning("Bot 尚未初始化，跳过事件处理。")
                return

            event.bot = self.bot  # 注入 Bot 实例

            # 打印日志
            if event.post_type == "message":
                sender_name = event.sender.nickname if hasattr(event, "sender") and event.sender else "Unknown"
                message_type = getattr(event, "message_type", "Unknown")
                user_id = getattr(event, "user_id", "Unknown")
                raw_message = getattr(event, "raw_message", "")
                self.logger.info(f"[消息] {message_type} | {user_id}({sender_name}): {raw_message}")
            elif event.post_type == "notice":
                notice_type = getattr(event, "notice_type", "Unknown")
                self.logger.info(f"[通知] {notice_type}")
            elif event.post_type == "request":
                request_type = getattr(event, "request_type", "Unknown")
                self.logger.info(f"[请求] {request_type}")
            elif event.post_type == "meta_event":
                meta_event_type = getattr(event, "meta_event_type", "Unknown")
                self.logger.debug(f"[元事件] {meta_event_type}")

            # 分发事件
            from .managers.command_manager import matcher
            await matcher.handle_event(self.bot, event)

        except Exception as e:
            self.logger.exception(f"事件处理异常: {str(e)}")
            error = WebSocketError(
                message=f"事件处理异常: {str(e)}",
                code=ErrorCode.WS_MESSAGE_ERROR,
                original_error=e
            )
            self.logger.log_custom_exception(error)

    async def _notify_qq_sent(self, params):
        """Gateway mirror: QQ group -> Discord channel (one-way)"""
        def _build_filename(msg_type, data):
            filename = data.get("filename", "")
            if filename:
                return filename
            file_field = data.get("file", "")
            if file_field and not file_field.startswith(("http", "data:", "/")):
                return file_field
            ext_map = {"image": ".png", "video": ".mp4", "record": ".wav", "file": ".bin"}
            return msg_type + ext_map.get(msg_type, ".bin")

        try:
            from neobot.plugins.discord_cross.config import config

            if not config.ENABLE_CROSS_PLATFORM:
                return

            group_id = params.get("group_id")
            message = params.get("message", "")

            content = ""
            attachments = []
            reply_ids = []
            if isinstance(message, list):
                for seg in message:
                    if isinstance(seg, dict):
                        if seg.get("type") == "text":
                            content += seg.get("data", {}).get("text", "")
                        elif seg.get("type") == "at":
                            qq = seg.get("data", {}).get("qq", "")
                            content += f"@{qq}"
                        elif seg.get("type") == "reply":
                            reply_id = seg.get("data", {}).get("id", "")
                            if reply_id:
                                reply_ids.append(reply_id)
                        elif seg.get("type") in ("image", "video", "record", "file"):
                            url = seg.get("data", {}).get("url") or seg.get("data", {}).get("file")
                            if url:
                                seg_data = seg.get("data", {})
                                filename = _build_filename(seg["type"], seg_data)
                                attachments.append({"type": seg["type"], "url": str(url), "filename": filename})
                    elif isinstance(seg, str):
                        content += seg
            elif isinstance(message, dict):
                if message.get("type") == "text":
                    content = message.get("data", {}).get("text", "")
                elif message.get("type") == "at":
                    qq = message.get("data", {}).get("qq", "")
                    content = f"@{qq}"
                elif message.get("type") == "reply":
                    reply_id = message.get("data", {}).get("id", "")
                    if reply_id:
                        reply_ids.append(reply_id)
                elif message.get("type") in ("image", "video", "record", "file"):
                    url = message.get("data", {}).get("url") or message.get("data", {}).get("file")
                    if url:
                        msg_data = message.get("data", {})
                        filename = _build_filename(message["type"], msg_data)
                        attachments.append({"type": message["type"], "url": str(url), "filename": filename})
            elif isinstance(message, str):
                content = message

            for reply_id in reply_ids:
                try:
                    reply_result = await self.call_api("get_msg", {"message_id": int(reply_id)})
                    if reply_result and "data" in reply_result:
                        reply_msg = reply_result["data"]
                        raw = reply_msg.get("raw_message", "") or ""
                        if isinstance(reply_msg.get("message"), list):
                            raw = "".join(
                                s.get("data", {}).get("text", "")
                                for s in reply_msg["message"]
                                if isinstance(s, dict) and s.get("type") == "text"
                            )
                        if raw:
                            prefix = f"> {str(raw)[:200]}\n"
                            content = prefix + content
                    else:
                        content = f"[回复消息 #{reply_id}] {content}"
                except Exception:
                    content = f"[回复消息 #{reply_id}] {content}"

            if not content and not attachments:
                self.logger.debug("[GatewayMirror:QQ→DC] 消息内容为空，跳过")
                return

            self.logger.debug(f"[GatewayMirror:QQ→DC] 提取内容: content_len={len(content)}, attachments={len(attachments)}")

            from neobot.plugins.discord_cross.forwarder import forwarder

            self.logger.info(f"[GatewayMirror:QQ→DC] 上报 QQ 已发送消息: group={group_id}, content='{content[:80]}...'")
            await forwarder.notify_qq_sent(
                qq_nickname="NeoBot",
                qq_user_id=self.self_id or 0,
                group_name=f"群{group_id}",
                group_id=group_id,
                content=content,
                attachments=attachments,
            )

        except Exception as e:
            self.logger.error(f"[GatewayMirror:QQ→DC] 异常: {e}")
            import traceback
            self.logger.error(f"[GatewayMirror:QQ→DC] 异常堆栈: {traceback.format_exc()}")

    async def close(self) -> None:
        """
        关闭 WebSocket 客户端，释放资源。
        """
        self.logger.info("正在关闭 WebSocket 客户端...")
        
        # 从 BotManager 注销
        if self.bot and self.self_id:
            from .managers.bot_manager import bot_manager
            bot_manager.unregister_bot(str(self.self_id))
        
        if self.ws:
            await self.ws.close()

        # 取消所有后台任务（on_event / _notify_qq_sent 等）
        self._cancel_background_tasks()

        # 取消所有挂起的请求
        with self._pending_requests_lock:
            for future in self._pending_requests.values():
                if not future.done():
                    future.cancel()
            self._pending_requests.clear()
        
        self.logger.success("WebSocket 客户端已关闭")

    async def call_api(self, action: str, params: Optional[Dict[Any, Any]] = None) -> Dict[Any, Any]:
        """
        向 OneBot v11 实现端发送一个 API 请求。

        该方法通过 WebSocket 发送请求，并使用 `echo` 字段来匹配对应的响应。
        它创建了一个 `Future` 对象来异步等待响应，并设置了超时机制。

        Args:
            action (str): API 的动作名称，例如 "send_group_msg"。
            params (dict, optional): API 请求的参数字典。 Defaults to None.

        Returns:
            dict: OneBot API 的响应数据。如果超时或连接断开，则返回一个
                  表示失败的字典。
        """
        if not self.ws:
            self.logger.error("调用 API 失败: WebSocket 未初始化")
            return create_error_response(
                code=ErrorCode.WS_DISCONNECTED,
                message="WebSocket未初始化",
                data={"action": action, "params": params}
            )

        from websockets.protocol import State

        if getattr(self.ws, "state", None) is not State.OPEN:
            self.logger.error("调用 API 失败: WebSocket 连接未打开")
            return create_error_response(
                code=ErrorCode.WS_DISCONNECTED,
                message="WebSocket连接未打开",
                data={"action": action, "params": params}
            )

        if params is None:
            params = {}

        from neobot.core.utils.logger import ModuleLogger
        gw_logger = ModuleLogger("GatewayMirror")

        # Gateway mirror: 拦截发送至 QQ 群的消息，单向同步到 Discord
        # 触发条件：
        #   1. 未显式标记 _no_mirror（避免反向同步造成回环）
        #   2. action 为 send_group_msg 或 send_msg(message_type=group)
        #   3. 存在 group_id
        #   4. 跨平台同步已启用（在触发点提前判断，避免无谓的 fire-and-forget 任务）
        if not params.get("_no_mirror"):
            is_group_send = (
                action == "send_group_msg"
                or (action == "send_msg" and params.get("message_type") == "group")
            )
            group_id = params.get("group_id")
            if is_group_send and group_id is not None:
                try:
                    from neobot.plugins.discord_cross.config import config as _cross_config
                    cross_enabled = _cross_config.ENABLE_CROSS_PLATFORM
                except Exception:
                    cross_enabled = False
                if cross_enabled:
                    gw_logger.debug(
                        f"[GatewayMirror:QQ→DC] 触发同步: action={action}, group_id={group_id}"
                    )
                    self._spawn_task(self._notify_qq_sent(params))

        actual_params = {k: v for k, v in params.items() if not k.startswith("_")}
        echo_id = str(uuid.uuid4())
        payload = {"action": action, "params": actual_params, "echo": echo_id}

        loop = asyncio.get_running_loop()
        future = loop.create_future()
        with self._pending_requests_lock:
            self._pending_requests[echo_id] = future
        
        try:
            await self.ws.send(orjson.dumps(payload).decode('utf-8'))
            return await asyncio.wait_for(future, timeout=30.0)
        except asyncio.TimeoutError:
            with self._pending_requests_lock:
                self._pending_requests.pop(echo_id, None)
            self.logger.warning(f"API 调用超时: action={action}, params={self._truncate_params_for_log(params)}")
            return create_error_response(
                code=ErrorCode.TIMEOUT_ERROR,
                message="API调用超时",
                data={"action": action, "params": params}
            )
        except Exception as e:
            with self._pending_requests_lock:
                self._pending_requests.pop(echo_id, None)
            self.logger.exception(f"API 调用异常: action={action}, error={str(e)}")
            return create_error_response(
                code=ErrorCode.WS_MESSAGE_ERROR,
                message=f"API调用异常: {str(e)}",
                data={"action": action, "params": params}
            )


class ReverseWSClient(WS):
    """
    反向 WebSocket 客户端代理，用于 Bot 实例调用 API。
    """
    def __init__(self, manager: Any, client_id: str):
        super().__init__()
        self.manager = manager
        self.client_id = client_id
        
    async def call_api(self, action: str, params: Optional[Dict[Any, Any]] = None) -> Dict[Any, Any]:
        return await self.manager.call_api(action, params, self.client_id)
