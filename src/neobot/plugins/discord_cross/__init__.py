# -*- coding: utf-8 -*-
"""
跨平台消息互通插件入口
"""
from neobot.plugin_api import ModuleLogger
from .config import config
# 导入 handlers 以注册其平台消息/命令装饰器（副作用导入，符号经 __all__ 标记保留）
from .handlers import (
    cross_config_command,
    cross_reload_command,
    handle_discord_message,
    handle_qq_group_message,
    handle_qq_message,
)
from .subscription import start_cross_platform_subscription, stop_cross_platform_subscription

# 副作用导入：handlers 的装饰器注册在 import 时生效，符号经 __all__ 标记为有意保留
__all__ = [
    "config",
    "logger",
    "start",
    "shutdown",
    "cross_config_command",
    "cross_reload_command",
    "handle_discord_message",
    "handle_qq_message",
    "handle_qq_group_message",
]

# 创建模块专用日志记录器
logger = ModuleLogger("CrossPlatform")


async def start():
    """插件启动入口：重载配置并启动 Redis 跨平台订阅。"""
    await config.reload()
    await start_cross_platform_subscription()


async def shutdown():
    """停止跨平台订阅并释放资源。"""
    await stop_cross_platform_subscription()
