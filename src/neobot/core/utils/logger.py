"""
日志模块

该模块负责初始化和配置 loguru 日志记录器，为整个应用程序提供统一的日志记录接口。
"""
import os
import sys
from pathlib import Path
from loguru import logger

# 导入全局配置
try:
    from ..config_loader import global_config
    USE_CONFIG = True
except ImportError:
    USE_CONFIG = False

# 默认日志保留天数（配置文件未指定时使用）
DEFAULT_RETENTION_DAYS = 7


def resolve_retention_days(value, default: int = DEFAULT_RETENTION_DAYS) -> int:
    """保留天数只认正整数。缺省、写错或小于 1 都回到默认，避免被写成 1 天。"""
    try:
        days = int(value)
    except (TypeError, ValueError):
        return default
    if days < 1:
        return default
    return days
# 环境变量覆盖项，与 config_loader 中 LOG_LEVEL 等保持同名
_LOGGING_ENV_KEYS = (
    ("level", "LOG_LEVEL"),
    ("file_level", "LOG_FILE_LEVEL"),
    ("console_level", "LOG_CONSOLE_LEVEL"),
    ("retention_days", "LOG_RETENTION_DAYS"),
)


def _read_logging_config_from_file() -> dict:
    """
    在 config_loader 尚未初始化完成时，直接读取 config.toml 的 [logging] 配置。

    背景：main.py 第一行就要导入本模块，而本模块又需要读取配置级别，此时
    `from ..config_loader import global_config` 会因为循环导入拿到未完成的模块，
    走到 USE_CONFIG=False 分支。原来的实现直接硬编码 DEBUG/DEBUG/INFO，导致
    config.toml 里的 [logging] 完全失效（日志文件按 DEBUG 级别无限膨胀）。

    这里不依赖任何 neobot 模块，直接解析 TOML，并沿用与 config_loader 一致的环境
    变量覆盖优先级，保证配置在任何导入顺序下都生效。
    """
    try:
        import tomllib
    except ModuleNotFoundError:  # Python < 3.11
        return {}

    config_path = Path(os.environ.get("NEOBOT_CONFIG_FILE", "config.toml"))
    try:
        with open(config_path, "rb") as file:
            raw_config = tomllib.load(file)
    except (OSError, ValueError):
        return {}

    logging_config = dict(raw_config.get("logging") or {})
    for key, env_name in _LOGGING_ENV_KEYS:
        env_value = os.environ.get(env_name)
        if env_value:
            logging_config[key] = env_value
    return logging_config

# 定义日志格式，添加进程ID和线程ID作为上下文信息
LOG_FORMAT = (
    "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
    "<level>{level: <8}</level> | "
    "<magenta>PID {process} TID {thread}</magenta> | "
    "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - "
    "<level>{message}</level>"
)

# 开发环境日志格式（更详细）
DEBUG_LOG_FORMAT = (
    "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
    "<level>{level: <8}</level> | "
    "<magenta>PID {process} TID {thread}</magenta> | "
    "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> | "
    "<yellow>Module: {module}</yellow> | "
    "<level>{message}</level>"
)

# 移除 loguru 默认的处理器
logger.remove()

# 获取日志级别配置
if USE_CONFIG:
    LOG_LEVEL = global_config.logging.level
    FILE_LEVEL = global_config.logging.file_level
    CONSOLE_LEVEL = global_config.logging.console_level
    RETENTION_DAYS = resolve_retention_days(getattr(global_config.logging, "retention_days", None))
else:
    _fallback_logging = _read_logging_config_from_file()
    LOG_LEVEL = _fallback_logging.get("level", "DEBUG")
    FILE_LEVEL = _fallback_logging.get("file_level", LOG_LEVEL)
    CONSOLE_LEVEL = _fallback_logging.get("console_level", "INFO")
    RETENTION_DAYS = resolve_retention_days(_fallback_logging.get("retention_days"))

