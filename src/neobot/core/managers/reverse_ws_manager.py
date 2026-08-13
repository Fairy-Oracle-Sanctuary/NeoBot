"""
反向 WebSocket 管理器模块

该模块提供了反向 WebSocket 服务端功能，允许 OneBot 实现（如 NapCat）
主动连接到机器人服务器，而不是由机器人主动连接到 OneBot 实现。
"""
import asyncio
import orjson
import websockets
import websockets.http11
from websockets.server import WebSocketServerProtocol
from typing import Dict, Any, Optional, Set, TYPE_CHECKING
from datetime import datetime
import uuid
import threading

if TYPE_CHECKING:
    from ..bot import Bot

from ..utils.logger import ModuleLogger
from ..utils.error_codes import ErrorCode, create_error_response
from .command_manager import matcher
from neobot.models.events.factory import EventFactory
from ..ws import WS, ReverseWSClient as _ReverseWSClient


class ReverseWSClient(_ReverseWSClient):
    """
    反向 WebSocket 客户端代理，用于 Bot 实例调用 API。
    """
    def __init__(self, manager: "ReverseWSManager", client_id: str):
        super().__init__(manager, client_id)
        self.manager = manager
        self.client_id = client_id
        
    async def call_api(self, action: str, params: Optional[Dict[Any, Any]] = None) -> Dict[Any, Any]:
        """
        通过 ReverseWSManager 调用 API。
        """
        return await self.manager.call_api(action, params, self.client_id)


