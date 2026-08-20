# -*- coding: utf-8 -*-
"""
希腊字母插件

提供 /希腊字母 指令：选定一个希腊字母后，等待用户发送一张图片，
使用 ffmpeg 将指定的希腊字母覆盖到图片上，并叠加失真效果后返回。

字母映射规则：取 "这是希腊字母" 目录下每个 PNG 文件名中的英文前缀
（如 Alpha1.png → Alpha），以其首字母小写作为键（a/b/d/e/g/i/k/t/z）。
当多个文件首字母相同时（如 Epsilon 与 Eta），按文件名排序先出现者胜出，
即 Epsilon 对应 'e'，Eta 被跳过。每次命令只能覆盖一个字母。
"""
import asyncio
import base64
import io
import os
import re
import shutil
import tempfile

import aiohttp
from PIL import Image
from neobot.plugin_api import Bot, platform_command, platform_message, input_validator, ModuleLogger, define_plugin
from neobot.models.events.message import MessageEvent
from neobot.models.message import MessageSegment

logger = ModuleLogger("GreekAlphabet")

plugin_manifest = define_plugin(
    name="greek_alphabet",
    description="在图片上覆盖希腊字母并用 ffmpeg 叠加失真效果",
    usage="/希腊字母 <字母> - 例如 /希腊字母 a（每次只能覆盖一个字母）",
)

# ── 资源目录 ────────────────────────────────────────────────────────
_PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
_LETTER_DIR = os.path.join(_PLUGIN_DIR, "这是希腊字母")

# ── 失真效果参数（可按需调整）──────────────────────────────────────
# noise: 胶片噪点；eq: 过饱和/高对比；unsharp: 锐化伪影；format=rgb24: 输出展平为 RGB
_DISTORTION_FILTER = "noise=alls=40,eq=contrast=1.4:saturation=1.7,unsharp=5:5:1.5,format=rgb24"
_JPEG_QUALITY = 5          # JPEG 质量（2=最佳，31=最差），偏低以增加压缩失真
_WAIT_TIMEOUT = 60         # 等待用户发送图片的超时时间（秒）


def _build_letter_map() -> dict:
    """
    扫描希腊字母图片目录，构建 "首字母小写 -> 图片路径" 的映射。

    :return: 字母到图片绝对路径的字典
    """
    mapping: dict = {}
    if not os.path.isdir(_LETTER_DIR):
        logger.warning(f"希腊字母图片目录不存在：{_LETTER_DIR}")
        return mapping

    for fname in sorted(os.listdir(_LETTER_DIR)):
        if not fname.lower().endswith(".png"):
            continue
        match = re.match(r"([A-Za-z]+)", fname)
        if not match:
            continue
        key = match.group(1)[0].lower()
        # 同一首字母按文件名排序，先出现者胜出（Epsilon 先于 Eta 占用 'e'）
        if key not in mapping:
            mapping[key] = os.path.join(_LETTER_DIR, fname)
    return mapping


# 启动时构建字母映射
LETTER_MAP = _build_letter_map()

# 等待图片的用户状态：user_id -> {"letter": 图片路径, "task": asyncio.Task}
_waiting_state: dict = {}


def _resolve_ffmpeg() -> str:
    """
    解析 ffmpeg 可执行文件路径。

    优先使用 PATH 中的 ffmpeg，否则回退到常见的系统安装位置，
    避免机器人运行环境的 PATH 未包含 /usr/bin 时无法找到。

    :return: ffmpeg 可执行文件绝对路径
    :raises RuntimeError: 找不到 ffmpeg 时抛出
    """
    for candidate in (shutil.which("ffmpeg"), "/usr/bin/ffmpeg", "/usr/local/bin/ffmpeg"):
        if candidate and os.path.isfile(candidate):
            return candidate
    raise RuntimeError("未找到 ffmpeg，请先安装 ffmpeg 后再使用本插件")


async def _download_image(url: str) -> bytes:
    """
    异步下载图片。

    :param url: 图片 URL
    :return: 图片字节数据
    """
    # SSRF 防护：仅允许 http/https 且拒绝内网/回环地址
    if not input_validator.validate_http_url(url):
        raise Exception("不安全的图片 URL")
    async with aiohttp.ClientSession() as session:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=30)) as resp:
            if resp.status != 200:
                raise Exception(f"下载图片失败：HTTP {resp.status}")
            return await resp.read()


def _build_filter_complex(base_w: int, base_h: int) -> str:
    """
    构造 ffmpeg filter_complex：只对底图（原图）叠加失真效果，
    希腊字母保持清晰，最后居中覆盖到失真后的底图上。

    :param base_w: 底图宽度
    :param base_h: 底图高度
    :return: filter_complex 字符串
    """
    target_h = max(2, int(base_h * 0.45))
    x_expr, y_expr = "(W-w)/2", "(H-h)/2"

    # 仅对底图失真；希腊字母只做缩放，不做失真
    return (
        f"[0:v]{_DISTORTION_FILTER}[db];"
        f"[1:v]scale=-2:{target_h},format=rgba[ov0];"
        f"[db][ov0]overlay={x_expr}:{y_expr}[out]"
    )


