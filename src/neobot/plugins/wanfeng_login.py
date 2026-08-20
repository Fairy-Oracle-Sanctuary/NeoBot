# -*- coding: utf-8 -*-
"""
晚风人登录插件（低调指令，无元信息注册，不出现在 /help 列表）

功能：在指定群内发送「/登录 我是晚风人」验证晚风身份，
      验证成功后给触发者 QQ 打上「晚风标识」（Redis Set: neobot:wanfeng:members）。

仅限群 854312725 触发。该标识为未来 mcc-service 独占功能预留。
"""
from neobot.plugin_api import platform_command, redis_manager, logger
# 晚风标识 Redis key（Set 集合，存有标识的 QQ）
WANFENG_MEMBERS_KEY = "neobot:wanfeng:members"

# 仅限此群触发
ALLOWED_GROUP_ID = 854312725

# 验证口令（严格匹配）
PASSPHRASE = "我是晚风人"


@platform_command(["qq"], "登录")
async def handle_wanfeng_login(bot, event, args: list[str]):
    """
    处理「/登录 我是晚风人」：验证口令 + 群限制，成功后打晚风标识。
    """
    # 1. 仅限指定群
    if event.group_id != ALLOWED_GROUP_ID:
        return  # 其他群/私聊静默忽略，不响应

    # 2. 校验口令
    text = " ".join(args).strip()
    if text != PASSPHRASE:
        await event.reply(f"口令不对哦，请输入：/登录 {PASSPHRASE}")
        return

    user_id = str(event.user_id)

    # 3. 打标（幂等：已打标则提示已认证）
    try:
        added = await redis_manager.redis.sadd(WANFENG_MEMBERS_KEY, user_id)
        if added:
            logger.info(f"[晚风登录] 群 {event.group_id} 用户 {user_id} 已认证晚风人")
            await event.reply("✅ 晚风人认证成功！")
        else:
            await event.reply("你已经是晚风人啦~")
    except Exception as e:
        logger.error(f"[晚风登录] 打标失败: {type(e).__name__}: {e}")
        await event.reply("内部服务异常，请稍后再试。")
