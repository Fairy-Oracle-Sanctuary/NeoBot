"""
今日人品插件

提供 /jrcd 和 /bbcd 指令，用于娱乐。
"""

import random
from datetime import datetime
from neobot.plugin_api import Bot, platform_command, redis_manager, run_in_thread_pool, logger, define_plugin
from neobot.models.events.message import MessageEvent, MessageSegment
plugin_manifest = define_plugin(
    name="jrcd",
    description="来看看你的长度吧！",
    usage="/jrcd\n/bbcd [@某人]",
)

# jrcd
JRCDMSG_1 = [
    "今天的长度是%scm，可以让我一口吃掉吗罒ω罒",
    "今天的长度是%scm，啥啊？怎么这么小啊？(*°ｰ°)v",
    "今天的长度是%scm，什么嘛，原来是可爱的小豆丁呀(*°ｰ°)v",
]
JRCDMSG_2 = [
    "今天的长度是%scm，还行，也不是不能接受(๑´ㅂ´๑)",
    "今天的长度是%scm，小老弟不错啊，和哥哥一起玩会儿吗(〃∇〃)",
    "今天的长度是%scm，也许我们今晚能做很多很多事情呢(〃∇〃)",
]
JRCDMSG_3 = [
    "今天的长度是%scm，哦豁？听说你很勇哦？(✧◡✧)",
    "今天的长度是%scm，嘶哈嘶哈(((o(*°▽°*)o)))...",
    "今天的长度是%scm，我靠，让哥哥爽一-爽吧！(((o(*°▽°*)o)))...",
    "今天的长度是%scm，单是看到哥哥的长度就....(〃w〃)",
]

# bbcd long
BBCDMSG1 = ["还行,可以尝试一下(๑‾ ꇴ ‾๑)"]
BBCDMSG2 = ["不错的成绩,努力一下或许可以让他受孕哦..(〃w〃)"]
BBCDMSG3 = ["好猛,试试强制让他受孕吧！！！(((o(*°▽°*)o)))"]

# bbcd short
BBCDMSG4 = ["差的不多,富贵险中求一下(*°ｰ°)v?"]
BBCDMSG5 = ["还行,可以尝试一下(๑‾ ꇴ ‾๑)"]
BBCDMSG6 = ["快逃!!!!!!!!(o(*°▽°*)o)"]

# bbcd equal
BBCDMSG7 = ["试试刺刀看看谁能赢吧！"]


def get_jrcd(user_id: int) -> int:
    """
    根据用户ID和当前日期生成一个伪随机的“长度”值。

    :param user_id: 用户QQ号。
    :return: 返回一个1到30之间的整数。
    """
    current_time = (
        datetime.now().year * 100 + datetime.now().month * 100 + datetime.now().day
    )

    random.seed(hash(user_id + current_time))
    jrcd = random.randint(1, 30)
    random.seed()

    return jrcd


@platform_command(["qq", "discord"], "jrcd")
async def handle_jrcd(bot: Bot, event: MessageEvent, args: list[str]):
    if event.group_id == 831797331:
        return None
    """
    处理 jrcd 指令，回复用户的“今日长度”。

    :param bot: Bot 实例。
    :param event: 消息事件对象。
    :param args: 指令参数列表（未使用）。
    """
    user_id = event.user_id
    jrcd = await run_in_thread_pool(get_jrcd, user_id)
    
    msg_text = ""
    if jrcd <= 9:
        msg_text = random.choice(JRCDMSG_1) % jrcd
    elif jrcd <= 19:
        msg_text = random.choice(JRCDMSG_2) % jrcd
    else:
        msg_text = random.choice(JRCDMSG_3) % jrcd
        
    reply_segments = [MessageSegment.at(user_id), MessageSegment.from_text(msg_text)]
    await event.reply(reply_segments)

    # 使用 Lua 脚本原子化地增加总调用次数
    lua_script = "return redis.call('INCR', KEYS[1])"
    try:
        total_calls = await redis_manager.execute_lua_script(
            script=lua_script,
            keys=["neobot:jrcd:total_calls"],
            args=[]
        )
        if total_calls:
            logger.info(f"jrcd 总调用次数: {total_calls}")
    except Exception as e:
        logger.error(f"jrcd 插件增加调用次数失败: {e}")


@platform_command(["qq", "discord"], "jrcd_stats")
async def handle_jrcd_stats(bot: Bot, event: MessageEvent, args: list[str]):
    """
    处理 jrcd_stats 指令，查询 /jrcd 的总调用次数。

    :param bot: Bot 实例。
    :param event: 消息事件对象。
    :param args: 指令参数列表（未使用）。
    """
    total_calls = await redis_manager.get("neobot:jrcd:total_calls")
    if not total_calls:
        total_calls = 0
    
    reply_text = f"/jrcd 指令已被大家调用了 {total_calls} 次啦！"
    await event.reply(reply_text)


@platform_command(["qq", "discord"], "bbcd")
async def handle_bbcd(bot: Bot, event: MessageEvent, args: list[str]):
    if event.group_id == 831797331:
        return None
    """
    处理 bbcd 指令，比较两位用户的“长度”。

    :param bot: Bot 实例。
    :param event: 消息事件对象。
    :param args: 指令参数列表（未使用）。
    """
    message = event.message
    print(message)
    if len(message) < 2:
        return

    user_id1 = event.user_id
    try:
        user_id2 = int(message[1].data.get("qq", 0))
    except (ValueError, AttributeError, IndexError):
        return

    if user_id1 == user_id2:
        await event.reply("不能和自己比！")
        return

    jrcd1 = await run_in_thread_pool(get_jrcd, user_id1)
    jrcd2 = await run_in_thread_pool(get_jrcd, user_id2)

    jrcz = jrcd1 - jrcd2

    text_part = ""
    if jrcz == 0:
        text_part = f" 一样长。{random.choice(BBCDMSG7)}"
    elif jrcz > 0:
        text_part = f" 长{jrcz}cm。"
        if jrcz <= 9:
            text_part += random.choice(BBCDMSG1)
        elif jrcz <= 19:
            text_part += random.choice(BBCDMSG2)
        else:
            text_part += random.choice(BBCDMSG3)
    else:  # jrcz < 0
        text_part = f" 短{abs(jrcz)}cm。"
        if jrcz >= -9:
            text_part += random.choice(BBCDMSG4)
        elif jrcz >= -19:
            text_part += random.choice(BBCDMSG5)
        else:
            text_part += random.choice(BBCDMSG6)

    segments = [
        MessageSegment.at(user_id1),
        MessageSegment.from_text(" 你的长度比 "),
        MessageSegment.at(user_id2),
        MessageSegment.from_text(text_part),
    ]
            
    await event.reply(segments)
