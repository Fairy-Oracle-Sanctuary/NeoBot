"""
NEO Bot API Package

OneBot API 封装模块。
"""

from .account import AccountAPI
from .base import BaseAPI
from .friend import FriendAPI
from .group import GroupAPI
from .media import MediaAPI
from .message import MessageAPI

__all__ = [
    "AccountAPI",
    "BaseAPI",
    "FriendAPI",
    "GroupAPI",
    "MediaAPI",
    "MessageAPI",
]
