# -*- coding: utf-8 -*-
"""
管理员专用的广播插件
功能：
- 仅限管理员在私聊中调用。
- 通过回复一条消息并发送指令，将该消息转发给机器人所在的所有群聊。
- 支持跨机器人广播：当任意机器人接收到广播消息时，会通过 Redis 发布消息，
  所有其他机器人订阅后也会转发给它们各自的群聊。
- 使用通用消息格式，不使用合并转发（聊天记录）格式。
"""
import asyncio
import json
from typing import Any
from neobot.core.managers.command_manager import matcher
from neobot.models.events.message import MessageEvent
from neobot.core.permission import Permission
from neobot.core.utils.logger import logger
from neobot.core.managers.redis_manager import redis_manager

# --- 会话状态管理 ---
# 结构: {user_id: asyncio.TimerHandle}
broadcast_sessions: dict[int, asyncio.TimerHandle] = {}

# 广播消息订阅任务
_broadcast_subscription_task = None


def _find_running_subscription_tasks():
    """查找所有正在运行的广播订阅循环任务（兼容热重载后模块级变量丢失的情况）。"""
    tasks = []
    for task in asyncio.all_tasks():
        try:
            coro = task.get_coro()
        except Exception:
            continue
        if coro is not None and coro.__name__ == "broadcast_subscription_loop" and not task.done():
            tasks.append(task)
    return tasks

def cleanup_session(user_id: int):
    """
    清理超时的广播会话。
    """
    if user_id in broadcast_sessions:
        del broadcast_sessions[user_id]
        logger.info(f"[Broadcast] 会话 {user_id} 已超时，自动取消。")


async def broadcast_message_to_groups(bot, message, source_robot_id: str = "unknown"):
    """
    将消息广播到所有群聊
    
    Args:
        bot: 机器人实例
        message: 要发送的消息
        source_robot_id: 消息来源机器人ID（用于日志）
    """
    try:
        group_list = await bot.get_group_list()
        if not group_list:
            logger.warning(f"[Broadcast] 机器人 {source_robot_id} 目前没有加入任何群聊")
            return
        
        success_count, failed_count = 0, 0
        total_groups = len(group_list)
        
        for group in group_list:
            try:
                await bot.send_group_msg(group.group_id, message)
                success_count += 1
            except Exception as e:
                failed_count += 1
                logger.error(f"[Broadcast] 机器人 {source_robot_id} 发送至群聊 {group.group_id} 失败: {e}")
        
        logger.success(f"[Broadcast] 机器人 {source_robot_id} 广播完成: {total_groups} 个群聊, 成功 {success_count}, 失败 {failed_count}")
        
    except Exception as e:
        logger.error(f"[Broadcast] 机器人 {source_robot_id} 获取群聊列表失败: {e}")


async def start_broadcast_subscription():
    """
    启动 Redis 广播消息订阅
    """
    global _broadcast_subscription_task

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

    _broadcast_subscription_task = asyncio.create_task(broadcast_subscription_loop())
    logger.success("[Broadcast] Redis 广播订阅已启动")


async def stop_broadcast_subscription():
    """
    停止 Redis 广播消息订阅
    """
    global _broadcast_subscription_task

    tasks = list(_find_running_subscription_tasks())
    if _broadcast_subscription_task is not None and _broadcast_subscription_task not in tasks:
        tasks.append(_broadcast_subscription_task)
    for task in tasks:
        task.cancel()
    for task in tasks:
        try:
            await task
        except asyncio.CancelledError:
            pass
        except Exception:
            pass
    _broadcast_subscription_task = None
    logger.info("[Broadcast] Redis 广播订阅已停止")


def _serialize_message(message) -> Any:
    """
    将消息转换为可 JSON 序列化的结构（MessageSegment -> dict），供 Redis 发布/签名使用。

    :param message: 原始消息（MessageSegment / 列表 / 其他）
    :return: 可 JSON 序列化的结构
    """
    from neobot.models.message import MessageSegment
    if isinstance(message, MessageSegment):
        return {"type": message.type, "data": message.data}
    if isinstance(message, list):
        return [_serialize_message(m) for m in message]
    return message


