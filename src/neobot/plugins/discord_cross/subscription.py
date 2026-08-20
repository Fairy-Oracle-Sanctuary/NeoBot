# -*- coding: utf-8 -*-
"""
跨平台消息互通插件订阅模块
"""
import json
import asyncio
from neobot.plugin_api import ModuleLogger, redis_manager
from .config import config
from .forwarder import forwarder

# 创建模块专用日志记录器
logger = ModuleLogger("CrossPlatformSubscription")

async def cross_platform_subscription_loop():
    """Redis 跨平台消息订阅循环"""
    try:
        redis = redis_manager.redis
    except ConnectionError as e:
        logger.warning(f"[CrossPlatform] Redis 未初始化，无法启动订阅: {e}")
        return
        
    try:
        # 使用 async with 自动管理 pubsub 连接：任务取消/异常退出时连接归还连接池，避免连接池泄漏
        async with redis.pubsub() as pubsub:
            await pubsub.subscribe(config.CROSS_PLATFORM_CHANNEL)

            logger.success("[CrossPlatform] 已订阅 Redis 跨平台频道")

            async for message in pubsub.listen():
                if message["type"] == "message":
                    try:
                        data = json.loads(message["data"])
                        # 校验 HMAC 签名，防止任意可访问 Redis 的进程伪造跨平台消息
                        if isinstance(data, dict):
                            signature = data.pop("_sig", "")
                        else:
                            signature = ""
                        if not redis_manager.verify_pubsub(data, signature):
                            logger.warning("[CrossPlatform] 跨平台消息签名校验失败，丢弃伪造消息")
                            continue
                        platform = data.get("platform", "")
                        message_data = data.get("data", {})

                        logger.info(f"[CrossPlatform] 收到跨平台消息: {platform}")

                        if platform == "discord":
                            await forwarder.forward_discord_to_qq(
                                discord_username=message_data.get("username", "Unknown"),
                                discord_discriminator=message_data.get("discriminator", ""),
                                content=message_data.get("content", ""),
                                channel_id=message_data.get("channel_id", 0),
                                attachments=message_data.get("attachments", [])
                            )
                        elif platform == "qq":
                            await forwarder.forward_qq_to_discord(
                                qq_nickname=message_data.get("nickname", "Unknown"),
                                qq_user_id=message_data.get("user_id", 0),
                                group_name=message_data.get("group_name", ""),
                                group_id=message_data.get("group_id", 0),
                                content=message_data.get("content", ""),
                                attachments=message_data.get("attachments", []),
                            )

                    except json.JSONDecodeError as e:
                        logger.error(f"[CrossPlatform] 解析消息失败: {e}")
                    except Exception as e:
                        logger.error(f"[CrossPlatform] 处理跨平台消息失败: {e}")

    except asyncio.CancelledError:
        raise  # 任务被取消：async with 会负责关闭 pubsub，重新抛出让调用方感知
    except Exception as e:
        logger.error(f"[CrossPlatform] 订阅循环异常: {e}")

_subscription_task = None

def _find_running_subscription_tasks():
    """查找所有正在运行的订阅循环任务（兼容热重载后模块级变量丢失的情况）。"""
    tasks = []
    for task in asyncio.all_tasks():
        try:
            coro = task.get_coro()
        except Exception:
            continue
        if coro is not None and coro.__name__ == "cross_platform_subscription_loop" and not task.done():
            tasks.append(task)
    return tasks

async def start_cross_platform_subscription():
    """启动跨平台消息订阅"""
    global _subscription_task

    if not config.ENABLE_CROSS_PLATFORM:
        return

    # 热重载后旧模块的订阅循环任务可能仍在运行：先取消旧的再启动，避免重复订阅
    for old_task in _find_running_subscription_tasks():
        old_task.cancel()
    for old_task in _find_running_subscription_tasks():
        try:
            await old_task
        except asyncio.CancelledError:
            pass
        except Exception:
            pass

    _subscription_task = asyncio.create_task(cross_platform_subscription_loop())
    logger.success("[CrossPlatform] 跨平台消息订阅已启动")

async def stop_cross_platform_subscription():
    """停止跨平台消息订阅"""
    global _subscription_task

    tasks = list(_find_running_subscription_tasks())
    if _subscription_task is not None and _subscription_task not in tasks:
        tasks.append(_subscription_task)
    for task in tasks:
        task.cancel()
    for task in tasks:
        try:
            await task
        except asyncio.CancelledError:
            pass
        except Exception:
            pass
    _subscription_task = None
    logger.info("[CrossPlatform] 跨平台消息订阅已停止")
