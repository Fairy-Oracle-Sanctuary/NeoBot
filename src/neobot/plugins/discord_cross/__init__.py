# -*- coding: utf-8 -*-
"""
跨平台消息互通插件入口
"""
from neobot.core.utils.logger import ModuleLogger
from .config import config
from .subscription import start_cross_platform_subscription, stop_cross_platform_subscription
from .handlers import *

# 创建模块专用日志记录器
logger = ModuleLogger("CrossPlatform")


async def start():
    """插件启动入口：重载配置并启动 Redis 跨平台订阅。"""
    await config.reload()
    await start_cross_platform_subscription()


async def shutdown():
    """停止跨平台订阅并释放资源。"""
    await stop_cross_platform_subscription()
