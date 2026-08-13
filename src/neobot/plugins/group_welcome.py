"""
入群提醒插件

在机器人加入群时发送提醒消息，包含作者信息和用途说明。
"""
from neobot.core.managers.command_manager import matcher
from neobot.core.bot import Bot
from neobot.models.events.notice import GroupIncreaseNoticeEvent
from neobot.models.message import MessageSegment

__plugin_meta__ = {
    "name": "入群提醒",
    "description": "机器人加入群时发送提醒消息",
    "usage": "自动触发，无需手动操作"
}

@matcher.on_notice(notice_type="group_increase")
async def handle_group_increase(bot: Bot, event: GroupIncreaseNoticeEvent):
    """
    处理群成员增加事件，当机器人加入群时发送提醒

    :param bot: Bot实例
    :param event: 群成员增加事件对象
    """
    if event.user_id != event.self_id:
        return
    
    welcome_message = (
        f"我已加入本群！👋\n"
        f"\n"
        f"作者QQ号：2221577113\n"
        f"作者：镀铬酸钾\n"
        f"\n"
        f"用途：/help"
        f"by TOS team"
    )
    
    try:
        await bot.send(
            event,
            MessageSegment.text(welcome_message)
        )
    except Exception as e:
        print(f"[入群提醒] 发送提醒消息失败: {e}")
