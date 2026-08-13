"""
事件处理器模块

该模块定义了用于处理不同类型事件的处理器类。
每个处理器都负责注册和分发特定类型的事件。
"""
import inspect
from abc import ABC, abstractmethod
from typing import Any, Callable, Dict, List, Optional, Tuple, TYPE_CHECKING

if TYPE_CHECKING:
    from ..bot import Bot
from ..config_loader import global_config
from ..permission import Permission
from ..utils.executor import run_in_thread_pool
from ..utils.logger import logger, ModuleLogger
from ..managers.redis_manager import redis_manager
from neobot.core.managers.permission_manager import permission_manager


class BaseHandler(ABC):
    """
    事件处理器抽象基类
    """
    def __init__(self):
        self.handlers: List[Dict[str, Any]] = []

    @abstractmethod
    async def handle(self, bot: "Bot", event: Any):
        """
        处理事件
        """
        raise NotImplementedError

    async def _run_handler(
        self,
        func: Callable,
        bot: "Bot",
        event: Any,
        args: Optional[List[str]] = None,
        permission_granted: Optional[bool] = None
    ):
        """
        智能执行事件处理器，并注入所需参数
        """
        sig = inspect.signature(func)
        params = sig.parameters
        kwargs: Dict[str, Any] = {}

        if "bot" in params:
            kwargs["bot"] = bot
        if "event" in params:
            kwargs["event"] = event
        if "ctx" in params:
            kwargs["ctx"] = event
        if "args" in params and args is not None:
            kwargs["args"] = args
        if "permission_granted" in params and permission_granted is not None:
            kwargs["permission_granted"] = permission_granted

        if inspect.iscoroutinefunction(func):
            result = await func(**kwargs)
        else:
            # 如果是同步函数，则放入线程池执行
            result = await run_in_thread_pool(func, **kwargs)
        return result is True


