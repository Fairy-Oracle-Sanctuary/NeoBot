"""
Bot 状态查询插件

提供 /status 指令，以图片形式展示机器人当前的综合运行状态。
"""
import os
import psutil
import time
import asyncio
import socket
import platform
from datetime import datetime, timedelta
from functools import lru_cache
from typing import Optional

from neobot.core.bot import Bot
from neobot.core.managers.command_manager import matcher
from neobot.core.managers.image_manager import image_manager
from neobot.core.managers.redis_manager import redis_manager
from neobot.core.utils.executor import run_in_thread_pool
from neobot.core.utils.logger import logger
from neobot.models.events.message import MessageEvent, MessageSegment
from neobot.models.objects import Status, VersionInfo

__plugin_meta__ = {
    "name": "bot_status",
    "description": "以图片形式展示机器人当前的综合运行状态",
    "usage": "/status 或 /状态",
}

# 记录机器人启动时间
START_TIME = time.time()
# 获取当前进程
PROCESS = psutil.Process(os.getpid())
# 缓存bot昵称（12小时过期）
_nickname_cache: dict[str, tuple[str, float]] = {}

def _get_system_info():
    """
    同步函数：使用 psutil 获取系统信息，避免阻塞事件循环。
    优化：使用 interval=None 获取自上次调用以来的平均 CPU 使用率
    """
    try:
        # interval=None 会返回自上次调用以来的平均值，不会阻塞
        cpu_percent = psutil.cpu_percent(interval=None)
        mem_info = psutil.virtual_memory()
        bot_mem_mb = PROCESS.memory_info().rss / (1024 * 1024)
        
        # 磁盘信息
        disk_usage = psutil.disk_usage('/')
        
        # 网络信息
        net_io = psutil.net_io_counters()
        
        # 进程数
        process_count = len(psutil.pids())
        
        # CPU核心数
        cpu_count = psutil.cpu_count(logical=True)
        cpu_count_physical = psutil.cpu_count(logical=False)
        
        return {
            "cpu_percent": f"{cpu_percent:.1f}",
            "cpu_count": cpu_count,
            "cpu_count_physical": cpu_count_physical,
            "mem_percent": f"{mem_info.percent:.1f}",
            "mem_total": f"{mem_info.total / (1024**3):.1f}",
            "mem_used": f"{mem_info.used / (1024**3):.1f}",
            "mem_available": f"{mem_info.available / (1024**3):.1f}",
            "bot_mem_mb": f"{bot_mem_mb:.2f}",
            "disk_percent": f"{disk_usage.percent:.1f}",
            "disk_total": f"{disk_usage.total / (1024**3):.1f}",
            "disk_used": f"{disk_usage.used / (1024**3):.1f}",
            "disk_free": f"{disk_usage.free / (1024**3):.1f}",
            "net_sent": f"{net_io.bytes_sent / (1024**2):.1f}",
            "net_recv": f"{net_io.bytes_recv / (1024**2):.1f}",
            "process_count": process_count,
        }
    except Exception as e:
        logger.error(f"获取系统信息失败: {e}")
        return _create_error_system_info("N/A")

async def _get_bot_nickname(bot: Bot) -> str:
    """
    异步获取bot昵称，带缓存机制（12小时过期）
    """
    cache_key = f"bot_{bot.self_id}"
    now = time.time()
    
    # 检查缓存是否有效
    if cache_key in _nickname_cache:
        nickname, timestamp = _nickname_cache[cache_key]
        if now - timestamp < 43200:  # 12小时
            return nickname
    
    # 优先使用 get_stranger_info，更轻量
    try:
        stranger_info = await bot.get_stranger_info(user_id=bot.self_id)
        nickname = stranger_info.nickname
    except Exception:
        try:
            login_info = await bot.get_login_info()
            nickname = login_info.nickname
        except Exception:
            logger.warning("获取bot昵称失败")
            nickname = "获取失败"
    
    _nickname_cache[cache_key] = (nickname, now)
    return nickname

