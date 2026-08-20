# -*- coding: utf-8 -*-
"""
晚风人永久租赁人工审核插件（低调指令，无元信息注册）

功能：
  1. 后台轮询 mcc-service 的待审核永久租赁申请，出现新申请时主动私聊推送管理员。
  2. 「/审核通过 <qq>」指令（仅管理员 QQ 可用）→ 调 mcc-service 审核通过。

设计：
  - 审核权限在 mcc-service（admin token），neobot 只是推送 + 指令转发。
  - 无 __plugin_meta__，不出现在 /help。
"""
import asyncio
from typing import Dict, List
from neobot.plugin_api import mcc_manager, bot_manager, platform_command, logger
# 管理员 QQ（唯一有审核权限的人）
ADMIN_QQ = 2221577113

# 轮询间隔（秒）
POLL_INTERVAL = 30

# 后台任务状态
_tasks: List[asyncio.Task] = []
_running = False
# 已推送过的申请（避免重复推送）: {qq: 申请信息}
_seen: Dict[str, dict] = {}


async def _get_client():
    """获取 mcc-service 客户端（共享单例）。"""
    try:
        return await mcc_manager.get_client()
    except Exception as e:
        logger.error(f"[审核] 获取 mcc-service 客户端失败: {type(e).__name__}: {e}")
        return None


async def _push_admin(message: str) -> None:
    """给管理员发私聊（所有在线 bot 尝试推送）。"""
    bots = bot_manager.get_all_bots()
    if not bots:
        logger.warning("[审核] 无在线 bot，无法推送管理员")
        return
    for bot in bots:
        try:
            await bot.send_private_msg(ADMIN_QQ, message)
            return
        except Exception as e:
            logger.error(f"[审核] 推送管理员失败: {type(e).__name__}: {e}")


async def _poll_once() -> None:
    """轮询一次待审核申请，发现新的推送给管理员。"""
    client = await _get_client()
    if client is None:
        return
    try:
        data = await client.rental_pending()
    except Exception as e:
        logger.debug(f"[审核] 轮询待审列表失败: {type(e).__name__}: {e}")
        return
    if not data or not data.get("success"):
        return
    pending = data.get("pending") or []
    for entry in pending:
        qq = str(entry.get("qq", ""))
        if not qq or qq in _seen:
            continue
        _seen[qq] = entry
        purpose = (entry.get("purpose") or "").strip() or "未填写"
        game_name = (entry.get("game_name") or "").strip() or "未填写"
        from datetime import datetime
        req_at = entry.get("requested_at", 0)
        time_str = datetime.fromtimestamp(float(req_at)).strftime("%Y-%m-%d %H:%M") if req_at else "?"
        await _push_admin(
            f"🕐 新的永久租赁申请待审核\n"
            f"━━━━━━━━━━━━━━\n"
            f"申请者 QQ：{qq}\n"
            f"游戏名：{game_name}\n"
            f"用途：{purpose}\n"
            f"提交时间：{time_str}\n"
            f"━━━━━━━━━━━━━━\n"
            f"回复「/审核通过 {qq}」批准"
        )


async def _poll_loop() -> None:
    while True:
        try:
            await _poll_once()
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error(f"[审核] 轮询异常: {type(e).__name__}: {e}")
        await asyncio.sleep(POLL_INTERVAL)


async def start() -> bool:
    """启动后台审核轮询任务。"""
    global _tasks, _running
    if _running:
        return True
    _running = True
    task = asyncio.create_task(_poll_loop())
    _tasks.append(task)
    logger.info("[审核] 永久租赁审核轮询已启动")
    return True


async def stop() -> bool:
    """停止后台轮询任务。"""
    global _tasks, _running
    _running = False
    for task in _tasks:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
    _tasks = []
    logger.info("[审核] 永久租赁审核轮询已停止")
    return True


@platform_command(["qq"], "审核通过")
async def handle_review_approve(bot, event, args: list[str]):
    """
    /审核通过 <qq> —— 仅管理员可用，批准某 QQ 的永久租赁申请。
    """
    # 仅管理员
    if event.user_id != ADMIN_QQ:
        return  # 非管理员静默忽略

    qq = (args[0] if args else "").strip()
    if not qq or not qq.isdigit():
        await event.reply("用法：/审核通过 <qq号>")
        return

    client = await _get_client()
    if client is None:
        await event.reply("mcc-service 不可用，请稍后再试")
        return

    try:
        data = await client.rental_approve(qq)
    except Exception as e:
        logger.error(f"[审核] 审核通过调用失败: {type(e).__name__}: {e}")
        await event.reply(f"审核失败：{type(e).__name__}")
        return

    if data and data.get("success"):
        # 移除已推送记录，避免该 qq 后续再次被推送（若重新申请则重新推送）
        _seen.pop(qq, None)
        rental = data.get("rental") or {}
        bot_name = rental.get("bot") or "?"
        await event.reply(f"✅ 已审核通过 {qq} → 永久租赁假人「{bot_name}」")
    else:
        msg = (data or {}).get("message", "未知错误")
        await event.reply(f"❌ 审核失败：{msg}")
