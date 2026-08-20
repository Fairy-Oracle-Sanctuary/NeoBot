"""
Echo 与交互插件

提供 /echo 和 /赞我 指令。

本插件为插件 API 契约 (plugin-api-v1) 的示范实现:
- 只从 ``neobot.plugin_api`` 命名空间导入;
- 使用 ``define_plugin`` 声明清单(新式契约插件)。
"""
from neobot.plugin_api import (
    Bot,
    MessageEvent,
    ModuleLogger,
    command,
    define_plugin,
    platform_command,
)

logger = ModuleLogger("Echo")

plugin_manifest = define_plugin(
    name="echo",
    description="提供 echo 和 赞我 功能",
    usage="/echo [内容] - 复读内容\n/赞我 - 让机器人给你点赞",
    version="0.1.0",
    author="镀铬酸钾",
)

@platform_command(["qq", "discord"], "echo")
async def handle_echo(bot: Bot, event: MessageEvent, args: list[str]):
    """
    处理 echo 指令，原样回复用户输入的内容

    :param bot: Bot 实例
    :param event: 消息事件对象
    :param args: 指令参数列表
    """
    if not args:
        reply_msg = "请在指令后输入要回复的内容，例如：/echo 你好"
    else:
        reply_msg = " ".join(args)

    await event.reply(reply_msg)

@platform_command(
    ["qq", "discord"],
    "赞我",
    override_permission_check=True
)
async def handle_poke(bot: Bot, event: MessageEvent, permission_granted: bool):
    """
    处理 赞我 指令，发送点赞

    :param bot: Bot 实例
    :param event: 消息事件对象
    :param permission_granted: 权限检查结果
    """
    if not permission_granted:
        await event.reply("只有我的操作员才能让我点赞哦！(｡•ˇ‸ˇ•｡)")
        return

    try:
        # 尝试发送赞
        await bot.send_like(event.user_id, times=10)
        await event.reply("好感度+10！(〃'▽'〃)")
    except Exception as e:
        await event.reply(f"点赞失败了 >_<: {str(e)}")