async def _get_bot_info(bot: Bot, start_time: float) -> dict:
    """
    收集bot信息（id、昵称、头像、启动时间等）
    """
    nickname = await _get_bot_nickname(bot)
    
    uptime_seconds = int(time.time() - start_time)
    uptime_delta = timedelta(seconds=uptime_seconds)
    days = uptime_delta.days
    hours, remainder = divmod(uptime_delta.seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    uptime_str = f"{days}天 {hours:02}:{minutes:02}:{seconds:02}"
    
    return {
        "user_id": bot.self_id,
        "nickname": nickname,
        "avatar_url": f"https://q1.qlogo.cn/g?b=qq&nk={bot.self_id}&s=640",
        "start_time": datetime.fromtimestamp(start_time).strftime("%Y-%m-%d %H:%M:%S"),
        "uptime": uptime_str,
    }

async def _get_version_info(bot: Bot) -> dict:
    """
    获取版本信息，失败时返回默认值
    """
    try:
        version_info = await bot.get_version_info()
        return {
            "app_name": version_info.app_name,
            "app_version": version_info.app_version,
            "protocol_version": version_info.protocol_version,
        }
    except Exception as e:
        logger.warning(f"获取版本信息失败: {e}")
        return {
            "app_name": "获取失败",
            "app_version": "N/A",
            "protocol_version": "N/A",
        }

async def _get_stats(redis_manager) -> tuple[dict, list]:
    """
    获取统计数据和命令排行
    """
    try:
        msgs_recv = await redis_manager.get("neobot:stats:messages_received") or 0
        msgs_sent = await redis_manager.get("neobot:stats:messages_sent") or 0
        command_stats_raw = await redis_manager.redis.hgetall("neobot:command_stats")
        
        total_commands = sum(int(v) for v in command_stats_raw.values()) if command_stats_raw else 0
        
        stats_data = {
            "messages_received": int(msgs_recv),
            "messages_sent": int(msgs_sent),
            "total_commands": total_commands,
        }

        command_stats_data = sorted(
            [{"name": k, "count": int(v)} for k, v in command_stats_raw.items()],
            key=lambda x: x["count"],
            reverse=True
        ) if command_stats_raw else []
        
        return stats_data, command_stats_data
    except Exception as e:
        logger.error(f"获取统计数据失败: {e}")
        return {
            "messages_received": 0,
            "messages_sent": 0,
            "total_commands": 0,
        }, []

async def _get_system_info_async(timeout: float = 3.0) -> dict:
    """
    异步获取系统信息，带超时控制
    """
    try:
        system_data = await asyncio.wait_for(
            run_in_thread_pool(_get_system_info),
            timeout=timeout
        )
        return system_data
    except asyncio.TimeoutError:
        logger.error("获取系统信息超时")
        return _create_error_system_info("Timeout")
    except Exception as e:
        logger.error(f"获取系统信息异常: {e}")
        return _create_error_system_info("Error")

async def _get_network_info_async() -> dict:
    """
    异步获取网络信息
    """
    try:
        return await asyncio.wait_for(
            run_in_thread_pool(_get_network_info),
            timeout=2.0
        )
    except Exception as e:
        logger.error(f"获取网络信息异常: {e}")
        return {
            "hostname": "获取失败",
            "local_ip": "获取失败",
            "public_ip": "获取失败",
        }

async def _get_os_info_async() -> dict:
    """
    异步获取操作系统信息
    """
    try:
        return await asyncio.wait_for(
            run_in_thread_pool(_get_os_info),
            timeout=2.0
        )
    except Exception as e:
        logger.error(f"获取操作系统信息异常: {e}")
        return {
            "os_name": "获取失败",
            "os_version": "获取失败",
            "os_arch": "获取失败",
            "python_version": "获取失败",
        }

def _create_error_system_info(error_msg: str = "N/A") -> dict:
    """
    创建错误状态的系统信息字典
    """
    return {
        "cpu_percent": error_msg,
        "cpu_count": error_msg,
        "cpu_count_physical": error_msg,
        "mem_percent": error_msg,
        "mem_total": error_msg,
        "mem_used": error_msg,
        "mem_available": error_msg,
        "bot_mem_mb": error_msg,
        "disk_percent": error_msg,
        "disk_total": error_msg,
        "disk_used": error_msg,
        "disk_free": error_msg,
        "net_sent": error_msg,
        "net_recv": error_msg,
        "process_count": error_msg,
    }

def _get_network_info():
    """
    获取网络信息（IP地址、主机名等）
    """
    try:
        hostname = socket.gethostname()
        
        # 获取本地IP
        try:
            local_ip = socket.gethostbyname(hostname)
        except Exception:
            local_ip = "获取失败"
        
        # 尝试获取公网IP（通过连接外部DNS）
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            public_ip = s.getsockname()[0]
            s.close()
        except Exception:
            public_ip = "无法获取"
        
        return {
            "hostname": hostname,
            "local_ip": local_ip,
            "public_ip": public_ip,
        }
    except Exception as e:
        logger.error(f"获取网络信息失败: {e}")
        return {
            "hostname": "获取失败",
            "local_ip": "获取失败",
            "public_ip": "获取失败",
        }

def _get_os_info():
    """
    获取操作系统信息
    """
    try:
        os_name = platform.system()
        os_version = platform.release()
        os_arch = platform.machine()
        python_version = platform.python_version()
        
        return {
            "os_name": os_name,
            "os_version": os_version,
            "os_arch": os_arch,
            "python_version": python_version,
        }
    except Exception as e:
        logger.error(f"获取操作系统信息失败: {e}")
        return {
            "os_name": "获取失败",
            "os_version": "获取失败",
            "os_arch": "获取失败",
            "python_version": "获取失败",
        }

@matcher.platform_command(["qq", "discord"], "status", "状态")
async def handle_status(bot: Bot, event: MessageEvent, args: list[str]):
    """
    处理 status 指令，生成并回复机器人状态图片。
    优化：并发获取各项数据，提升响应速度
    """
    logger.info(f"收到用户 {event.user_id} 的状态查询指令，开始生成状态图...")

    try:
        # 并发获取所有数据，提升性能
        bot_info, version_info, stats_result, system_data, network_info, os_info = await asyncio.gather(
            _get_bot_info(bot, START_TIME),
            _get_version_info(bot),
            _get_stats(redis_manager),
            _get_system_info_async(timeout=3.0),
            _get_network_info_async(),
            _get_os_info_async(),
            return_exceptions=False
        )
        
        # 处理 _get_stats 返回的元组
        if isinstance(stats_result, Exception):
            logger.error(f"获取统计数据失败: {stats_result}")
            stats_data, command_stats_data = {"messages_received": 0, "messages_sent": 0, "total_commands": 0}, []
        else:
            stats_data, command_stats_data = stats_result
        
        # 处理异常返回值
        if isinstance(system_data, Exception):
            logger.error(f"获取系统信息失败: {system_data}")
            system_data = _create_error_system_info("Error")
        
        if isinstance(network_info, Exception):
            logger.error(f"获取网络信息失败: {network_info}")
            network_info = {
                "hostname": "获取失败",
                "local_ip": "获取失败",
                "public_ip": "获取失败",
            }
        
        if isinstance(os_info, Exception):
            logger.error(f"获取操作系统信息失败: {os_info}")
            os_info = {
                "os_name": "获取失败",
                "os_version": "获取失败",
                "os_arch": "获取失败",
                "python_version": "获取失败",
            }

        # 脱敏：主机名/内网IP/公网IP 属基础设施信息，仅管理员可见
        from neobot.core.managers.permission_manager import permission_manager
        from neobot.core.permission import Permission
        if not await permission_manager.check_permission(event.user_id, Permission.ADMIN):
            network_info = {
                "hostname": "已隐藏",
                "local_ip": "已隐藏",
                "public_ip": "已隐藏",
            }

        # 推断机器人状态（能响应此命令说明在线且状态良好）
        status_info = Status(online=True, good=True)

        # 准备模板数据
        template_data = {
            "bot_info": bot_info,
            "status_info": status_info,
            "version_info": version_info,
            "stats": stats_data,
            "system": system_data,
            "network": network_info,
            "os": os_info,
            "command_stats": command_stats_data,
        }

        # 渲染图片
        try:
            base64_str = await image_manager.render_template_to_base64(
                template_name="status.html",
                data=template_data,
                output_name="status.png",
                image_type="png"
            )

            if base64_str:
                await event.reply(MessageSegment.image(base64_str))
            else:
                await event.reply("状态图片生成失败，请稍后重试或联系管理员。")
        except Exception as e:
            logger.error(f"渲染图片失败: {e}")
            await event.reply("状态图片渲染过程中发生错误。")

    except Exception as e:
        logger.exception(f"生成状态图时发生意外错误, 用户: {event.user_id}")
        await event.reply(f"获取状态信息时发生未知错误，请稍后再试或联系管理员。")
