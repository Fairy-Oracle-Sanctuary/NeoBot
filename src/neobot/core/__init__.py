"""
NEO Bot Core Package

核心框架模块，包含事件处理、API封装、管理器等核心功能。
"""

from .api import MessageAPI, GroupAPI, FriendAPI, AccountAPI, MediaAPI
from .bot import Bot
from .config_loader import global_config
from .permission import Permission
from .plugin import Plugin

__all__ = [
    "MessageAPI",
    "GroupAPI",
    "FriendAPI",
    "AccountAPI",
    "MediaAPI",
    "Bot",
    "global_config",
    "Permission",
    "Plugin",
]
