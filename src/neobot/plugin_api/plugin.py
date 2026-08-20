"""
类风格插件基类 —— 插件 API 契约 (plugin-api-v1)。

适合结构化插件:继承 :class:`Plugin`(装饰器风格)或 :class:`SimplePlugin`
(方法即指令),并统一在文件末尾实例化::

    plugin = MyPlugin()

类内方法使用的标记装饰器请从本子模块导入:

    from neobot.plugin_api.plugin import command, on_message

注意与 ``neobot.plugin_api.command``(模块级注册装饰器)区分。
"""
from __future__ import annotations

from neobot.core.plugin import Plugin, SimplePlugin, command, on_message, on_notice, on_request
from neobot.core.permission import Permission

__all__ = [
    "Plugin",
    "SimplePlugin",
    "command",
    "on_message",
    "on_notice",
    "on_request",
    "Permission",
]
