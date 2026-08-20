"""
注册装饰器 —— 插件 API 契约 (plugin-api-v1)。

模块级函数的命令 / 事件注册入口。框架内部委托给 ``matcher``,
但插件侧只允许使用这里(以及 ``neobot.plugin_api`` 顶层)导出的符号。

与 ``neobot.plugin_api.plugin``(类风格标记装饰器)的区别:
- 本模块装饰器直接注册模块级函数;
- ``plugin`` 子模块的装饰器用于 ``Plugin`` 子类方法,由基类统一注册。
"""
from __future__ import annotations

from typing import Any, Callable, Optional

from neobot.core.managers.command_manager import matcher as _matcher


def command(
    *names: str,
    permission: Optional[Any] = None,
    override_permission_check: bool = False,
) -> Callable:
    """
    注册消息指令。``/指令名`` 触发,参数以 ``args: list[str]`` 形式传入。

    :param names: 指令名(可带别名,如 ``command("echo", "复读")``)。
    :param permission: 需要的权限级别(见 :class:`neobot.plugin_api.Permission`)。
    :param override_permission_check: 为 True 时以 ``permission_granted: bool``
        作为处理器最后一个参数,由插件自行决定放行逻辑。
    """
    return _matcher.command(
        *names,
        permission=permission,
        override_permission_check=override_permission_check,
    )


def platform_command(
    platforms,
    *names: str,
    permission: Optional[Any] = None,
    override_permission_check: bool = False,
) -> Callable:
    """
    注册平台感知指令(仅对指定平台生效)。

    :param platforms: 平台名列表,如 ``["qq", "discord"]``。
    """
    return _matcher.platform_command(
        platforms,
        *names,
        permission=permission,
        override_permission_check=override_permission_check,
    )


def on_message(**kwargs) -> Callable:
    """注册通用消息处理器:监听所有非指令消息。"""
    return _matcher.on_message(**kwargs)


def platform_message(platforms, **kwargs) -> Callable:
    """注册平台感知的通用消息处理器。"""
    return _matcher.platform_message(platforms, **kwargs)


def on_notice(notice_type: Optional[str] = None) -> Callable:
    """
    注册通知事件处理器。

    :param notice_type: 通知子类型,如 ``group_increase``;为 None 时接收全部。
    """
    return _matcher.on_notice(notice_type=notice_type)


def on_request(request_type: Optional[str] = None) -> Callable:
    """
    注册请求事件处理器(好友 / 群申请)。

    :param request_type: 请求子类型,如 ``friend`` / ``group``;为 None 时接收全部。
    """
    return _matcher.on_request(request_type=request_type)
