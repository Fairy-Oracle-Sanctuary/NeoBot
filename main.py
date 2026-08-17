"""
NEO Bot 主程序入口

负责启动 WebSocket 连接，初始化插件系统，并提供热重载功能。
"""
import asyncio
import os
import sys
import time
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

# 将 src 目录添加到 sys.path（必须在导入 neobot 模块之前执行）
ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
SRC_DIR = os.path.join(ROOT_DIR, "src")
sys.path.insert(0, SRC_DIR)

# 初始化日志系统，必须在其他 neobot 模块导入之前执行
from neobot.core.utils.logger import logger

# 核心模块导入
from neobot.core.ws import WS
from neobot.core.managers import plugin_manager, matcher, permission_manager, reverse_ws_manager, thread_manager
from neobot.core.managers.redis_manager import redis_manager
from neobot.core.managers.browser_manager import browser_manager
from neobot.core.utils.executor import run_in_thread_pool, initialize_executor
from neobot.core.config_loader import global_config as config
from neobot.core.services.local_file_server import start_local_file_server, stop_local_file_server
from neobot.adapters.discord_adapter import DiscordAdapter


# 获取插件目录的绝对路径
PLUGIN_DIR = os.path.join(ROOT_DIR, "src", "neobot", "plugins")


async def reload_plugin_and_sync_help(module_name: str):
    """
    重载插件并同步帮助图片
    """
    await run_in_thread_pool(plugin_manager.reload_plugin, module_name)
    # 插件重载后，重新生成帮助图片
    await matcher.sync_help_pic()


class PluginReloadHandler(FileSystemEventHandler):
    """
    文件变更处理器，用于热重载插件

    继承自 watchdog.events.FileSystemEventHandler，
    监听 plugins 目录下的文件变化，并触发插件重载。
    """
    def __init__(self, loop: asyncio.AbstractEventLoop):
        """
        初始化处理器
        
        设置冷却时间，并保存主事件循环的引用。
        """
        self.loop = loop
        self.last_reload_time = 0
        self.cooldown = 1.0  # 冷却时间，防止短时间内多次重载

    def on_any_event(self, file_system_event):
        """
        处理所有文件事件

        :param file_system_event: watchdog 事件对象
        """
        if file_system_event.is_directory:
            return
        
        src_path = file_system_event.src_path
        
        # 只监控 py 文件
        if not src_path.endswith(".py"):
            return
            
        # 过滤掉一些临时文件和__init__.py文件
        if "__pycache__" in src_path or not src_path.startswith(PLUGIN_DIR) or os.path.basename(src_path) == "__init__.py":
            return

        # 简单的防抖动
        current_time = time.time()
        if current_time - self.last_reload_time < self.cooldown:
            return
        
        self.last_reload_time = current_time
        
        # 从文件路径解析出模块名
        # 例如: C:\path\to\project\src\neobot\plugins\bili_parser.py -> neobot.plugins.bili_parser
        relative_path = os.path.relpath(src_path, ROOT_DIR)
        module_name = os.path.splitext(relative_path.replace(os.sep, '.'))[0]

        logger.info(f"检测到文件变更: {src_path}")
        logger.info(f"准备重载插件: {module_name}...")
        
        try:
            # 使用线程安全的方式在主事件循环中运行异步的插件重载函数
            asyncio.run_coroutine_threadsafe(reload_plugin_and_sync_help(module_name), self.loop)
            logger.success(f"插件 {module_name} 重载任务已提交")
        except Exception as e:
            logger.exception(f"重载失败: {e}")


