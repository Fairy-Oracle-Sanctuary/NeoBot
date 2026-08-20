"""
Bot 对象 —— 插件 API 契约 (plugin-api-v1)。

事件处理器签名中的 ``bot: Bot`` 类型标注请使用本模块导出的 :class:`Bot`,
它聚合了消息 / 群组 / 好友 / 账号 / 媒体全部 OneBot API(见 ``docs/api`` 系列文档)。
"""
from __future__ import annotations

from neobot.core.bot import Bot

__all__ = ["Bot"]
