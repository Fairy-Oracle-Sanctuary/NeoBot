"""随机兽图。不带标签时走 furry.ist；带标签时交给 e926。"""
from __future__ import annotations

import uuid

from neobot.plugin_api import Bot, MessageSegment, define_plugin, platform_command
from neobot.models.events.message import MessageEvent

plugin_manifest = define_plugin(
    name="furry",
    description="发送一张 SFW 兽图",
    usage=(
        "/furry - 随机一张图\n"
        "/furry 1-10 - 一次要多张，每张地址不同\n"
        "/furry <英文标签> - 按标签从 e926 找图（别名 /moe）\n"
        "/兽图 也可以按标签找"
    ),
    version="0.2.0",
)

_BASE = "https://api.furry.ist/furry-img/"


def furry_image_url(nonce: str) -> str:
    return f"{_BASE}?cb={nonce}"


def unique_furry_urls(count: int, nonces: list[str]) -> list[str]:
    urls: list[str] = []
    seen = set()
    for nonce in nonces:
        url = furry_image_url(str(nonce))
        if url in seen:
            continue
        seen.add(url)
        urls.append(url)
        if len(urls) >= count:
            break
    return urls


def _fresh_urls(count: int) -> list[str]:
    return unique_furry_urls(count, [uuid.uuid4().hex for _ in range(count)])


@platform_command(["qq", "discord"], "furry", "moe")
async def handle_furry(bot: Bot, event: MessageEvent, args: list[str]):
    if args and not (len(args) == 1 and args[0].isdigit()):
        from neobot.plugins.e926_gallery import reply_tagged_posts

        await reply_tagged_posts(event, args)
        return
    if not args:
        count = 1
    else:
        count = int(args[0])
        if count <= 0:
            await event.reply("请输入一个大于 0 的整数。")
            return
        if count > 10:
            await event.reply("一次最多 10 张。")
            return
    urls = _fresh_urls(count)
    try:
        if count == 1:
            await event.reply(MessageSegment.image(urls[0]))
            return
        nodes = [
            bot.build_forward_node(
                user_id=event.self_id,
                nickname="机器人",
                message=MessageSegment.image(url),
            )
            for url in urls
        ]
        await bot.send_forwarded_messages(event, nodes)
    except Exception as exc:
        await event.reply(f"图没发出去：{exc}")
