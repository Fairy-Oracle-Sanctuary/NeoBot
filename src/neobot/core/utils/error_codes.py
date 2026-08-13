"""
错误码和统一响应格式模块

该模块定义了项目中使用的错误码和统一的错误响应格式，确保所有模块返回一致的错误信息。
"""
from typing import Optional

# 错误码定义
class ErrorCode:
    """
    错误码枚举类，包含所有系统错误码的定义。
    
    错误码规则：
    - 1xxx: 系统级错误
    - 2xxx: WebSocket相关错误
    - 3xxx: 插件相关错误
    - 4xxx: 配置相关错误
    - 5xxx: 权限相关错误
    - 6xxx: 命令相关错误
    - 7xxx: Redis相关错误
    - 8xxx: 浏览器管理器相关错误
    - 9xxx: 代码执行相关错误
    """
    # 系统级错误
    SUCCESS = 0                     # 成功
    UNKNOWN_ERROR = 1000            # 未知错误
    INVALID_PARAMETER = 1001        # 参数无效
    DATABASE_ERROR = 1002           # 数据库错误
    NETWORK_ERROR = 1003            # 网络错误
    TIMEOUT_ERROR = 1004            # 超时错误
    RESOURCE_EXHAUSTED = 1005       # 资源耗尽
    
    # WebSocket相关错误
    WS_CONNECTION_FAILED = 2000     # WebSocket连接失败
    WS_AUTH_FAILED = 2001           # WebSocket认证失败
    WS_DISCONNECTED = 2002          # WebSocket已断开
    WS_MESSAGE_ERROR = 2003         # WebSocket消息错误
    
    # 插件相关错误
    PLUGIN_LOAD_FAILED = 3000       # 插件加载失败
    PLUGIN_RELOAD_FAILED = 3001     # 插件重载失败
    PLUGIN_NOT_FOUND = 3002         # 插件未找到
    PLUGIN_INVALID = 3003           # 插件无效
    PLUGIN_DEPENDENCY_ERROR = 3004  # 插件依赖错误
    
    # 配置相关错误
    CONFIG_NOT_FOUND = 4000         # 配置文件未找到
    CONFIG_PARSE_ERROR = 4001       # 配置解析错误
    CONFIG_VALIDATION_ERROR = 4002  # 配置验证错误
    CONFIG_KEY_NOT_FOUND = 4003     # 配置项未找到
    
    # 权限相关错误
    PERMISSION_DENIED = 5000        # 权限不足
    NOT_ADMIN = 5001                # 不是管理员
    USER_BANNED = 5002              # 用户已被禁止
    
    # 命令相关错误
    COMMAND_NOT_FOUND = 6000        # 命令未找到
    COMMAND_PARAM_ERROR = 6001      # 命令参数错误
    COMMAND_EXECUTE_ERROR = 6002    # 命令执行错误
    COMMAND_TIMEOUT = 6003          # 命令执行超时
    
    # Redis相关错误
    REDIS_CONNECTION_FAILED = 7000  # Redis连接失败
    REDIS_OPERATION_ERROR = 7001    # Redis操作错误
    
    # 浏览器管理器相关错误
    BROWSER_INIT_FAILED = 8000      # 浏览器初始化失败
    BROWSER_POOL_ERROR = 8001       # 浏览器池错误
    BROWSER_OPERATION_ERROR = 8002  # 浏览器操作错误
    
    # 代码执行相关错误
    CODE_EXECUTE_ERROR = 9000       # 代码执行错误
    CODE_SECURITY_ERROR = 9001      # 代码安全错误


