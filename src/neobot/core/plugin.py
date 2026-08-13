import inspect
import functools
from typing import Optional, Union, Any, Callable
from neobot.core.managers.command_manager import matcher as command_manager
from neobot.core.permission import Permission
from neobot.models.events.message import MessageEvent

class Plugin:
    """
    插件基类，提供类风格的插件编写方式。
    通过继承此类，可以使用装饰器在类方法上注册命令和事件处理器。
    """
    def __init__(self):
        self._register_handlers()

    def _register_handlers(self):
        """
        自动注册带有装饰器的方法。
        """
        # 遍历实例的所有方法
        for name, method in inspect.getmembers(self, predicate=inspect.ismethod):
            # 检查是否有命令元数据
            if hasattr(method, "_command_meta"):
                meta = method._command_meta
                # 调用 command_manager 的装饰器来注册绑定后的方法
                command_manager.command(
                    *meta['names'], 
                    permission=meta.get('permission'),
                    override_permission_check=meta.get('override_permission_check', False)
                )(method)
            
            # 检查是否有消息处理元数据
            if hasattr(method, "_on_message_meta"):
                command_manager.on_message()(method)
            
            # 检查是否有通知处理元数据
            if hasattr(method, "_on_notice_meta"):
                meta = method._on_notice_meta
                command_manager.on_notice(notice_type=meta.get('notice_type'))(method)
            
            # 检查是否有请求处理元数据
            if hasattr(method, "_on_request_meta"):
                meta = method._on_request_meta
                command_manager.on_request(request_type=meta.get('request_type'))(method)

    async def send(self, event: MessageEvent, message: Union[str, Any]):
        """
        发送消息的基础逻辑。
        """
        if hasattr(event, 'reply'):
            await event.reply(message)
        else:
            pass

    async def reply(self, event: MessageEvent, message: Union[str, Any]):
        """
        回复消息。
        """
        await self.send(event, message)

class SimplePlugin(Plugin):
    """
    面向新手的简化插件基类。
    
    特性：
    1. 自动将公共方法（不以_开头）注册为指令。
    2. 指令名默认为方法名。
    3. 自动解析参数类型。
    4. 支持直接返回字符串来回复消息。
    """
    def _register_handlers(self):
        # 先处理带装饰器的方法
        super()._register_handlers()
        
        # 扫描普通方法并注册为指令
        for name, method in inspect.getmembers(self, predicate=inspect.ismethod):
            if name.startswith("_"):
                continue
            if hasattr(method, "_command_meta"):
                continue # 已经处理过
            if hasattr(method, "_on_message_meta"):
                continue
            if hasattr(method, "_on_notice_meta"):
                continue
            if hasattr(method, "_on_request_meta"):
                continue
            if name in dir(Plugin):
                continue # 忽略基类方法
            
            self._register_method_as_command(name, method)

    def _register_method_as_command(self, name: str, method: Callable):
        # 获取方法的签名
        sig = inspect.signature(method)
        
        # 包装函数
        @functools.wraps(method)
        async def wrapper(event: MessageEvent, args: list[str]):
            try:
                # 准备调用参数
                call_args: list[Any] = []
                
                # 跳过 self，第一个参数应该是 event
                params = list(sig.parameters.values())
                if not params:
                    # 方法没有参数？这不应该发生，至少要有 event
                    await method() 
                    return

                # 绑定 event
                call_args.append(event)
                
                # 处理剩余参数
                method_params = params[1:] # 除去 event
                
                if not method_params:
                    # 方法不需要额外参数
                    pass
                elif len(method_params) == 1:
                    # 只有一个参数，把所有 args 拼起来传给它
                    param = method_params[0]
                    if args:
                        str_val = " ".join(args)
                        val: Any = str_val
                        # 类型转换
                        if param.annotation is int:
                            val = int(str_val)
                        elif param.annotation is float:
                            val = float(str_val)
                        call_args.append(val)
                    elif param.default is not inspect.Parameter.empty:
                        call_args.append(param.default)
                    else:
                        await event.reply(f"缺少参数: {param.name}")
                        return
                else:
                    # 多个参数，尝试一一对应
                    if len(args) < len([p for p in method_params if p.default is inspect.Parameter.empty]):
                        # 必填参数不足
                        usage = " ".join([f"<{p.name}>" for p in method_params])
                        await event.reply(f"参数不足。用法: /{name} {usage}")
                        return
                    
                    for i, param in enumerate(method_params):
                        if i < len(args):
                            arg_str = args[i]
                            arg_val: Any = arg_str
                            # 简单的类型转换
                            try:
                                if param.annotation is int:
                                    arg_val = int(arg_str)
                                elif param.annotation is float:
                                    arg_val = float(arg_str)
                            except ValueError:
                                await event.reply(f"参数 {param.name} 类型错误，应为 {param.annotation.__name__}")
                                return
                            call_args.append(arg_val)
                        else:
                            call_args.append(param.default)

                # 调用方法
                result = await method(*call_args)
                
                # 如果有返回值，自动回复
                if result is not None:
                    await event.reply(str(result))
                    
            except Exception as e:
                await event.reply(f"执行命令时发生错误: {str(e)}")

        # 注册命令
        command_manager.command(name)(wrapper)


def command(name: str, *aliases: str, permission: Optional[Permission] = None, override_permission_check: bool = False):
    """
    装饰器：标记方法为命令处理器。
    """
    def decorator(func):
        func._command_meta = {
            "names": (name,) + aliases,
            "permission": permission,
            "override_permission_check": override_permission_check
        }
        return func
    return decorator

def on_message():
    """
    装饰器：标记方法为通用消息处理器。
    """
    def decorator(func):
        func._on_message_meta = {}
        return func
    return decorator

def on_notice(notice_type: Optional[str] = None):
    """
    装饰器：标记方法为通知处理器。
    """
    def decorator(func):
        func._on_notice_meta = {
            "notice_type": notice_type
        }
        return func
    return decorator

def on_request(request_type: Optional[str] = None):
    """
    装饰器：标记方法为请求处理器。
    """
    def decorator(func):
        func._on_request_meta = {
            "request_type": request_type
        }
        return func
    return decorator
