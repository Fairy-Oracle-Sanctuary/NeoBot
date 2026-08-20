"""
日志模块

该模块负责初始化和配置 loguru 日志记录器，为整个应用程序提供统一的日志记录接口。
"""
import sys
from pathlib import Path
from loguru import logger

# 导入全局配置
try:
    from ..config_loader import global_config
    USE_CONFIG = True
except ImportError:
    USE_CONFIG = False

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
else:
    LOG_LEVEL = "DEBUG"
    FILE_LEVEL = "DEBUG"
    CONSOLE_LEVEL = "INFO"

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

# 添加文件输出处理器
logger.add(
    log_file_path,
    level=FILE_LEVEL,
    format=DEBUG_LOG_FORMAT,
    colorize=False,
    rotation="00:00",  # 每天午夜创建新文件
    retention="7 days",  # 保留最近 7 天的日志
    encoding="utf-8",
    enqueue=True,  # 异步写入
    backtrace=True,  # 记录完整的异常堆栈
    diagnose=False   # 不启用异常变量诊断（diagnose=True 会捕获局部变量快照，
                     # 含图片字节/base64 时造成瞬时内存峰值）
)

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
__all__ = ["logger", "log_exception", "ModuleLogger"]