@logger.catch
async def main():
    """
    主函数
    
    1. 启动文件监控（热重载）
    2. 初始化 WebSocket 客户端
    3. 建立连接并保持运行
    """
    # 初始化向量数据库
    #from neobot.core.managers.vectordb_manager import vectordb_manager
    #vectordb_manager.initialize()

    # 首先加载所有插件
    plugin_manager.load_all_plugins()

    # 初始化 Redis 连接
    await redis_manager.initialize()

    # 启动晚风人永久租赁审核轮询（后台任务：30s 轮询待审申请 → 私聊推送管理员）
    try:
        from neobot.plugins.wanfeng_review import start as start_wanfeng_review
        await start_wanfeng_review()
    except Exception as e:
        logger.exception(f"启动晚风人审核轮询失败: {e}")

    # 启动晚风群成员同步（后台任务：10min 拉取群成员 → 覆盖 Redis 集合，供 is_wanfeng 判定）
    try:
        from neobot.plugins.wanfeng_members import start as start_wanfeng_members
        await start_wanfeng_members()
    except Exception as e:
        logger.exception(f"启动晚风群成员同步失败: {e}")

    # 启动跨平台消息订阅（Discord ↔ QQ，依赖 Redis）
    from neobot.plugins.discord_cross import start as start_cross_platform
    try:
        await start_cross_platform()
    except Exception as e:
        logger.exception(f"启动跨平台订阅失败: {e}")

    # 同步帮助图片
    await matcher.sync_help_pic()

    # 初始化权限管理器（包含了管理员管理功能）
    await permission_manager.initialize()

    # 初始化浏览器管理器 (使用页面池)
    await browser_manager.init_pool(size=3)
    if config.reverse_ws.enabled:
        logger.info("正在启动反向 WebSocket 服务端...")
        asyncio.create_task(reverse_ws_manager.start(
            host=config.reverse_ws.host,
            port=config.reverse_ws.port,
            token=config.reverse_ws.token
        ))
        logger.success(f"反向 WebSocket 服务端已启动: ws://{config.reverse_ws.host}:{config.reverse_ws.port}")

    # 启动本地文件服务器（如果启用）
    if config.local_file_server.enabled:
        logger.info("正在启动本地文件服务器...")
        asyncio.create_task(start_local_file_server())
        logger.success(f"本地文件服务器已启动: http://{config.local_file_server.host}:{config.local_file_server.port}")

    # 启动 Discord 客户端（如果启用）
    discord_client = None
    if config.discord.enabled and config.discord.token:
        logger.info("正在启动 Discord 客户端...")
        discord_client = DiscordAdapter(token=config.discord.token)
        asyncio.create_task(discord_client.start_client())
    elif config.discord.enabled:
        logger.warning("Discord 已启用，但未配置 Token，跳过启动。")

    # 启动文件监控
    # 监控 plugins 目录
    plugin_path = os.path.join(ROOT_DIR, "src", "neobot", "plugins")
    
    # 获取当前事件循环并传递给处理器
    loop = asyncio.get_running_loop()
    event_handler = PluginReloadHandler(loop)
    observer = Observer()
    
    if os.path.exists(plugin_path):
        observer.schedule(event_handler, plugin_path, recursive=True)
        observer.start()
        logger.info(f"已启动插件热重载监控: {plugin_path}")
    else:
        logger.warning(f"插件目录不存在 {plugin_path}")

    websocket_client = None
    try:
        # 初始化代码执行器
        code_executor = initialize_executor(config)
        
        # 初始化 WebSocket 客户端
        websocket_client = WS(code_executor=code_executor)

        # 启动代码执行器的后台 worker
        logger.debug("[Main] 检查是否需要启动代码执行 Worker...")
        if code_executor and code_executor.docker_client:
            logger.info("[Main] Docker 连接成功，正在启动代码执行 Worker...")
            asyncio.create_task(code_executor.worker())
        else:
            logger.warning("[Main] 未启动代码执行 Worker，因为 Docker 客户端未初始化或连接失败。")

        await websocket_client.connect()
    except asyncio.CancelledError:
        logger.info("主任务被取消，正在停止...")
    finally:
        logger.info("正在清理资源...")
        if observer.is_alive():
            observer.stop()
            observer.join()
        
        if websocket_client:
            await websocket_client.close()
            
        if discord_client:
            await discord_client.close()

        # 停止跨平台订阅
        from neobot.plugins.discord_cross import shutdown as stop_cross_platform
        try:
            await stop_cross_platform()
        except Exception as e:
            logger.exception(f"停止跨平台订阅失败: {e}")
            
        # 关闭反向 WebSocket 服务端
        if config.reverse_ws.enabled and reverse_ws_manager.server:
            await reverse_ws_manager.stop()
        
        # 关闭本地文件服务器
        if config.local_file_server.enabled:
            await stop_local_file_server()
        
        # 关闭线程管理器
        thread_manager.shutdown()
        
        # 关闭浏览器管理器
        await browser_manager.shutdown()

        # 关闭 mcc-service 共享 HTTP 客户端
        try:
            from neobot.adapters.mcc_adapter import mcc_manager
            await mcc_manager.close()
        except Exception as e:
            logger.debug(f"关闭 mcc_manager 失败: {type(e).__name__}: {e}")

        logger.success("资源清理完成，程序退出。")


if __name__ == "__main__":
    """
    程序主入口，添加全局异常捕获和友好提示
    """
    from neobot.core.utils.error_codes import exception_to_error_response
    from neobot.core.utils.logger import ModuleLogger
    
    # 创建主程序日志记录器
    main_logger = ModuleLogger("Main")
    
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        # 捕获 KeyboardInterrupt，不做任何操作，让 asyncio.run 正常结束
        pass
    except Exception as e:
        main_logger.exception("程序发生未处理的全局异常")
        
        # 生成统一的错误响应
        error_response = exception_to_error_response(e)
        
        # 打印友好的错误提示
        print("\n" + "=" * 60)
        print("程序发生错误，请检查以下信息：")
        print("=" * 60)
        print(f"错误代码: {error_response['code']}")
        print(f"错误信息: {error_response['message']}")
        print("=" * 60)
        print("详细错误信息已记录到日志文件中")
        print("请检查 logs 目录下的日志文件以获取更多调试信息")
        print("=" * 60)
        
        # 根据错误类型给出不同的建议
        if hasattr(e, "original_error") and e.original_error:
            print(f"\n原始错误: {e.original_error}")
            
        if "WebSocket" in str(type(e).__name__):
            print("\n建议检查:")
            print("1. WebSocket 服务是否正在运行")
            print("2. 配置文件中的 WebSocket 地址和令牌是否正确")
            print("3. 网络连接是否正常")
        elif "Config" in str(type(e).__name__):
            print("\n建议检查:")
            print("1. 配置文件 config.toml 是否存在")
            print("2. 配置文件格式是否正确")
            print("3. 所有必填配置项是否都已设置")
        elif "Plugin" in str(type(e).__name__):
            print("\n建议检查:")
            print("1. 插件目录是否存在")
            print("2. 插件文件是否有语法错误")
            print("3. 插件是否符合插件开发规范")
        
        exit(1)
