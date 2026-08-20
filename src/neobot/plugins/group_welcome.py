"""
入群提醒插件

在机器人加入群时发送提醒消息，包含作者信息和用途说明。
"""
from neobot.plugin_api import on_notice, Bot, define_plugin
from neobot.models.events.notice import GroupIncreaseNoticeEvent
from neobot.models.message import MessageSegment

plugin_manifest = define_plugin(
    name="group_welcome",
    description="机器人加入群时发送提醒消息",
    usage="自动触发，无需手动操作",
)

@on_notice(notice_type="group_increase")
async def handle_group_increase(bot: Bot, event: GroupIncreaseNoticeEvent):
    """
    处理群成员增加事件，当机器人加入群时发送提醒

    :param bot: Bot实例
    :param event: 群成员增加事件对象
    """
    if event.user_id != event.self_id:
        return

    # 群管理开关：目标群关闭了「主动推送」则跳过入群提醒
    from neobot.plugins.group_manage import is_feature_enabled
    group_id = getattr(event, "group_id", None)
    if group_id and not await is_feature_enabled(group_id, "push"):
        return

    welcome_message = (
        "我已加入本群！👋\n"
        "\n"
        "作者QQ号：2221577113\n"
        "作者：镀铬酸钾\n"
        "\n"
        "用途：/help"
        "by TOS team"
    )
    
    try:
        await bot.send(
            event,
            MessageSegment.text(welcome_message)
        )
    except Exception as e:
        print(f"[入群提醒] 发送提醒消息失败: {e}")
