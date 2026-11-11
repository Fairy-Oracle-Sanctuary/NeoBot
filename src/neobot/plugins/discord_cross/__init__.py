# -*- coding: utf-8 -*-
"""
跨平台消息互通插件入口
"""
from neobot.plugin_api import ModuleLogger, on_shutdown, on_startup
from .config import config
# 导入 handlers 以注册其平台消息/命令装饰器（副作用导入，符号经 __all__ 标记保留）
from .handlers import (
    cross_config_command,
    cross_reload_command,
    handle_discord_message,
    handle_qq_group_message,
    handle_qq_message,
)
# 副作用导入：加载 subscription 时会注册 forwarder 的消息总线订阅
from .subscription import (  # noqa: F401
    start_cross_platform_subscription,
    stop_cross_platform_subscription,
)

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


@on_startup
async def start():
    """插件启动入口：重载配置并启动 Redis 跨平台订阅。

    函数体内再导入一次，热重载子模块后重新执行启动钩子时能拿到新函数。
    """
    from .config import config as cross_config
    from .subscription import start_cross_platform_subscription as start_subscription

    await cross_config.reload()
    await start_subscription()


@on_shutdown
async def shutdown():
    """停止跨平台订阅并释放资源。"""
    from .subscription import stop_cross_platform_subscription as stop_subscription

    await stop_subscription()