# 错误码到错误消息的映射
ERROR_MESSAGES = {
    # 系统级错误
    ErrorCode.SUCCESS: "操作成功",
    ErrorCode.UNKNOWN_ERROR: "未知错误",
    ErrorCode.INVALID_PARAMETER: "参数无效",
    ErrorCode.DATABASE_ERROR: "数据库错误",
    ErrorCode.NETWORK_ERROR: "网络错误",
    ErrorCode.TIMEOUT_ERROR: "操作超时",
    ErrorCode.RESOURCE_EXHAUSTED: "资源耗尽",
    
    # WebSocket相关错误
    ErrorCode.WS_CONNECTION_FAILED: "WebSocket连接失败",
    ErrorCode.WS_AUTH_FAILED: "WebSocket认证失败",
    ErrorCode.WS_DISCONNECTED: "WebSocket已断开连接",
    ErrorCode.WS_MESSAGE_ERROR: "WebSocket消息格式错误",
    
    # 插件相关错误
    ErrorCode.PLUGIN_LOAD_FAILED: "插件加载失败",
    ErrorCode.PLUGIN_RELOAD_FAILED: "插件重载失败",
    ErrorCode.PLUGIN_NOT_FOUND: "插件未找到",
    ErrorCode.PLUGIN_INVALID: "插件无效",
    ErrorCode.PLUGIN_DEPENDENCY_ERROR: "插件依赖错误",
    
    # 配置相关错误
    ErrorCode.CONFIG_NOT_FOUND: "配置文件未找到",
    ErrorCode.CONFIG_PARSE_ERROR: "配置文件解析错误",
    ErrorCode.CONFIG_VALIDATION_ERROR: "配置验证失败",
    ErrorCode.CONFIG_KEY_NOT_FOUND: "配置项未找到",
    
    # 权限相关错误
    ErrorCode.PERMISSION_DENIED: "权限不足",
    ErrorCode.NOT_ADMIN: "需要管理员权限",
    ErrorCode.USER_BANNED: "用户已被禁止操作",
    
    # 命令相关错误
    ErrorCode.COMMAND_NOT_FOUND: "命令未找到",
    ErrorCode.COMMAND_PARAM_ERROR: "命令参数错误",
    ErrorCode.COMMAND_EXECUTE_ERROR: "命令执行错误",
    ErrorCode.COMMAND_TIMEOUT: "命令执行超时",
    
    # Redis相关错误
    ErrorCode.REDIS_CONNECTION_FAILED: "Redis连接失败",
    ErrorCode.REDIS_OPERATION_ERROR: "Redis操作错误",
    
    # 浏览器管理器相关错误
    ErrorCode.BROWSER_INIT_FAILED: "浏览器初始化失败",
    ErrorCode.BROWSER_POOL_ERROR: "浏览器池错误",
    ErrorCode.BROWSER_OPERATION_ERROR: "浏览器操作错误",
    
    # 代码执行相关错误
    ErrorCode.CODE_EXECUTE_ERROR: "代码执行错误",
    ErrorCode.CODE_SECURITY_ERROR: "代码存在安全风险",
}


def get_error_message(code: int) -> str:
    """
    根据错误码获取错误消息
    
    Args:
        code: 错误码
        
    Returns:
        str: 错误消息
    """
    return ERROR_MESSAGES.get(code, ERROR_MESSAGES[ErrorCode.UNKNOWN_ERROR])


def create_error_response(code: int, message: Optional[str] = None, data: Optional[dict] = None, request_id: Optional[str] = None) -> dict:
    """
    创建统一格式的错误响应
    
    Args:
        code: 错误码
        message: 错误消息（可选，如果未提供则使用默认消息）
        data: 附加数据（可选）
        request_id: 请求ID（可选，用于追踪请求）
        
    Returns:
        dict: 统一格式的错误响应
    """
    error_message = message if message is not None else get_error_message(code)
    
    response = {
        "code": code,
        "message": error_message,
        "success": code == ErrorCode.SUCCESS,
    }
    
    if data is not None:
        response["data"] = data
    
    if request_id is not None:
        response["request_id"] = request_id
    
    return response


def exception_to_error_response(exception: Exception, code: Optional[int] = None, request_id: Optional[str] = None) -> dict:
    """
    将异常对象转换为统一格式的错误响应
    
    Args:
        exception: 异常对象
        code: 错误码（可选，如果未提供则根据异常类型自动推断）
        request_id: 请求ID（可选，用于追踪请求）
        
    Returns:
        dict: 统一格式的错误响应
    """
    # 从自定义异常类中提取错误码
    if hasattr(exception, "code") and exception.code is not None:
        code = exception.code
    
    # 如果仍未找到错误码，则根据异常类型推断
    if code is None:
        from .exceptions import (
            WebSocketError, PluginError, ConfigError, NeoPermissionError,
            CommandError, RedisError, BrowserManagerError, CodeExecutionError
        )

        if isinstance(exception, WebSocketError):
            code = ErrorCode.WS_CONNECTION_FAILED
        elif isinstance(exception, PluginError):
            code = ErrorCode.PLUGIN_LOAD_FAILED
        elif isinstance(exception, ConfigError):
            code = ErrorCode.CONFIG_PARSE_ERROR
        elif isinstance(exception, NeoPermissionError):
            code = ErrorCode.PERMISSION_DENIED
        elif isinstance(exception, CommandError):
            code = ErrorCode.COMMAND_EXECUTE_ERROR
        elif isinstance(exception, RedisError):
            code = ErrorCode.REDIS_OPERATION_ERROR
        elif isinstance(exception, BrowserManagerError):
            code = ErrorCode.BROWSER_OPERATION_ERROR
        elif isinstance(exception, CodeExecutionError):
            code = ErrorCode.CODE_EXECUTE_ERROR
        else:
            code = ErrorCode.UNKNOWN_ERROR
    
    # 获取错误消息
    message = str(exception)
    
    # 如果异常有原始错误，也包含在响应中
    data = None
    if hasattr(exception, "original_error") and exception.original_error is not None:
        data = {"original_error": str(exception.original_error)}
    
    return create_error_response(code, message, data, request_id)


# 将错误码导出以便其他模块使用
ErrorCodes = ErrorCode

__all__ = [
    "ErrorCode",
    "ErrorCodes",
    "get_error_message",
    "create_error_response",
    "exception_to_error_response"
]