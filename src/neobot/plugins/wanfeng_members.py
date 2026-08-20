# -*- coding: utf-8 -*-
"""
晚风人群成员同步插件（后台任务，低调，无元信息注册）

每 10 分钟拉取晚风群（854312725）完整成员列表，全量覆盖写入 Redis Set
`neobot:wanfeng:members`，作为「晚风人」身份的权威数据源。
mcc-service 的 /api/rental/status 直接 SISMEMBER 该集合返回 is_wanfeng。

设计：
  - 数据源 = 群成员列表（比口令打标权威：退群自动失效、无需手动维护）
  - 拉取失败时保留旧集合（不清空），避免短暂网络故障导致全员失权
  - 无 __plugin_meta__，不出现在 /help
"""
import asyncio
from typing import List
from neobot.plugin_api import bot_manager, redis_manager, logger
# 晚风群群号（与 wanfeng_login.py 的 ALLOWED_GROUP_ID 一致）
WANFENG_GROUP_ID = 854312725
# 晚风标识 Redis key（Set 集合，存有标识的 QQ）
WANFENG_MEMBERS_KEY = "neobot:wanfeng:members"
# 同步间隔（秒）：成员变动不频繁，10 分钟足够
SYNC_INTERVAL = 600

_tasks: List[asyncio.Task] = []
_running = False


async def _sync_once() -> bool:
    """拉取群成员并全量覆盖写入 Redis Set。成功返回 True，失败返回 False。"""
    bots = bot_manager.get_all_bots()
    if not bots:
        logger.warning("[晚风成员] 无在线 bot，无法拉取群成员")
        return False
    for bot in bots:
        try:
            members = await bot.get_group_member_list(WANFENG_GROUP_ID)
        except Exception as e:
            logger.error(
                f"[晚风成员] bot {getattr(bot, 'self_id', '?')} 拉取群成员失败: {type(e).__name__}: {e}"
            )
            continue
        if not members:
            logger.warning("[晚风成员] 群成员列表为空，跳过本次同步")
            continue
        ids = {str(getattr(m, "user_id", "")) for m in members}
        ids.discard("")
        r = redis_manager.redis
        # 全量覆盖：先删后写，退群成员自动失效
        await r.delete(WANFENG_MEMBERS_KEY)
        if ids:
            await r.sadd(WANFENG_MEMBERS_KEY, *ids)
        logger.info(f"[晚风成员] 已同步晚风群成员 {len(ids)} 人 → {WANFENG_MEMBERS_KEY}")
        return True
    return False


async def _sync_loop() -> None:
    while True:
        try:
            await _sync_once()
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error(f"[晚风成员] 同步异常: {type(e).__name__}: {e}")
        await asyncio.sleep(SYNC_INTERVAL)


async def start() -> bool:
    """启动后台群成员同步任务。"""
    global _tasks, _running
    if _running:
        return True
    _running = True
    task = asyncio.create_task(_sync_loop())
    _tasks.append(task)
    logger.info("[晚风成员] 群成员同步任务已启动")
    return True


async def stop() -> bool:
    """停止后台同步任务。"""
    global _tasks, _running
    _running = False
    for task in _tasks:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
    _tasks = []
    logger.info("[晚风成员] 群成员同步任务已停止")
    return True
