"""
反馈插件

提供 /反馈 指令：仅 NeoBot 官群（1106927665）生效，收集用户反馈并私聊转发给管理员。

用法:
  /反馈 <内容> - 提交反馈（仅官群可用）
"""
from neobot.plugin_api import (
    Bot,
    MessageEvent,
    ModuleLogger,
    define_plugin,
    platform_command,
)

logger = ModuleLogger("反馈")

plugin_manifest = define_plugin(
    name="feedback",
    description="收集用户反馈并转发给管理员（仅官群生效）",
    usage="/反馈 <内容> - 提交反馈（仅官群可用）",
    version="0.1.0",
    author="镀铬酸钾",
)

# 仅此群生效
ALLOWED_GROUP_ID = 1106927665
# 反馈接收人（管理员）
ADMIN_QQ = 2221577113


@platform_command(["qq"], "反馈")
async def handle_feedback(bot: Bot, event: MessageEvent, args: list[str]):
    """
    处理 反馈 指令：仅官群生效，内容转发给管理员。

    :param bot: Bot 实例
    :param event: 消息事件对象
    :param args: 指令参数列表
    """
    # 仅允许在指定群使用
    group_id = getattr(event, "group_id", None)
    if group_id != ALLOWED_GROUP_ID:
        await event.reply("该指令仅在 NeoBot 官群可用，去官群使用吧～")
        return

    if not args:
        await event.reply(
            "请附上反馈内容，格式：/反馈 <内容>\n"
            "比如：/反馈 抖音解析失败了，链接是 xxx，刚才发的"
        )
        return

    content = " ".join(args).strip()
    if len(content) < 2:
        await event.reply("反馈内容太短啦，多写一点～")
        return

    # 发送者信息
    sender_id = str(getattr(event, "user_id", "") or "")
    sender_name = ""
    sender = getattr(event, "sender", None)
    if isinstance(sender, dict):
        sender_name = str(sender.get("card") or sender.get("nickname") or "")
    elif sender is not None:
        sender_name = str(getattr(sender, "card", "") or getattr(sender, "nickname", "") or "")

    logger.info(f"收到反馈（群 {group_id}）：{sender_id} {sender_name}：{content}")

    # 私聊转发给管理员（失败不影响用户侧回复）
    try:
        await bot.send_private_msg(
            ADMIN_QQ,
            f"📮 群反馈\n"
            f"发送者: {sender_name} ({sender_id})\n"
            f"群: {group_id}\n"
            f"内容: {content}",
        )
    except Exception as e:
        logger.error(f"转发反馈给管理员失败: {type(e).__name__}: {e}")

    await event.reply("收到！反馈已记录，管理员看到后会处理。感谢反馈～")
