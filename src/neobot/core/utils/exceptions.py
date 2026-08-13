"""
自定义异常模块

该模块定义了项目中使用的各种自定义异常类，用于提供更精确、更友好的错误提示。
"""

class SyncHandlerError(Exception):
    """
    当尝试注册同步函数作为异步事件处理器时抛出此异常。
    """
    pass


class WebSocketError(Exception):
    """
    WebSocket相关错误的基类。
    
    Args:
        message: 错误消息
        code: 错误代码（可选）
        original_error: 原始异常对象（可选）
    """
    def __init__(self, message, code=None, original_error=None):
        self.message = message
        self.code = code
        self.original_error = original_error
        super().__init__(message)


class WebSocketConnectionError(WebSocketError):
    """
    WebSocket连接失败时抛出此异常。
    """
    pass


class WebSocketAuthenticationError(WebSocketError):
    """
    WebSocket认证失败时抛出此异常。
    """
    pass


class PluginError(Exception):
    """
    插件相关错误的基类。
    
    Args:
        plugin_name: 插件名称
        message: 错误消息
        original_error: 原始异常对象（可选）
    """
    def __init__(self, plugin_name, message, original_error=None):
        self.plugin_name = plugin_name
        self.message = message
        self.original_error = original_error
        super().__init__(f"插件 {plugin_name}: {message}")


class PluginLoadError(PluginError):
    """
    插件加载失败时抛出此异常。
    """
    pass


class PluginReloadError(PluginError):
    """
    插件重载失败时抛出此异常。
    """
    pass


class PluginNotFoundError(PluginError):
    """
    找不到指定插件时抛出此异常。
    """
    pass


class ConfigError(Exception):
    """
    配置相关错误的基类。
    
    Args:
        section: 配置部分名称（可选）
        key: 配置项名称（可选）
        message: 错误消息（可选）
    """
    def __init__(self, section=None, key=None, message=None):
        self.section = section
        self.key = key
        self.message = message
        self.original_error = None
        
        if section and key and message:
            super().__init__(f"配置错误 [{section}.{key}]: {message}")
        elif section and message:
            super().__init__(f"配置错误 [{section}]: {message}")
        else:
            super().__init__(message or "配置错误")


class ConfigNotFoundError(ConfigError):
    """
    配置文件不存在时抛出此异常。
    """
    pass


class ConfigValidationError(ConfigError):
    """
    配置验证失败时抛出此异常。
    """
    pass


class NeoPermissionError(Exception):
    """
    权限相关错误的基类。

    注意：命名为 NeoPermissionError 以避免覆盖 Python 内置的 PermissionError。
    旧代码中若仍引用 exceptions.PermissionError，请统一迁移到 NeoPermissionError。

    Args:
        user_id: 用户ID
        operation: 操作名称
        message: 错误消息
    """
    def __init__(self, user_id=None, operation=None, message=None):
        self.user_id = user_id
        self.operation = operation
        self.message = message

        if user_id and operation and message:
            super().__init__(f"权限错误 [用户 {user_id}]: 无权限执行操作 {operation} - {message}")
        elif user_id and operation:
            super().__init__(f"权限错误 [用户 {user_id}]: 无权限执行操作 {operation}")
        else:
            super().__init__(message or "权限错误")


class CommandError(Exception):
    """
    命令处理相关错误的基类。
    
    Args:
        command: 命令名称
        message: 错误消息
        original_error: 原始异常对象（可选）
    """
    def __init__(self, command=None, message=None, original_error=None):
        self.command = command
        self.message = message
        self.original_error = original_error
        
        if command and message:
            super().__init__(f"命令错误 [{command}]: {message}")
        else:
            super().__init__(message or "命令错误")


class CommandNotFoundError(CommandError):
    """
    找不到指定命令时抛出此异常。
    """
    pass


class CommandParameterError(CommandError):
    """
    命令参数错误时抛出此异常。
    """
    pass


class RedisError(Exception):
    """
    Redis相关错误的基类。
    
    Args:
        message: 错误消息
        original_error: 原始异常对象（可选）
    """
    def __init__(self, message, original_error=None):
        self.message = message
        self.original_error = original_error
        super().__init__(message)


class BrowserManagerError(Exception):
    """
    浏览器管理器相关错误的基类。
    
    Args:
        message: 错误消息
        original_error: 原始异常对象（可选）
    """
    def __init__(self, message, original_error=None):
        self.message = message
        self.original_error = original_error
        super().__init__(message)


class BrowserPoolError(BrowserManagerError):
    """
    浏览器池相关错误时抛出此异常。
    """
    pass


class CodeExecutionError(Exception):
    """
    代码执行相关错误的基类。
    
    Args:
        message: 错误消息
        code: 执行的代码（可选）
        original_error: 原始异常对象（可选）
    """
    def __init__(self, message, code=None, original_error=None):
        self.message = message
        self.code = code
        self.original_error = original_error
        super().__init__(message)
