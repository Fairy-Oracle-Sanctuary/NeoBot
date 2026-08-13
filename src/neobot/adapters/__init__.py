"""
NEO Bot Adapters Package

适配器模块，用于连接不同的平台（如 Discord）或提供调试接口（CLI）。
"""

try:
    from .discord_adapter import DiscordAdapter
except ImportError:
    DiscordAdapter = None  # Discord 依赖可能未安装，容错处理

from .cli_adapter import MockBot, CLIDebugger

try:
    from .mcc_adapter import mcc as mcc_adapter
except ImportError:
    mcc_adapter = None  # MCC 适配器依赖异常时容错

__all__ = ["DiscordAdapter", "MockBot", "CLIDebugger", "mcc_adapter"]