# 添加控制台输出处理器
logger.add(
    sys.stderr,
    level=CONSOLE_LEVEL,
    format=LOG_FORMAT,
    colorize=True,
    enqueue=True  # 异步写入
)

# 定义日志文件路径
log_dir = Path("logs")
log_dir.mkdir(exist_ok=True)
log_file_path = log_dir / "{time:YYYY-MM-DD}.log"

# 文件日志只有这一处注册。配置加载完成后会按校验过的 retention_days 重挂一次。
_file_sink_id = None


def apply_retention_days(days) -> int:
    """按天数重挂文件日志。返回实际采用的天数。"""
    global _file_sink_id
    kept = resolve_retention_days(days)
    if _file_sink_id is not None:
        try:
            logger.remove(_file_sink_id)
        except ValueError:
            pass
        _file_sink_id = None
    _file_sink_id = logger.add(
        log_file_path,
        level=FILE_LEVEL,
        format=DEBUG_LOG_FORMAT,
        colorize=False,
        rotation="00:00",  # 每天午夜创建新文件
        retention=f"{kept} days",
        encoding="utf-8",
        enqueue=True,  # 异步写入
        backtrace=True,  # 记录完整的异常堆栈
        diagnose=False,  # 不启用异常变量诊断（diagnose=True 会捕获局部变量快照，
                         # 含图片字节/base64 时造成瞬时内存峰值）
    )
    return kept


apply_retention_days(RETENTION_DAYS)

# 为自定义异常添加专门的日志记录方法
def log_exception(exc, module_name="unknown", level="error"):
    """
    记录自定义异常的详细信息
    
    Args:
        exc: 异常对象
        module_name: 模块名称（可选）
        level: 日志级别（可选，默认为 "error"）
    """
    log_func = getattr(logger, level)
    log_func(f"模块 {module_name} 发生异常: {exc}")
    
    # 如果异常对象有原始异常，也记录原始异常信息
    if hasattr(exc, "original_error") and exc.original_error:
        log_func(f"原始异常: {exc.original_error}")
    
    # 如果是配置错误，记录配置相关信息
    if hasattr(exc, "section") and hasattr(exc, "key"):
        log_func(f"配置信息: 部分={exc.section}, 键={exc.key}")
    
    # 如果是插件错误，记录插件名称
    if hasattr(exc, "plugin_name"):
        log_func(f"插件名称: {exc.plugin_name}")
    
    # 如果是命令错误，记录命令名称
    if hasattr(exc, "command"):
        log_func(f"命令名称: {exc.command}")
    
    # 如果是权限错误，记录用户ID和操作
    if hasattr(exc, "user_id") and hasattr(exc, "operation"):
        log_func(f"权限信息: 用户ID={exc.user_id}, 操作={exc.operation}")

# 为不同模块提供日志工具
class ModuleLogger:
    """
    模块专用日志记录器
    
    Args:
        module_name: 模块名称
    """
    def __init__(self, module_name):
        self.module_name = module_name
        
    def debug(self, message):
        logger.debug(f"[{self.module_name}] {message}")
    
    def info(self, message):
        logger.info(f"[{self.module_name}] {message}")
    
    def success(self, message):
        logger.success(f"[{self.module_name}] {message}")
    
    def warning(self, message):
        logger.warning(f"[{self.module_name}] {message}")
    
    def error(self, message):
        logger.error(f"[{self.module_name}] {message}")
    
    def exception(self, message, exc_info=True):
        logger.exception(f"[{self.module_name}] {message}", exc_info=exc_info)
    
    def log_custom_exception(self, exc, level="error"):
        """
        记录自定义异常
        
        Args:
            exc: 异常对象
            level: 日志级别
        """
        log_exception(exc, self.module_name, level)

# 导出配置好的 logger 和工具函数
__all__ = ["logger", "log_exception", "ModuleLogger", "resolve_retention_days", "apply_retention_days", "DEFAULT_RETENTION_DAYS"]