class ReverseWSManager:
    """
    反向 WebSocket 管理器，作为服务端接收 OneBot 实现的连接。
    支持多前端负载均衡和防重复发送机制。
    """
    
    def __init__(self):
        """
        初始化反向 WebSocket 管理器。
        """
        self.server = None
        self.clients: Dict[str, WebSocketServerProtocol] = {}
        self.client_self_ids: Dict[str, int] = {}
        self._pending_requests: Dict[str, asyncio.Future] = {}
        self._running = False
        self.logger = ModuleLogger("ReverseWSManager")
        # 反向 WS 服务端鉴权 token（来自配置 reverse_ws.token，未配置时拒绝所有连接）
        self.auth_token: str = ""
        
        # 负载均衡相关
        self._active_client_id: Optional[str] = None  # 当前活跃的客户端（用于消息发送）
        self._client_load: Dict[str, int] = {}  # 客户端负载计数
        self._client_health: Dict[str, datetime] = {}  # 客户端健康检查时间
        
        # 防重复发送相关
        self._processed_events: Dict[str, Dict[str, datetime]] = {}  # 每个客户端已处理的事件ID和时间
        self._event_ttl = 60  # 事件ID保留时间（秒）
        self._message_locks: Dict[str, asyncio.Lock] = {}  # 消息处理锁
        self._message_lock_times: Dict[str, datetime] = {}  # 消息锁创建时间
        self._lock_ttl = 300  # 锁保留时间（秒）
        
        # 基于消息内容的防重复（仅用于群聊）
        self._processed_messages: Dict[str, Dict[str, datetime]] = {}  # 每个客户端已处理的消息内容和时间
        self._message_content_ttl = 5  # 消息内容保留时间（秒）
        
        # 启动清理任务
        self._cleanup_task = None
        
        # Bot实例字典（每个前端独立的Bot实例）
        self.bots: Dict[str, "Bot"] = {}
        
        # 正在处理的事件ID集合（用于防止重复处理）
        self._processing_events: Dict[str, Set[str]] = {}  # client_id: set of event_ids
        
        # 线程安全锁
        self._clients_lock = threading.RLock()
        self._bots_lock = threading.RLock()
        self._pending_requests_lock = threading.RLock()
        self._load_lock = threading.RLock()
        self._health_lock = threading.RLock()
        self._processed_events_lock = threading.RLock()
        self._processed_messages_lock = threading.RLock()
        self._processing_events_lock = threading.RLock()
        self._message_locks_lock = threading.RLock()
        self._message_lock_times_lock = threading.RLock()

        # 后台任务集合：client_id -> set[Task]，客户端断开时取消其遗留任务，避免僵尸任务累积
        self._background_tasks: Dict[str, Set[asyncio.Task]] = {}
        self._background_tasks_lock = threading.RLock()

    def _spawn_task(self, client_id: str, coro) -> asyncio.Task:
        """创建后台任务并登记到客户端的任务集合，任务完成后自动移除。"""
        task = asyncio.create_task(coro)
        with self._background_tasks_lock:
            self._background_tasks.setdefault(client_id, set()).add(task)
        task.add_done_callback(self._remove_background_task(client_id, task))
        return task

    def _remove_background_task(self, client_id: str, task: asyncio.Task):
        def _done(_task):
            with self._background_tasks_lock:
                tasks = self._background_tasks.get(client_id)
                if tasks:
                    tasks.discard(task)
                    if not tasks:
                        self._background_tasks.pop(client_id, None)
        return _done

    def _cancel_client_tasks(self, client_id: str) -> None:
        """取消某个客户端的全部后台任务（客户端断开时调用）。"""
        with self._background_tasks_lock:
            tasks = self._background_tasks.pop(client_id, set())
        for task in tasks:
            task.cancel()
        
    async def start(self, host: str = "0.0.0.0", port: int = 3002, token: str = "") -> None:
        """
        启动反向 WebSocket 服务端。
        
        Args:
            host: 监听地址，默认为 0.0.0.0
            port: 监听端口，默认为 3002
            token: 服务端鉴权 token，客户端需携带 Authorization: Bearer <token>，
                   未配置（为空）时拒绝所有连接，防止未授权事件注入。
        """
        self._running = True
        self.auth_token = token or ""
        if not self.auth_token:
            self.logger.warning("反向 WebSocket 服务端未配置 token，将拒绝所有连接，请在配置 reverse_ws.token 中设置")
        self.server = await websockets.serve(
            self._handle_client,
            host,
            port,
            ping_interval=20,
            ping_timeout=20,
            process_request=self._check_auth
        )
        self.logger.success(f"反向 WebSocket 服务端已启动: ws://{host}:{port}")
        
        # 启动清理任务
        self._cleanup_task = asyncio.create_task(self._cleanup_expired_data())
        
    async def stop(self) -> None:
        """
        停止反向 WebSocket 服务端。
        """
        self._running = False
        
        # 停止清理任务
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
        
        if self.server:
            self.server.close()
            await self.server.wait_closed()
            
        for client_id in list(self.clients.keys()):
            await self._disconnect_client(client_id)

        # 清理剩余后台任务
        with self._background_tasks_lock:
            remaining = self._background_tasks
            self._background_tasks = {}
        for tasks in remaining.values():
            for task in tasks:
                task.cancel()
            
        self.logger.success("反向 WebSocket 服务端已停止")
        
    async def _check_auth(self, connection, request):
        """
        WS 握手阶段鉴权回调：校验 Authorization: Bearer <token>。
        未配置 token 或 token 不匹配时返回 401 拒绝握手。
        """
        if not self.auth_token:
            self.logger.warning("反向 WebSocket 服务端未配置 token，拒绝连接（未授权）")
            return websockets.http11.Response(401, "Unauthorized", {}, b"reverse_ws token not configured")
        auth = request.headers.get("Authorization", "")
        if auth == f"Bearer {self.auth_token}":
            return None
        remote = getattr(connection, "remote_address", "?")
        self.logger.warning(f"反向 WebSocket 鉴权失败，拒绝连接: {remote}")
        return websockets.http11.Response(401, "Unauthorized", {}, b"invalid token")

    async def _handle_client(
        self, 
        websocket: WebSocketServerProtocol, 
        path: str = None
    ) -> None:
        """
        处理客户端连接。
        
        Args:
            websocket: WebSocket 连接对象
            path: 连接路径
        """
        client_id = str(uuid.uuid4())
        self.clients[client_id] = websocket
        self.logger.info(f"新客户端连接: {client_id}")
        
        try:
            async for message in websocket:
                try:
                    data = orjson.loads(message)
                    
                    # 处理 API 响应
                    echo_id = data.get("echo")
                    if echo_id and echo_id in self._pending_requests:
                        future = self._pending_requests.pop(echo_id)
                        if not future.done():
                            future.set_result(data)
                        continue
                        
                    # 处理上报事件
                    if "post_type" in data:
                        event_id = self._extract_event_id(data)
                        self.logger.debug(f"收到事件: client_id={client_id}, event_id={event_id}, post_type={data.get('post_type')}")
                        self._spawn_task(client_id, self._on_event(client_id, data))
                        
                except orjson.JSONDecodeError as e:
                    self.logger.error(f"JSON 解析失败: {str(e)}")
                except Exception as e:
                    self.logger.exception(f"处理消息异常: {str(e)}")
                    
        except websockets.exceptions.ConnectionClosed as e:
            self.logger.info(f"客户端断开连接: {client_id} - {str(e)}")
        except Exception as e:
            self.logger.exception(f"客户端异常: {str(e)}")
        finally:
            await self._disconnect_client(client_id)
            
    async def _cleanup_expired_data(self) -> None:
        """
        清理过期的事件ID和消息锁
        """
        while self._running:
            try:
                await asyncio.sleep(10)  # 每10秒清理一次
                
                current_time = datetime.now()
                
                # 清理过期的事件ID（按客户端）
                with self._processed_events_lock:
                    for client_id, events in list(self._processed_events.items()):
                        expired_events = [
                            event_id for event_id, timestamp in events.items()
                            if (current_time - timestamp).total_seconds() > self._event_ttl
                        ]
                        for event_id in expired_events:
                            del events[event_id]
                        if not events:
                            del self._processed_events[client_id]
                
                # 清理过期的消息锁
                with self._message_lock_times_lock:
                    expired_locks = [
                        lock_key for lock_key, timestamp in self._message_lock_times.items()
                        if (current_time - timestamp).total_seconds() > self._lock_ttl
                    ]
                    for lock_key in expired_locks:
                        with self._message_locks_lock:
                            if lock_key in self._message_locks:
                                del self._message_locks[lock_key]
                        if lock_key in self._message_lock_times:
                            del self._message_lock_times[lock_key]
                
                # 清理过期的消息内容（按客户端）
                with self._processed_messages_lock:
                    for client_id, messages in list(self._processed_messages.items()):
                        expired_messages = [
                            msg_key for msg_key, timestamp in messages.items()
                            if (current_time - timestamp).total_seconds() > self._message_content_ttl
                        ]
                        for msg_key in expired_messages:
                            del messages[msg_key]
                        if not messages:
                            del self._processed_messages[client_id]
                        
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error(f"清理过期数据失败: {str(e)}")
            
    async def _disconnect_client(self, client_id: str) -> None:
        """
        断开客户端连接。
        
        Args:
            client_id: 客户端 ID
        """
        with self._clients_lock:
            if client_id in self.clients:
                del self.clients[client_id]
        with self._clients_lock:
            if client_id in self.client_self_ids:
                del self.client_self_ids[client_id]
        with self._load_lock:
            if client_id in self._client_load:
                del self._client_load[client_id]
        with self._health_lock:
            if client_id in self._client_health:
                del self._client_health[client_id]
        with self._bots_lock:
            if client_id in self.bots:
                # 从 BotManager 注销
                from .bot_manager import bot_manager
                if self.bots[client_id].self_id:
                    bot_manager.unregister_bot(str(self.bots[client_id].self_id))
                del self.bots[client_id]
            
        # 清理该客户端的防重复数据
        with self._processed_events_lock:
            if client_id in self._processed_events:
                del self._processed_events[client_id]
        with self._processed_messages_lock:
            if client_id in self._processed_messages:
                del self._processed_messages[client_id]
        with self._processing_events_lock:
            if client_id in self._processing_events:
                del self._processing_events[client_id]

        # 取消该客户端的后台任务（如仍在处理的 _on_event），避免僵尸任务累积
        self._cancel_client_tasks(client_id)

        self.logger.info(f"客户端已断开并清理: {client_id}")
            
    async def _on_event(self, client_id: str, event_data: Dict[str, Any]) -> None:
        """
        处理事件，包含防重复发送和负载均衡逻辑。
        
        Args:
            client_id: 客户端 ID
            event_data: 事件数据
        """
        # 获取事件ID（不再使用 time 作为兜底，避免同秒不同事件被误判为重复）
        event_id = self._extract_event_id(event_data)
        if not event_id:
            # 无可用事件 ID 时跳过去重，直接处理（避免误丢事件）
            self.logger.debug(f"_on_event: 事件ID为空，跳过去重直接处理, client_id={client_id}, post_type={event_data.get('post_type')}")
            event_key = None
        else:
            event_key = f"{event_data.get('post_type')}:{event_id}"
        
        # 检查客户端是否已连接
        with self._clients_lock:
            if client_id not in self.clients:
                self.logger.debug(f"_on_event: 客户端已断开, client_id={client_id}")
                return
        
        # 检查是否正在处理（仅在具有 event_key 时启用）
        if event_key is not None:
            with self._processing_events_lock:
                if client_id not in self._processing_events:
                    self._processing_events[client_id] = set()

                if event_key in self._processing_events[client_id]:
                    self.logger.debug(f"_on_event: 事件正在处理中, client_id={client_id}, event_key={event_key}")
                    return

                # 标记为正在处理
                self._processing_events[client_id].add(event_key)
        
        try:
            event = EventFactory.create_event(event_data)
            
            if hasattr(event, 'self_id'):
                with self._clients_lock:
                    self.client_self_ids[client_id] = event.self_id
                
            # 为事件注入 Bot 实例
            from .bot_manager import bot_manager
            from ..bot import Bot
            
            # 为每个前端创建独立的 Bot 实例
            with self._bots_lock:
                if client_id not in self.bots:
                    # 使用 ReverseWSClient 代理
                    temp_ws = ReverseWSClient(self, client_id)
                    temp_ws.self_id = event.self_id if hasattr(event, 'self_id') else 0
                    self.bots[client_id] = Bot(temp_ws)
                    
                    # 注册到 BotManager
                    bot_manager.register_bot(self.bots[client_id])
            
            event.bot = self.bots[client_id]
            
            # 记录客户端健康状态
            with self._health_lock:
                self._client_health[client_id] = datetime.now()
            
            # 检查是否为重复事件（按客户端）
            is_duplicate = self._is_duplicate_event(event_data, client_id)
            self.logger.debug(f"事件防重复检查: client_id={client_id}, event_id={event_data.get('message_id')}, is_duplicate={is_duplicate}")
            if is_duplicate:
                self.logger.debug(f"检测到重复事件，已忽略: {event_data.get('id')}")
                return
              
            # 处理消息事件
            if event.post_type == "message":
                sender_name = event.sender.nickname if hasattr(event, "sender") and event.sender else "Unknown"
                message_type = getattr(event, "message_type", "Unknown")
                user_id = getattr(event, "user_id", "Unknown")
                raw_message = getattr(event, "raw_message", "")
                self.logger.info(f"[消息] {message_type} | {user_id}({sender_name}): {raw_message}")
                
                # 使用锁防止同一消息被多次处理
                message_key = self._get_message_key(event_data)
                async with self._get_message_lock(message_key):
                    # 再次检查是否重复（防止并发问题）
                    if self._is_duplicate_event(event_data, client_id):
                        self.logger.debug(f"并发检测到重复消息（事件ID），已忽略: {message_key}")
                        return
                    
                    # 检查是否重复（基于消息内容，按客户端，仅群聊）
                    is_duplicate_content = self._is_duplicate_message(event_data, client_id)
                    self.logger.debug(f"锁内内容检查: client_id={client_id}, is_duplicate={is_duplicate_content}")
                    if is_duplicate_content:
                        self.logger.debug(f"并发检测到重复消息（内容），已忽略: {message_key}")
                        return
                    
                    # 标记事件已处理（按客户端）
                    with self._processed_events_lock:
                        self._mark_event_processed(event_data, client_id)
                    
                    # 更新客户端负载
                    with self._load_lock:
                        self._update_client_load(client_id)
                    
                    await matcher.handle_event(event.bot, event)
            else:
                # 对于非消息事件，直接标记并处理
                with self._processed_events_lock:
                    self._mark_event_processed(event_data, client_id)
                
                if event.post_type == "notice":
                    notice_type = getattr(event, "notice_type", "Unknown")
                    self.logger.info(f"[通知] {notice_type}")
                    await matcher.handle_event(event.bot, event)
                    
                elif event.post_type == "request":
                    request_type = getattr(event, "request_type", "Unknown")
                    self.logger.info(f"[请求] {request_type}")
                    await matcher.handle_event(event.bot, event)
                    
                elif event.post_type == "meta_event":
                    meta_event_type = getattr(event, "meta_event_type", "Unknown")
                    self.logger.debug(f"[元事件] {meta_event_type}")
                    await matcher.handle_event(event.bot, event)
                
        except Exception as e:
            self.logger.exception(f"事件处理异常: {str(e)}")
        finally:
            # 清理正在处理的事件（仅在标记过 event_key 时清理）
            if event_key is not None:
                with self._processing_events_lock:
                    if client_id in self._processing_events:
                        if event_key in self._processing_events[client_id]:
                            self._processing_events[client_id].discard(event_key)
                        # 如果集合为空，删除该客户端的记录
                        if not self._processing_events[client_id]:
                            del self._processing_events[client_id]
            
    async def call_api(
        self, 
        action: str, 
        params: Optional[Dict[Any, Any]] = None,
        client_id: Optional[str] = None,
        use_load_balance: bool = True
    ) -> Dict[Any, Any]:
        """
        向客户端发送 API 请求。
        
        Args:
            action: API 动作名称
            params: API 参数
            client_id: 客户端 ID，如果为 None 则根据负载均衡策略选择
            use_load_balance: 是否使用负载均衡，默认为 True
            
        Returns:
            API 响应数据
        """
        if not self.clients:
            self.logger.error("调用 API 失败: 没有可用的客户端连接")
            return create_error_response(
                code=ErrorCode.WS_DISCONNECTED,
                message="没有可用的客户端连接",
                data={"action": action, "params": params}
            )
            
        # 如果没有指定客户端，使用负载均衡
        if client_id is None and use_load_balance:
            # 优先选择健康的客户端
            healthy_clients = self.get_healthy_clients()
            if healthy_clients:
                # 选择负载最低的客户端
                client_id = self.get_client_with_least_load()
                if client_id is None and healthy_clients:
                    with self._clients_lock:
                        client_id = list(healthy_clients.keys())[0]
            else:
                # 如果没有健康客户端，使用所有客户端中的一个
                with self._clients_lock:
                    client_id = list(self.clients.keys())[0]
        
        echo_id = str(uuid.uuid4())
        payload = {"action": action, "params": params or {}, "echo": echo_id}
        
        loop = asyncio.get_running_loop()
        future = loop.create_future()
        with self._pending_requests_lock:
            self._pending_requests[echo_id] = future
        
        try:
            targets = [client_id] if client_id else None
            clients_to_send = []
            
            with self._clients_lock:
                if targets is None:
                    targets = list(self.clients.keys())
                for cid in targets:
                    if cid in self.clients:
                        clients_to_send.append((cid, self.clients[cid]))
            
            for cid, websocket in clients_to_send:
                await websocket.send(orjson.dumps(payload).decode('utf-8'))
                    
            return await asyncio.wait_for(future, timeout=30.0)
        except asyncio.TimeoutError:
            with self._pending_requests_lock:
                self._pending_requests.pop(echo_id, None)
            self.logger.warning(f"API 调用超时: action={action}, params={WS._truncate_params_for_log(params)}")
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
            
    def get_connected_clients(self) -> Dict[str, int]:
        """
        获取已连接的客户端列表。
        
        Returns:
            客户端 ID 和 self_id 的映射字典
        """
        with self._clients_lock:
            return self.client_self_ids.copy()
        
    def _extract_event_id(self, event_data: Dict[str, Any]) -> Optional[str]:
        """
        从事件数据中提取唯一事件 ID。

        仅使用真正具备唯一性的字段（id / post_id / message_id），
        不再使用 time 作为兜底，避免同一秒内多个不同事件被误判为重复。

        Args:
            event_data: 事件数据

        Returns:
            事件 ID 字符串，若无可用字段则返回 None
        """
        # 消息事件优先使用 message_id
        if event_data.get('post_type') == 'message':
            msg_id = event_data.get('message_id')
            if msg_id is not None:
                return str(msg_id)
        # 通用兜底：id / post_id（NapCat 等实现可能在非消息事件上提供）
        for key in ('id', 'post_id', 'message_id'):
            value = event_data.get(key)
            if value is not None:
                return str(value)
        return None

    def _is_duplicate_event(self, event_data: Dict[str, Any], client_id: str) -> bool:
        """
        检查是否为重复事件。
        
        Args:
            event_data: 事件数据
            client_id: 客户端ID
            
        Returns:
            是否为重复事件
        """
        # 提取事件ID（不再使用 time 作为兜底，避免同秒不同事件被误判为重复）
        event_id = self._extract_event_id(event_data)
        if not event_id:
            return False

        event_key = f"{event_data.get('post_type')}:{event_id}"

        # 检查该客户端是否已处理过此事件
        with self._processed_events_lock:
            if client_id not in self._processed_events:
                self.logger.debug(f"_is_duplicate_event: client_id={client_id}不在_processed_events中, event_key={event_key}, 返回False")
                return False

            is_duplicate = event_key in self._processed_events[client_id]
            self.logger.debug(f"_is_duplicate_event: client_id={client_id}, event_key={event_key}, in_processed={is_duplicate}, processed_events_count={len(self._processed_events[client_id])}")
            return is_duplicate
        
    def _is_duplicate_message(self, event_data: Dict[str, Any], client_id: str) -> bool:
        """
        检查是否为重复消息（基于消息内容）。
        
        Args:
            event_data: 事件数据
            client_id: 客户端ID
            
        Returns:
            是否为重复消息
        """
        if event_data.get('post_type') != 'message':
            return False
            
        # 只对群聊消息进行内容防重复
        if event_data.get('message_type') != 'group':
            return False
            
        # 生成消息内容标识
        raw_message = event_data.get('raw_message', '')
        user_id = event_data.get('user_id')
        group_id = event_data.get('group_id', '0')
        
        # 使用消息内容、用户ID和群组ID作为标识
        content_key = f"content:{raw_message}:{user_id}:{group_id}"
        
        # 检查该客户端是否已处理过此消息内容
        with self._processed_messages_lock:
            if client_id not in self._processed_messages:
                return False
            
            return content_key in self._processed_messages[client_id]
        
    def _mark_event_processed(self, event_data: Dict[str, Any], client_id: str) -> None:
        """
        标记事件已处理。
        
        Args:
            event_data: 事件数据
            client_id: 客户端ID
        """
        # 提取事件ID（不再使用 time 作为兜底，避免同秒不同事件被误判为重复）
        event_id = self._extract_event_id(event_data)
        if not event_id:
            self.logger.debug(f"_mark_event_processed: event_id为空, event_data={event_data}")
            return

        event_key = f"{event_data.get('post_type')}:{event_id}"
        
        # 为该客户端记录已处理的事件
        with self._processed_events_lock:
            if client_id not in self._processed_events:
                self._processed_events[client_id] = {}
            self._processed_events[client_id][event_key] = datetime.now()
            self.logger.debug(f"_mark_event_processed: client_id={client_id}, event_key={event_key}, processed_events_count={len(self._processed_events[client_id])}")
        
        # 只对群聊消息标记内容已处理
        if event_data.get('post_type') == 'message' and event_data.get('message_type') == 'group':
            raw_message = event_data.get('raw_message', '')
            user_id = event_data.get('user_id')
            group_id = event_data.get('group_id', '0')
            content_key = f"content:{raw_message}:{user_id}:{group_id}"
            
            with self._processed_messages_lock:
                if client_id not in self._processed_messages:
                    self._processed_messages[client_id] = {}
                self._processed_messages[client_id][content_key] = datetime.now()
        
    def _get_message_key(self, event_data: Dict[str, Any]) -> str:
        """
        获取消息唯一标识。
        
        Args:
            event_data: 事件数据
            
        Returns:
            消息唯一标识
        """
        if event_data.get('post_type') == 'message':
            message_id = event_data.get('message_id') or event_data.get('id')
            user_id = event_data.get('user_id')
            return f"msg:{message_id}:{user_id}"
        return str(uuid.uuid4())
        
    def _get_message_lock(self, key: str) -> asyncio.Lock:
        """
        获取消息处理锁。
        
        Args:
            key: 消息唯一标识
            
        Returns:
            asyncio.Lock 实例
        """
        with self._message_locks_lock:
            if key not in self._message_locks:
                self._message_locks[key] = asyncio.Lock()
                with self._message_lock_times_lock:
                    self._message_lock_times[key] = datetime.now()
        return self._message_locks[key]
        
    def _update_client_load(self, client_id: str) -> None:
        """
        更新客户端负载。
        
        Args:
            client_id: 客户端 ID
        """
        with self._load_lock:
            if client_id not in self._client_load:
                self._client_load[client_id] = 0
            self._client_load[client_id] += 1
        
    def get_client_with_least_load(self) -> Optional[str]:
        """
        获取负载最低的客户端。
        
        Returns:
            客户端 ID，如果没有客户端则返回 None
        """
        with self._load_lock:
            if not self._client_load:
                return None
            
            return min(self._client_load.keys(), key=lambda k: self._client_load[k])
        
    def get_healthy_clients(self) -> Dict[str, int]:
        """
        获取健康的客户端列表（最近30秒内有活动）。
        
        Returns:
            健康的客户端 ID 和 self_id 的映射字典
        """
        current_time = datetime.now()
        healthy = {}
        
        with self._health_lock:
            with self._clients_lock:
                for client_id, last_health in self._client_health.items():
                    if (current_time - last_health).total_seconds() < 30:
                        if client_id in self.client_self_ids:
                            healthy[client_id] = self.client_self_ids[client_id]
        
        return healthy


reverse_ws_manager = ReverseWSManager()
