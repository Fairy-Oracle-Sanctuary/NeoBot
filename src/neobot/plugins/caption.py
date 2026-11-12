"""给图片底部加一行字。发给 QQ 的成品是 JPEG，不是 PNG。"""
from __future__ import annotations

import asyncio
import base64
import io
from pathlib import Path

import aiohttp
from PIL import Image, ImageDraw, ImageFont

from neobot.plugin_api import (
    Bot,
    MessageEvent,
    MessageSegment,
    ModuleLogger,
    define_plugin,
    global_config,
    input_validator,
    platform_command,
    platform_message,
)

from .image_refs import image_urls_from_payload, image_urls_from_segments, reply_message_id

logger = ModuleLogger("Caption")

plugin_manifest = define_plugin(
    name="caption",
    description="给图片加上一行字",
    usage=(
        "/加字 <文字> - 给同一条消息里的图片、回复的图片加字\n"
        "没有图片时，会等你发下一张"
    ),
    version="0.1.0",
)

_FONT = Path(__file__).resolve().parent / "assets" / "fonts" / "wqy-microhei.ttc"
_waiting: dict[int, tuple[str, asyncio.Task]] = {}


class CaptionError(ValueError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _max_chars() -> int:
    try:
        return int(global_config.caption.max_chars)
    except Exception:
        return 36


def normalize_caption(text: str, max_chars: int = 36) -> str:
    cleaned = " ".join((text or "").split())
    if not cleaned:
        raise CaptionError("empty")
    if len(cleaned) > max_chars:
        raise CaptionError("long")
    return cleaned


def wrap_text(text: str, font: ImageFont.ImageFont, max_width: int) -> list[str]:
    lines: list[str] = []
    current = ""
    for char in text:
        trial = current + char
        if font.getlength(trial) <= max_width or not current:
            current = trial
        else:
            lines.append(current)
            current = char
    if current:
        lines.append(current)
    return lines or [text]


def layout_caption(text: str, image_width: int, font_path: str) -> tuple[int, list[str]]:
    width = max(int(image_width * 0.9), 40)
    chosen_size = 16
    chosen_lines = [text]
    for size in range(48, 15, -2):
        font = ImageFont.truetype(font_path, size=size, index=0)
        lines = wrap_text(text, font, width)
        if len(lines) <= 3:
            return size, lines
        chosen_size = size
        chosen_lines = lines
    return chosen_size, chosen_lines


def render_caption_image(image_bytes: bytes, text: str, font_path: str, max_chars: int = 36) -> bytes:
    """画上文字后返回 JPEG 字节。

    QQ / NapCat 发 JPEG 更稳，体积也比同尺寸 PNG 小。本仓库里其它要发给 QQ 的生成图同样用 JPEG。
    """
    caption = normalize_caption(text, max_chars=max_chars)
    image = Image.open(io.BytesIO(image_bytes))
    image = image.convert("RGBA")
    limit = 1600
    if max(image.size) > limit:
        image.thumbnail((limit, limit))
    size, lines = layout_caption(caption, image.width, font_path)
    font = ImageFont.truetype(font_path, size=size, index=0)
    line_height = int(size * 1.35)
    block = line_height * len(lines) + 24
    canvas = Image.new("RGBA", (image.width, image.height + block), (0, 0, 0, 0))
    canvas.paste(image, (0, 0))
    draw = ImageDraw.Draw(canvas)
    top = image.height + 8
    for index, line in enumerate(lines):
        text_width = font.getlength(line)
        x = max((image.width - text_width) / 2, 4)
        y = top + index * line_height
        draw.text((x, y), line, font=font, fill=(255, 255, 255, 255), stroke_width=2, stroke_fill=(0, 0, 0, 255))
    output = io.BytesIO()
    canvas.convert("RGB").save(output, format="JPEG", quality=90)
    return output.getvalue()


async def _download(url: str) -> bytes:
    if not input_validator.validate_http_url(url):
        raise CaptionError("url")
    timeout = aiohttp.ClientTimeout(total=15)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.get(url) as response:
            if response.status != 200:
                raise CaptionError("download")
            data = await response.read()
    if len(data) > 8 * 1024 * 1024:
        raise CaptionError("big")
    return data


async def _reply_image(event: MessageEvent, image_bytes: bytes) -> None:
    encoded = base64.b64encode(image_bytes).decode("ascii")
    await event.reply(MessageSegment.image(f"base64://{encoded}"))


async def _caption_and_reply(event: MessageEvent, url: str, text: str) -> None:
    try:
        raw = await _download(url)
        rendered = render_caption_image(raw, text, str(_FONT), max_chars=_max_chars())
    except CaptionError as exc:
        await event.reply(_caption_error_text(exc.code))
        return
    except Exception as exc:
        logger.error(f"[加字] 处理失败: {type(exc).__name__}: {exc}")
        await event.reply("这张图没加上字，请换一张再试。")
        return
    await _reply_image(event, rendered)


def _caption_error_text(code: str) -> str:
    if code == "empty":
        return "要加的字是空的。"
    if code == "long":
        return f"字有点多，请控制在 {_max_chars()} 个以内。"
    if code == "url":
        return "这张图的地址不能用。"
    if code == "big":
        return "图片太大了，换一张小一点的吧。"
    return "图片没能下载下来。"


async def _resolve_url(bot: Bot, event: MessageEvent) -> str:
    urls = image_urls_from_segments(getattr(event, "message", None))
    if urls:
        return urls[0]
    reply_id = reply_message_id(getattr(event, "message", None))
    if not reply_id or not hasattr(bot, "get_msg"):
        return ""
    try:
        payload = await bot.get_msg(int(reply_id))
    except Exception as exc:
        logger.warning(f"[加字] 读取回复消息失败: {type(exc).__name__}: {exc}")
        return ""
    found = image_urls_from_payload(payload)
    return found[0] if found else ""


async def _wait_next(event: MessageEvent, text: str, timeout: int = 30) -> None:
    user_id = int(getattr(event, "user_id", 0) or 0)
    await event.reply(f"请在 {timeout} 秒内发一张要加字的图片。")
    task = asyncio.current_task()
    _waiting[user_id] = (text, task)
    try:
        await asyncio.sleep(timeout)
        if user_id in _waiting and _waiting[user_id][1] is task:
            _waiting.pop(user_id, None)
            await event.reply("等太久了，请重新发 /加字。")
    except asyncio.CancelledError:
        return


@platform_message(["qq", "discord"], block=False)
async def handle_followup_image(bot: Bot, event: MessageEvent):
    user_id = int(getattr(event, "user_id", 0) or 0)
    pending = _waiting.get(user_id)
    if not pending:
        return
    urls = image_urls_from_segments(getattr(event, "message", None))
    if not urls:
        return
    text, task = _waiting.pop(user_id)
    if task is not None:
        task.cancel()
    await _caption_and_reply(event, urls[0], text)


@platform_command(["qq", "discord"], "加字")
async def handle_caption(bot: Bot, event: MessageEvent, args: list):
    if not _FONT.exists():
        await event.reply("加字用的字体不见了，请联系管理员。")
        return
    try:
        text = normalize_caption(" ".join(args), max_chars=_max_chars())
    except CaptionError as exc:
        if exc.code == "long":
            await event.reply(_caption_error_text("long"))
        else:
            await event.reply(f"用法：/加字 你好呀\n最多 {_max_chars()} 个字。")
        return
    url = await _resolve_url(bot, event)
    if url:
        await _caption_and_reply(event, url, text)
        return
    asyncio.create_task(_wait_next(event, text))
