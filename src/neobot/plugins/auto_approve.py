"""
自动同意请求插件

提供自动同意好友请求和群聊邀请的功能。
"""
from neobot.core.managers.command_manager import matcher
from neobot.core.bot import Bot
from neobot.models.events.request import FriendRequestEvent, GroupRequestEvent

__plugin_meta__ = {
    "name": "自动同意请求",
    "description": "自动同意好友请求和群聊邀请",
    "usage": "无需手动操作，自动处理请求事件",
}

@matcher.on_request(request_type="friend")
async def handle_friend_request(bot: Bot, event: FriendRequestEvent):
    """
    处理好友请求事件，自动同意好友申请

    :param bot: Bot实例
    :param event: 好友请求事件对象
    """
    try:
        # 自动同意好友请求
        await bot.call_api(
            "set_friend_add_request",
            params={
                "flag": event.flag,
                "approve": True
            }
        )
        print(f"[自动同意] 已同意用户 {event.user_id} 的好友请求")
    except Exception as e:
        print(f"[自动同意] 同意好友请求失败: {e}")

@matcher.on_request(request_type="group")
async def handle_group_request(bot: Bot, event: GroupRequestEvent):
    """
    处理群聊邀请事件，自动同意群聊邀请

    :param bot: Bot实例
    :param event: 群聊邀请事件对象
    """
    try:
        # 自动同意群聊邀请
        await bot.call_api(
            "set_group_add_request",
            params={
                "flag": event.flag,
                "sub_type": event.sub_type,
                "approve": True
            }
        )
        print(f"[自动同意] 已同意加入群聊 {event.group_id} (邀请人: {event.user_id})")
    except Exception as e:
        print(f"[自动同意] 同意群聊邀请失败: {e}")