class MessageHandler(BaseHandler):
    """
    消息事件处理器
    """
    def __init__(self, prefixes: Tuple[str, ...]):
        super().__init__()
        self.prefixes = prefixes
        self.commands: Dict[str, Dict] = {}
        self.message_handlers: List[Dict[str, Any]] = []
        # 平台感知分发（阶段 2/3）：platform -> handlers / commands
        self.platform_handlers: Dict[str, List[Dict[str, Any]]] = {}
        self.platform_commands: Dict[str, Dict[str, Dict]] = {}

    def clear(self):
        """
        清空所有已注册的消息和命令处理器
        """
        self.commands.clear()
        self.message_handlers.clear()
        self.platform_handlers.clear()
        self.platform_commands.clear()

    def unregister_by_plugin_name(self, plugin_name: str):
        """
        根据插件名卸载相关的消息和命令处理器
        """
        # 卸载命令
        commands_to_remove = [name for name, info in self.commands.items() if info["plugin_name"] == plugin_name]
        for name in commands_to_remove:
            del self.commands[name]
        
        # 卸载通用消息处理器
        self.message_handlers = [h for h in self.message_handlers if h["plugin_name"] != plugin_name]
        for platform in list(self.platform_handlers):
            self.platform_handlers[platform] = [
                h for h in self.platform_handlers[platform] if h["plugin_name"] != plugin_name
            ]
        for platform in list(self.platform_commands):
            self.platform_commands[platform] = {
                k: v for k, v in self.platform_commands[platform].items()
                if v.get("plugin_name") != plugin_name
            }

    def on_message(self, **kwargs) -> Callable:
        """
        注册通用消息处理器
        
        Args:
            priority: 处理器优先级，数值越小优先级越高，默认为 10
            block: 是否阻断后续处理器，默认为 False
        """
        priority = kwargs.get('priority', 10)
        block = kwargs.get('block', False)
        
        def decorator(func: Callable) -> Callable:
            module = inspect.getmodule(func)
            plugin_name = module.__name__ if module else "Unknown"
            self.message_handlers.append({
                "func": func, 
                "plugin_name": plugin_name,
                "priority": priority,
                "block": block
            })
            return func
        return decorator

    def command(
        self,
        *names: str,
        permission: Optional[Permission] = None,
        override_permission_check: bool = False
    ) -> Callable:
        """
        注册命令处理器
        """
        def decorator(func: Callable) -> Callable:
            module = inspect.getmodule(func)
            plugin_name = module.__name__ if module else "Unknown"
            for name in names:
                self.commands[name] = {
                    "func": func,
                    "permission": permission,
                    "override_permission_check": override_permission_check,
                    "plugin_name": plugin_name,
                }
            return func
        return decorator

    def platform_message(self, platforms, **kwargs) -> Callable:
        """注册平台感知的通用消息处理器（CommandContext 分发）。"""
        priority = kwargs.get('priority', 10)
        block = kwargs.get('block', False)
        if isinstance(platforms, str):
            platforms = [platforms]

        def decorator(func: Callable) -> Callable:
            module = inspect.getmodule(func)
            plugin_name = module.__name__ if module else "Unknown"
            for platform in platforms:
                self.platform_handlers.setdefault(platform, []).append({
                    "func": func,
                    "plugin_name": plugin_name,
                    "priority": priority,
                    "block": block,
                })
            return func

        return decorator

    def platform_command(
        self,
        platforms,
        *names: str,
        permission: Optional[Permission] = None,
        override_permission_check: bool = False,
    ) -> Callable:
        """注册平台感知的指令（CommandContext 分发）。"""
        if isinstance(platforms, str):
            platforms = [platforms]

        def decorator(func: Callable) -> Callable:
            module = inspect.getmodule(func)
            plugin_name = module.__name__ if module else "Unknown"
            for platform in platforms:
                for name in names:
                    self.platform_commands.setdefault(platform, {})[name] = {
                        "func": func,
                        "permission": permission,
                        "override_permission_check": override_permission_check,
                        "plugin_name": plugin_name,
                    }
            return func

        return decorator

    async def handle(self, bot: "Bot", event: Any):
        """
        处理消息事件，分发给命令处理器或通用消息处理器
        """
        # 原子化地增加接收消息总数
        try:
            lua_script = "return redis.call('INCR', KEYS[1])"
            await redis_manager.execute_lua_script(
                script=lua_script,
                keys=["neobot:stats:messages_received"],
                args=[]
            )
        except Exception as e:
            logger.error(f"接收消息计数失败: {e}")

        # 按优先级排序消息处理器（旧注册 + QQ 平台注册合并，数值越小优先级越高）
        sorted_handlers = sorted(
            list(self.message_handlers) + list(self.platform_handlers.get("qq", [])),
            key=lambda h: h.get("priority", 10),
        )
        dispatch_logger = ModuleLogger("EventDispatch")
        dispatch_logger.debug(f"[EventDispatch:TRACE] 开始分发消息事件: raw='{event.raw_message[:80] if event.raw_message else ''}', handlers={len(sorted_handlers)}")

        for handler_info in sorted_handlers:
            consumed = await self._run_handler(handler_info["func"], bot, event)
            handler_block = handler_info.get("block", False)
            dispatch_logger.debug(f"[EventDispatch:TRACE] handler 返回: consumed={consumed}, block={handler_block}")
            if consumed or handler_block:
                if handler_block and not consumed:
                    dispatch_logger.warning(
                        f"[EventDispatch] handler 阻断事件分发: plugin={handler_info['plugin_name']}, "
                        f"priority={handler_info.get('priority', 10)}, "
                        f"raw_message='{event.raw_message[:80] if event.raw_message else ''}'"
                    )
                return

        if not event.raw_message:
            dispatch_logger.debug("[EventDispatch:TRACE] 无 raw_message，跳过命令匹配")
            return

        raw_text = event.raw_message.strip()
        prefix_found = next((p for p in self.prefixes if raw_text.startswith(p)), None)

        if not prefix_found:
            dispatch_logger.debug(f"[EventDispatch:TRACE] 未匹配命令前缀，跳过: raw='{raw_text[:60]}'")
            return

        command_parts = raw_text[len(prefix_found):].split()
        if not command_parts:
            return

        command_name = command_parts[0]
        args = command_parts[1:]

        if command_name in self.commands:
            dispatch_logger.debug(f"[EventDispatch:TRACE] 匹配命令: /{command_name}, args={args}")
            command_info = self.commands[command_name]
            func = command_info["func"]
            permission = command_info.get("permission")
            override_check = command_info.get("override_permission_check", False)

            permission_granted = True
            if permission:
                permission_granted = await permission_manager.check_permission(event.user_id, permission)

            if not permission_granted and not override_check:
                permission_name = permission.name if isinstance(permission, Permission) else permission
                message_template = global_config.bot.permission_denied_message
                await bot.send(event, message_template.format(permission_name=permission_name))
                return

            # 在执行指令前，增加指令调用次数
            try:
                lua_script = "return redis.call('HINCRBY', KEYS[1], ARGV[1], 1)"
                await redis_manager.execute_lua_script(
                    script=lua_script,
                    keys=["neobot:command_stats"],
                    args=[command_name]
                )
            except Exception as e:
                logger.error(f"指令 /{command_name} 调用次数统计失败: {e}")

            await self._run_handler(
                func,
                bot,
                event,
                args=args,
                permission_granted=permission_granted
            )
        else:
            dispatch_logger.debug(f"[EventDispatch:TRACE] 命令未注册: /{command_name}")
            # 阶段 2/3：QQ 平台已迁移到 CommandContext 的指令（mcc 等）在这里桥接
            if self.platform_commands.get("qq"):
                from neobot.core.messaging.context import CommandContext
                ctx = CommandContext.from_onebot_event(event, bot)
                await self._dispatch_platform_commands(ctx)

    async def handle_platform(self, ctx: Any):
        """
        平台感知分发：只运行该平台注册的消息处理器与指令。
        ctx 为 CommandContext（属性与 MessageEvent 兼容）。
        """
        dispatch_logger = ModuleLogger("EventDispatch")
        dispatch_logger.debug(
            f"[PlatformDispatch:TRACE] platform={getattr(ctx, 'platform', '?')}, "
            f"raw='{(getattr(ctx, 'raw_message', '') or '')[:80]}'"
        )

        handlers = list(self.platform_handlers.get(getattr(ctx, "platform", ""), []))
        handlers += list(self.platform_handlers.get("", []))
        handlers.sort(key=lambda h: h.get("priority", 10))
        for handler_info in handlers:
            consumed = await self._run_handler(handler_info["func"], ctx.bot, ctx)
            if consumed or handler_info.get("block", False):
                return

        raw_text = (getattr(ctx, "raw_message", "") or "").strip()
        prefix_found = next((p for p in self.prefixes if raw_text.startswith(p)), None)
        if not prefix_found:
            return
        await self._dispatch_platform_commands(ctx, raw_text=raw_text, prefix_found=prefix_found)

    async def _dispatch_platform_commands(self, ctx: Any, raw_text: str = "", prefix_found: str = ""):
        """平台指令分发（command 名匹配 + 权限 + 执行）。"""
        dispatch_logger = ModuleLogger("EventDispatch")

        if not raw_text:
            raw_text = (getattr(ctx, "raw_message", "") or "").strip()
        if not prefix_found:
            prefix_found = next((p for p in self.prefixes if raw_text.startswith(p)), None)
        if not prefix_found:
            return
        parts = raw_text[len(prefix_found):].split()
        if not parts:
            return
        command_name, args = parts[0], parts[1:]

        platform = getattr(ctx, "platform", "")
        command_info = (
            self.platform_commands.get(platform, {}).get(command_name)
            or self.platform_commands.get("", {}).get(command_name)
        )
        if not command_info:
            dispatch_logger.debug(f"[PlatformDispatch] 平台 {platform} 未注册指令 /{command_name}")
            return

        func = command_info["func"]
        permission = command_info.get("permission")
        override_check = command_info.get("override_permission_check", False)
        if permission and not override_check:
            granted = await permission_manager.check_permission(ctx.user_id, permission)
            if not granted:
                permission_name = permission.name if isinstance(permission, Permission) else permission
                template = global_config.bot.permission_denied_message
                await ctx.reply(template.format(permission_name=permission_name))
                return

        await self._run_handler(func, ctx.bot, ctx, args=args, permission_granted=True)


