"""
thpic 插件

提供 /furry 指令，用于随机返回一个东方Project的图片。

"""
from neobot.plugin_api import platform_command, Bot, define_plugin
from neobot.models.events.message import MessageEvent
from neobot.models.message import MessageSegment

plugin_manifest = define_plugin(
    name="furry",
    description="处理 /furry 指令，发送furry出毛图片",
    usage="/furry - 发送一条furry图，1-10",
)

@platform_command(["qq", "discord"], "furry")
async def handle_echo(bot: Bot, event: MessageEvent, args: list[str]):
    """
    处理 furry 指令，发送一张随机的东方furry图片。

    :param bot: Bot 实例（未使用）。
    :param event: 消息事件对象。
    :param args: 指令参数列表（未使用）。
    """
    parts = args
    print(parts)
    if not parts:
        try:
            await event.reply(
                str(MessageSegment.image("https://api.furry.ist/furry-img/"))
            )
        except Exception as e:
            await event.reply(f"报错了。。。{e}")
    else:
        if parts[0].isdigit():
            nums = int(parts[0])
            if nums <= 0:
                await event.reply("请输入一个大于0的整数。")
                return
            elif nums > 10:
                await event.reply("请输入一个不大于10的整数。")
                return
            try:
                nodes = []
                for _ in range(nums):
                    nodes.append(
                        bot.build_forward_node(
                            user_id=event.self_id,
                            nickname="机器人",
                            message=MessageSegment.image(
                                "https://api.furry.ist/furry-img/"
                            ),
                        )
                    )
                await bot.send_forwarded_messages(event, nodes)
            except Exception as e:
                await event.reply(f"报错了。。。{e}")
        else:
            await event.reply(f"用法不正确。\n\n{plugin_manifest.usage}")
