"""
插件生命周期钩子 —— 插件 API 契约 (plugin-api-v1)。

需要后台任务的插件用 :func:`on_startup` / :func:`on_shutdown` 自注册。
``PluginManager`` 在插件加载完成且 Redis 就绪后统一调用启动钩子,
在热重载前和进程退出时调用关闭钩子。框架核心不点名任何具体插件。

同一模块内同名函数重复注册会替换旧钩子,避免 ``importlib.reload``
重新执行装饰器时把钩子叠成多份。
"""
from __future__ import annotations

from typing import Any, Callable, Dict, List

Hook = Callable[..., Any]

_startup: Dict[str, List[Hook]] = {}
_shutdown: Dict[str, List[Hook]] = {}


def _register(bucket: Dict[str, List[Hook]], func: Hook) -> Hook:
    module_name = func.__module__
    kept = [hook for hook in bucket.get(module_name, []) if hook.__name__ != func.__name__]
    kept.append(func)
    bucket[module_name] = kept
    return func


def on_startup(func: Hook) -> Hook:
    """注册插件启动钩子。

    在全部插件 import 完成、Redis 初始化之后调用;该模块热重载成功后再次调用。
    钩子可以是同步或异步函数。单个钩子抛错只记日志,不影响其他插件,也不影响发送消息。
    """
    return _register(_startup, func)


def on_shutdown(func: Hook) -> Hook:
    """注册插件关闭钩子。

    在该模块热重载之前,以及进程退出时调用,用于取消后台任务。
    必须在 ``importlib.reload`` 改写模块全局变量之前执行,否则旧任务句柄会丢失。
    """
    return _register(_shutdown, func)


def hooks_for(module_name: str, kind: str) -> List[Hook]:
    """返回某模块已注册的启动或关闭钩子(拷贝,按注册顺序)。"""
    bucket = _startup if kind == "startup" else _shutdown
    return list(bucket.get(module_name, []))


def clear_module_hooks(module_name: str) -> None:
    """移除某模块的全部生命周期钩子(测试与卸载时使用)。"""
    _startup.pop(module_name, None)
    _shutdown.pop(module_name, None)
