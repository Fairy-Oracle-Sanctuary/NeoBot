"""
NEO Bot Plugins Package

插件模块，包含所有业务逻辑插件。
"""

from . import admin
from . import auto_approve
from . import bot_status
from . import broadcast
from . import code_py
from . import discord_cross
from . import echo
from . import furry
from . import github_parser
from . import group_welcome
from . import jrcd
from . import mirror_avatar
from . import music
from . import thpic
from . import twitter_parser
from . import weather

__all__ = [
    "admin",
    "auto_approve",
    "bot_status",
    "broadcast",
    "code_py",
    "discord_cross",
    "echo",
    "furry",
    "github_parser",
    "group_welcome",
    "jrcd",
    "mirror_avatar",
    "music",
    "thpic",
    "twitter_parser",
    "weather",
]