class NoticeHandler(BaseHandler):
    """
    通知事件处理器
    """
    def clear(self):
        self.handlers.clear()

    def unregister_by_plugin_name(self, plugin_name: str):
        """
        根据插件名卸载相关的通知处理器
        """
        self.handlers = [h for h in self.handlers if h["plugin_name"] != plugin_name]

    def register(self, notice_type: Optional[str] = None) -> Callable:
        """
        注册通知处理器
        """
        def decorator(func: Callable) -> Callable:
            module = inspect.getmodule(func)
            plugin_name = module.__name__ if module else "Unknown"
            self.handlers.append({"type": notice_type, "func": func, "plugin_name": plugin_name})
            return func
        return decorator

    async def handle(self, bot: "Bot", event: Any):
        """
        处理通知事件
        """
        for handler in self.handlers:
            if handler["type"] is None or handler["type"] == event.notice_type:
                await self._run_handler(handler["func"], bot, event)


class RequestHandler(BaseHandler):
    """
    请求事件处理器
    """
    def clear(self):
        self.handlers.clear()

    def unregister_by_plugin_name(self, plugin_name: str):
        """
        根据插件名卸载相关的请求处理器
        """
        self.handlers = [h for h in self.handlers if h["plugin_name"] != plugin_name]

    def register(self, request_type: Optional[str] = None) -> Callable:
        """
        注册请求处理器
        """
        def decorator(func: Callable) -> Callable:
            module = inspect.getmodule(func)
            plugin_name = module.__name__ if module else "Unknown"
            self.handlers.append({"type": request_type, "func": func, "plugin_name": plugin_name})
            return func
        return decorator

    async def handle(self, bot: "Bot", event: Any):
        """
        处理请求事件
        """
        for handler in self.handlers:
            if handler["type"] is None or handler["type"] == event.request_type:
                await self._run_handler(handler["func"], bot, event)
