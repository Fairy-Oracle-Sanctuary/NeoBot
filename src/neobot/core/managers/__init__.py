"""
NEO Bot Managers Package

管理器模块，包含各种功能管理器。
"""

from .bot_manager import bot_manager
from .browser_manager import browser_manager
from .command_manager import matcher as command_manager, matcher
from .image_manager import image_manager
from .mysql_manager import mysql_manager
from .permission_manager import permission_manager
from .plugin_manager import plugin_manager
from .redis_manager import redis_manager
from .reverse_ws_manager import reverse_ws_manager
from .thread_manager import thread_manager
__all__ = [
    "bot_manager",
    "browser_manager",
    "command_manager",
    "image_manager",
    "matcher",
    "mysql_manager",
    "permission_manager",
    "plugin_manager",
    "redis_manager",
    "reverse_ws_manager",
    "thread_manager",
]
