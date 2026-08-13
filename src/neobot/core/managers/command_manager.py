"""
命令与事件管理器模块

该模块定义了 `CommandManager` 类，它是整个机器人框架事件处理的核心。
它通过装饰器模式，为插件提供了注册消息指令、通知事件处理器和
请求事件处理器的能力。
"""

from typing import Any, Callable, Dict, Optional, Tuple

from neobot.models.events.message import MessageSegment



from ..config_loader import global_config
from ..handlers.event_handler import MessageHandler, NoticeHandler, RequestHandler
from .redis_manager import redis_manager
from .image_manager import image_manager
from ..utils.logger import logger

# 从配置中获取命令前缀
_config_prefixes = global_config.bot.command

# 确保前缀配置是元组格式
_final_prefixes: Tuple[str, ...]
if isinstance(_config_prefixes, list):
    _final_prefixes = tuple(_config_prefixes)
elif isinstance(_config_prefixes, str):
    _final_prefixes = (_config_prefixes,)
else:
    _final_prefixes = tuple(_config_prefixes)


class CommandManager:
    """
    命令管理器，负责注册和分发所有类型的事件。

    这是一个单例对象（`matcher`），在整个应用中共享。
    它将不同类型的事件处理委托给专门的处理器类。
    """

    def __init__(self, prefixes: Tuple[str, ...]):
        """
        初始化命令管理器。

        Args:
            prefixes (Tuple[str, ...]): 一个包含所有合法命令前缀的元组。
        """
        self.plugins: Dict[str, Dict[str, Any]] = {}

        # 初始化专门的事件处理器
        self.message_handler = MessageHandler(prefixes)
        self.notice_handler = NoticeHandler()
        self.request_handler = RequestHandler()

        # 将处理器映射到事件类型
        self.handler_map = {
            "message": self.message_handler,
            "notice": self.notice_handler,
            "request": self.request_handler,
        }

        # 注册内置的 /help 命令
        self._register_internal_commands()

    async def sync_help_pic(self):
        """
        启动时或插件重载时同步 help 图片到 Redis
        """
        try:
            logger.info("正在生成帮助图片...")
            
            # 1. 收集插件数据
            plugins_data = []
            for plugin_name, meta in self.plugins.items():
                plugins_data.append({
                    "name": meta.get("name", plugin_name),
                    "description": meta.get("description", "暂无描述"),
                    "usage": meta.get("usage", "暂无用法")
                })
            
            # 2. 渲染图片
            # 使用 png 格式以获得更好的文字清晰度
            base64_str = await image_manager.render_template_to_base64(
                template_name="help.html",
                data={"plugins": plugins_data},
                output_name="help_menu.png",
                image_type="png"
            )
            
            if base64_str:
                await redis_manager.set("neobot:core:help_pic", base64_str)
                logger.success("帮助图片已更新并缓存到 Redis")
            else:
                logger.error("帮助图片生成失败")
                
        except Exception as e:
            logger.error(f"同步帮助图片失败: {e}")

    def _register_internal_commands(self):
        """
        注册框架内置的命令
        """
        # Help 命令
        self.message_handler.command("help")(self._help_command)
        self.plugins["core.help"] = {
            "name": "帮助",
            "description": "显示所有可用指令的帮助信息",
            "usage": "/help",
        }

    def clear_all_handlers(self):
        """
        清空所有已注册的事件处理器。
        注意：这也会移除内置的 /help 命令，因此需要重新注册。
        """
        self.message_handler.clear()
        self.notice_handler.clear()
        self.request_handler.clear()
        self.plugins.clear()

        # 清空后，需要重新注册内置命令
        self._register_internal_commands()

    def unload_plugin(self, plugin_name: str):
        """
        卸载指定插件的所有处理器和命令。

        Args:
            plugin_name (str): 插件的模块名 (例如 'plugins.bili_parser')
        """
        self.message_handler.unregister_by_plugin_name(plugin_name)
        self.notice_handler.unregister_by_plugin_name(plugin_name)
        self.request_handler.unregister_by_plugin_name(plugin_name)

        # 移除插件元信息
        plugins_to_remove = [name for name in self.plugins if name == plugin_name]
        for name in plugins_to_remove:
            del self.plugins[name]

    # --- 装饰器代理 ---

    def on_message(self, **kwargs) -> Callable:
        """
        装饰器：注册一个通用的消息处理器。
        """
        return self.message_handler.on_message(**kwargs)

    def command(
        self,
        *names: str,
        permission: Optional[Any] = None,
        override_permission_check: bool = False,
    ) -> Callable:
        """
        装饰器：注册一个消息指令处理器。
        """
        return self.message_handler.command(
            *names,
            permission=permission,
            override_permission_check=override_permission_check,
        )

    def platform_message(self, platforms, **kwargs) -> Callable:
        """注册平台感知的通用消息处理器（CommandContext 分发）。"""
        return self.message_handler.platform_message(platforms, **kwargs)

    def platform_command(
        self,
        platforms,
        *names: str,
        permission: Optional[Any] = None,
        override_permission_check: bool = False,
    ) -> Callable:
        """注册平台感知的指令（CommandContext 分发）。"""
        return self.message_handler.platform_command(
            platforms,
            *names,
            permission=permission,
            override_permission_check=override_permission_check,
        )

    def on_notice(self, notice_type: Optional[str] = None) -> Callable:
        """
        装饰器：注册一个通知事件处理器。
        """
        return self.notice_handler.register(notice_type=notice_type)

    def on_request(self, request_type: Optional[str] = None) -> Callable:
        """
        装饰器：注册一个请求事件处理器。
        """
        return self.request_handler.register(request_type=request_type)

    # --- 事件处理 ---

    async def handle_event(self, bot, event):
        """
        统一的事件分发入口。

        根据事件的 `post_type` 将其分发给对应的处理器。
        """
        if event.post_type == "message" and global_config.bot.ignore_self_message:
            if (
                hasattr(event, "user_id")
                and hasattr(event, "self_id")
                and event.user_id == event.self_id
            ):
                return

        handler = self.handler_map.get(event.post_type)
        if handler:
            await handler.handle(bot, event)

    async def handle_platform_event(self, ctx):
        """
        平台感知事件分发入口（CommandContext）。
        """
        await self.message_handler.handle_platform(ctx)

    # --- 内置命令实现 ---

    async def _help_command(self, bot, event):
        """
        内置的 `/help` 命令的实现。
        直接从 Redis 获取缓存的图片。
        """
        try:
            # 1. 尝试从 Redis 获取
            help_pic = await redis_manager.get("neobot:core:help_pic")
            
            if not help_pic:
                await bot.send(event, "帮助图片缓存缺失，正在重新生成...")
                await self.sync_help_pic()
                help_pic = await redis_manager.get("neobot:core:help_pic")
                
            if help_pic:
                await bot.send(event, MessageSegment.image(help_pic))
                return
        except Exception as e:
            logger.error(f"获取或生成帮助图片失败: {e}")

        # 2. 最后的兜底：发送纯文本
        help_text = "--- 可用指令列表 ---\n"
        for plugin_name, meta in self.plugins.items():
            name = meta.get("name", "未命名插件")
            description = meta.get("description", "暂无描述")
            usage = meta.get("usage", "暂无用法说明")

            help_text += f"\n{name}:\n"
            help_text += f"  功能: {description}\n"
            help_text += f"  用法: {usage}\n"

        await bot.send(event, help_text.strip())


# 实例化全局唯一的命令管理器
matcher = CommandManager(prefixes=_final_prefixes)