async def broadcast_subscription_loop():
    """
    Redis 广播消息订阅循环
    """
    if redis_manager.redis is None:
        logger.warning("[Broadcast] Redis 未初始化，无法启动广播订阅")
        return
    
    try:
        # 使用 async with 自动管理 pubsub 连接：任务取消/异常退出时连接归还连接池，避免连接池泄漏
        async with redis_manager.redis.pubsub() as pubsub:
            await pubsub.subscribe("neobot_broadcast")

            logger.success("[Broadcast] 已订阅 Redis 广播频道")

            async for message in pubsub.listen():
                if message["type"] == "message":
                    try:
                        data = json.loads(message["data"])
                        # 校验 HMAC 签名，防止任意可访问 Redis 的进程伪造广播
                        if isinstance(data, dict):
                            signature = data.pop("_sig", "")
                        else:
                            signature = ""
                        if not redis_manager.verify_pubsub(data, signature):
                            logger.warning("[Broadcast] 广播消息签名校验失败，丢弃伪造消息")
                            continue
                        robot_id = data.get("robot_id", "unknown")
                        message_data = data.get("message")

                        logger.info(f"[Broadcast] 收到跨机器人广播消息: 来源 {robot_id}")

                        # 获取所有活跃的 Bot 实例
                        from neobot.core.managers.bot_manager import bot_manager
                        all_bots = bot_manager.get_all_bots()

                        if not all_bots:
                            logger.warning("[Broadcast] 没有活跃的 Bot 实例，无法转发广播消息")
                            continue

                        # 遍历所有 Bot 进行广播
                        for bot in all_bots:
                            # 避免重复广播：如果消息来源就是当前 Bot，则跳过
                            if str(bot.self_id) == str(robot_id):
                                continue

                            await broadcast_message_to_groups(bot, message_data, robot_id)

                    except json.JSONDecodeError as e:
                        logger.error(f"[Broadcast] 解析广播消息失败: {e}")
                    except Exception as e:
                        logger.error(f"[Broadcast] 处理广播消息失败: {e}")

    except asyncio.CancelledError:
        raise  # 任务被取消：async with 会负责关闭 pubsub，重新抛出让调用方感知
    except Exception as e:
        logger.error(f"[Broadcast] 广播订阅循环异常: {e}")


@matcher.platform_command(["qq", "discord"], "broadcast", "广播", permission=Permission.ADMIN)
async def broadcast_start(event: MessageEvent):
    """
    广播指令的入口，启动一个等待用户消息的会话。
    """
    # 1. 仅限私聊
    if getattr(event, "message_type", "") != "private":
        return

    user_id = event.user_id
    
    # 如果上一个会话的超时任务还在，先取消它
    if user_id in broadcast_sessions:
        broadcast_sessions[user_id].cancel()

    await event.reply("已进入广播模式，请在 60 秒内发送您想要广播的消息内容。")
    
    # 设置 60 秒超时
    loop = asyncio.get_running_loop()
    timeout_handler = loop.call_later(
        60, 
        cleanup_session, 
        user_id
    )
    broadcast_sessions[user_id] = timeout_handler
    
    # 确保广播订阅已启动
    await start_broadcast_subscription()

@matcher.platform_message(["qq", "discord"], block=False)
async def handle_broadcast_content(event: MessageEvent):
    """
    通用消息处理器，用于捕获广播模式下的消息输入。
    将捕获到的消息直接发送给机器人所在的所有群聊，并通过 Redis 发布给其他机器人。
    """
    # 仅处理私聊消息，且用户在广播会话中
    if getattr(event, "message_type", "") != "private" or event.user_id not in broadcast_sessions:
        return

    user_id = event.user_id
    
    # 成功捕获到消息，取消超时任务并清理会话
    broadcast_sessions[user_id].cancel()
    del broadcast_sessions[user_id]

    message_to_broadcast = event.message
    if not message_to_broadcast:
        await event.reply("捕获到的消息为空，已取消广播。")
        return True

    # 获取当前机器人ID
    robot_id = "unknown"
    if event.bot and hasattr(event.bot, 'self_id'):
        robot_id = str(event.bot.self_id)
    
    # --- 执行本地广播 ---
    # 1. 先让接收到指令的这个 Bot 进行广播
    await broadcast_message_to_groups(event.bot, message_to_broadcast, robot_id)
    
    # 2. 获取其他所有 Bot 并进行广播（针对同一进程内的其他 Bot）
    from neobot.core.managers.bot_manager import bot_manager
    all_bots = bot_manager.get_all_bots()
    
    for bot in all_bots:
        # 跳过已经广播过的 Bot (即当前接收指令的 Bot)
        if str(bot.self_id) == robot_id:
            continue
        await broadcast_message_to_groups(bot, message_to_broadcast, robot_id)
    
    # --- 通过 Redis 发布消息给其他进程的机器人 ---
    try:
        if redis_manager.redis:
            broadcast_data = {
                "robot_id": robot_id,
                "message": _serialize_message(message_to_broadcast)
            }
            # 附加 HMAC 签名，防止伪造广播消息
            broadcast_data["_sig"] = redis_manager.sign_pubsub(broadcast_data)
            await redis_manager.redis.publish("neobot_broadcast", json.dumps(broadcast_data))
            logger.success(f"[Broadcast] 已通过 Redis 发布广播消息: 来源 {robot_id}")
    except Exception as e:
        logger.error(f"[Broadcast] 发布 Redis 消息失败: {e}")
    
    await event.reply("广播已完成！")
    
    return True # 消费事件，防止其他处理器响应