async def _overlay_letters(image_bytes: bytes, letter_paths: list) -> bytes:
    """
    用 ffmpeg 将希腊字母覆盖到图片上并叠加失真效果。

    :param image_bytes: 原始图片字节
    :param letter_paths: 希腊字母图片路径列表
    :return: 处理后的 JPEG 图片字节
    """
    # 读取底图尺寸（仅用于计算缩放与排版，不做实际像素处理）
    with Image.open(io.BytesIO(image_bytes)) as img:
        base_w, base_h = img.size

    ffmpeg_bin = _resolve_ffmpeg()

    with tempfile.TemporaryDirectory() as tmpdir:
        base_path = os.path.join(tmpdir, "base.img")
        out_path = os.path.join(tmpdir, "out.jpg")
        with open(base_path, "wb") as fp:
            fp.write(image_bytes)

        cmd = [ffmpeg_bin, "-y", "-i", base_path]
        for path in letter_paths:
            cmd += ["-i", path]

        filter_complex = _build_filter_complex(base_w, base_h)
        cmd += [
            "-filter_complex", filter_complex,
            "-map", "[out]",
            "-frames:v", "1",
            "-update", "1",
            "-q:v", str(_JPEG_QUALITY),
            out_path,
        ]

        logger.debug(f"ffmpeg 命令：{' '.join(cmd)}")
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            tail = stderr.decode(errors="replace")[-800:]
            raise RuntimeError(f"ffmpeg 处理失败（returncode={proc.returncode}）：\n{tail}")

        with open(out_path, "rb") as fp:
            return fp.read()


async def _wait_timeout(bot: Bot, event: MessageEvent, user_id):
    """
    等待图片超时任务：到点后清理等待状态并提示用户。

    :param bot: Bot 实例
    :param event: 消息事件对象（用于超时提示）
    :param user_id: 用户 ID
    """
    try:
        await asyncio.sleep(_WAIT_TIMEOUT)
    except asyncio.CancelledError:
        return
    if _waiting_state.pop(user_id, None) is not None:
        try:
            await event.reply("等待图片超时，请重新发送 /希腊字母 指令")
        except Exception:
            pass


@platform_message(["qq", "discord"], block=False)
async def _handle_image(bot: Bot, event: MessageEvent):
    """
    监听用户消息：若该用户正在等待且发送了图片，则处理图片。

    :param bot: Bot 实例
    :param event: 消息事件对象
    """
    user_id = event.user_id
    if user_id not in _waiting_state:
        return

    # 取第一张图片
    image_url = ""
    for seg in event.message:
        if seg.type == "image":
            image_url = seg.data.get("url") or seg.data.get("file") or ""
            if image_url:
                break
    if not image_url:
        return  # 非图片消息，保持等待状态

    state = _waiting_state.pop(user_id, None)
    if state is None:
        return
    task = state.get("task")
    if task:
        task.cancel()

    letter_path = state.get("letter")
    if not letter_path:
        await event.reply("内部状态异常，请重新发送 /希腊字母 指令")
        return
    try:
        await event.reply("收到图片，正在覆盖希腊字母并加上失真效果…")
        image_bytes = await _download_image(image_url)
        result = await _overlay_letters(image_bytes, [letter_path])
        b64 = base64.b64encode(result).decode("utf-8")
        await event.reply(MessageSegment.image(f"base64://{b64}"))
    except Exception as e:
        logger.exception("希腊字母图片处理失败")
        await event.reply(f"处理图片失败：{e}")


@platform_command(["qq", "discord"], "希腊字母")
async def _handle_command(bot: Bot, event: MessageEvent, args: list[str]):
    """
    处理 /希腊字母 指令：每次只取一个希腊字母，等待用户发送图片后覆盖。

    字母取希腊字母英文首字母（Alpha→a, Beta→b, Delta→d, Epsilon→e,
    Gamma→g, Iota→i, Kappa→k, Theta→t, Zeta→z）。
    如果用户一次输入多个字母，只取第一个有效字母，其余忽略并提示。

    :param bot: Bot 实例
    :param event: 消息事件对象
    :param args: 指令参数列表（字母）
    """
    if not LETTER_MAP:
        await event.reply(f"未找到希腊字母图片资源，请检查目录：{_LETTER_DIR}")
        return

    letters_str = "".join(args).lower().replace(" ", "").replace("　", "")
    available = "".join(sorted(LETTER_MAP.keys()))

    # 只取第一个有效字母
    selected_path = None
    selected_char = ""
    invalid = []
    for ch in letters_str:
        if ch in LETTER_MAP:
            if selected_path is None:
                selected_path = LETTER_MAP[ch]
                selected_char = ch
            # 已有首字母，其余忽略
        else:
            invalid.append(ch)

    if selected_path is None:
        await event.reply(
            "请指定要覆盖的希腊字母（取希腊字母英文首字母）。\n"
            f"可用字母：{available}\n"
            "用法：/希腊字母 <字母>，例如 /希腊字母 a\n"
            f"发送后请在 {_WAIT_TIMEOUT} 秒内发送一张图片。"
        )
        return

    # 有多个有效字母时提示只取第一个
    if letters_str and any(ch in LETTER_MAP and ch != selected_char for ch in letters_str):
        await event.reply(f'每次只能覆盖一个希腊字母，已选择 "{selected_char.upper()}"，其余忽略。')

    if invalid:
        logger.info(f"用户 {event.user_id} 输入了无效字母：{''.join(set(invalid))}（已忽略）")

    # 取消已有的等待任务
    prev = _waiting_state.pop(event.user_id, None)
    if prev and prev.get("task"):
        prev["task"].cancel()

    task = asyncio.create_task(_wait_timeout(bot, event, event.user_id))
    _waiting_state[event.user_id] = {"letter": selected_path, "task": task}
    await event.reply(
        f'已选定希腊字母 "{selected_char.upper()}"，请在 {_WAIT_TIMEOUT} 秒内发送一张图片，'
    )
