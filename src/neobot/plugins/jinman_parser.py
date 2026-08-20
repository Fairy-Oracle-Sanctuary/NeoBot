# -*- coding: utf-8 -*-
"""
禁漫天堂（JMComic）PDF 解析插件

功能：
- 管理员通过 `/jmc解析 开启|关闭|状态` 控制解析功能的开关（状态持久化到 Redis，默认关闭）
- 开启后 `/jmc <车牌号>` 手动生成 PDF；群聊/私聊中发送禁漫相册链接也会自动解析
- PDF 通过群文件上传到当前群聊（私聊则上传私聊文件）

数据源：自建 JMComic-Api 服务（https://github.com/FfmpegZZZ/JMComic-Api）
接口：
- GET {api_base}/album/<id>                    相册信息（标题等）
- GET {api_base}/get_pdf/<id>?pdf=true&passwd=false  直接返回 PDF 文件
"""
import asyncio
import re
import time
from typing import Dict, Optional, Tuple

import aiohttp
from neobot.plugin_api import platform_command, platform_message, redis_manager, Permission, get_local_file_server, ModuleLogger, global_config, define_plugin
from neobot.models.events.message import MessageEvent

logger = ModuleLogger("JinmanParser")

plugin_manifest = define_plugin(
    name="jinman_parser",
    description="禁漫天堂（JMComic）相册转 PDF（需管理员开启，自建 JMComic-Api 服务）",
    usage="/jmc解析 开启|关闭|状态 （管理员）\n"
        "/jmc <车牌号或链接> 生成 PDF\n"
        "开启后自动解析禁漫相册链接",
)

# 默认服务地址与超时，可通过 [jinman] 配置块覆盖
DEFAULT_API_BASE = "http://127.0.0.1:8699"
DEFAULT_TIMEOUT = 600

REDIS_KEY = "neobot:plugin:jinman_parser:enabled"

# 禁漫相册链接（常见镜像域名，路径 /album/<id> 或 /photo/<id>）
JM_ALBUM_URL_RE = re.compile(
    r"https?://(?:[\w-]+\.)*(?:18comic|jmcomic)[\w.-]*/(?:album|photo)/(\d+)",
    re.IGNORECASE,
)
# 车牌号：纯数字（或带 JM 前缀）
ALBUM_ID_RE = re.compile(r"^\s*(?:JM)?(\d{3,})\s*$", re.IGNORECASE)

# 开关状态（按会话作用域独立：群聊 group:<群号>，私聊 user:<QQ>）
# 内存缓存，首次查询时从 Redis 加载；Redis 无记录时默认关闭
_enabled_map: Dict[str, bool] = {}

# 开关内存缓存上限，防止长期运行无限增长
_MAX_ENABLED_SCOPES = 512

# 自动解析的消息去重（message_id -> 处理时间）
_processed_messages: Dict[int, float] = {}
_MAX_PROCESSED = 512

# 相同失败提示的冷却（目标, 文案）-> 上次发送时间
_error_reply_cooldown: Dict[Tuple[str, str], float] = {}
_ERROR_COOLDOWN_SECONDS = 120.0

# 共享 aiohttp 会话
_session: Optional[aiohttp.ClientSession] = None


# ── 配置 ──────────────────────────────────────────────────────

def _get_config() -> Tuple[str, int]:
    """
    读取 [jinman] 配置块（延迟 import，避免模块加载时解析全局配置）。

    Returns:
        (api_base, timeout)
    """
    try:
        cfg = global_config.jinman
        return (cfg.api_base or DEFAULT_API_BASE).rstrip("/"), cfg.timeout or DEFAULT_TIMEOUT
    except Exception as e:
        logger.debug(f"[JinmanParser] 读取配置失败，使用默认值: {type(e).__name__}: {e}")
        return DEFAULT_API_BASE, DEFAULT_TIMEOUT


# ── 开关状态 ─────────────────────────────────────────────────────

def _scope_key(event: MessageEvent) -> str:
    """
    计算开关的作用域：群聊按群号，私聊按对方QQ。
    """
    group_id = getattr(event, "group_id", None)
    if group_id:
        return f"group:{group_id}"
    user_id = getattr(event, "user_id", None)
    if user_id:
        return f"user:{user_id}"
    return "global"


async def _load_enabled(scope: str) -> bool:
    """从 Redis 加载指定作用域的开关状态（无记录或失败时默认关闭）。"""
    try:
        value = await redis_manager.get(f"{REDIS_KEY}:{scope}")
        enabled = value == "1"
    except Exception as e:
        # Redis 未初始化（例如 CLI 调试模式）时使用内存状态
        logger.debug(f"[JinmanParser] Redis 不可用，使用内存状态: {type(e).__name__}: {e}")
        enabled = False
    _enabled_map[scope] = enabled
    logger.debug(f"[JinmanParser] 加载开关状态 {scope}: {enabled}")
    return enabled


async def is_enabled_for(scope: str) -> bool:
    """获取指定作用域的解析开关状态（首次查询时从 Redis 加载，默认关闭）。"""
    if scope not in _enabled_map:
        await _load_enabled(scope)
    return _enabled_map.get(scope, False)


async def _set_enabled(scope: str, value: bool) -> bool:
    """设置指定作用域的开关状态并持久化到 Redis。"""
    _enabled_map[scope] = value
    # 限制内存缓存数量，防止长期运行无限增长
    if len(_enabled_map) > _MAX_ENABLED_SCOPES:
        for old_scope in list(_enabled_map)[: _MAX_ENABLED_SCOPES // 2]:
            del _enabled_map[old_scope]
    try:
        await redis_manager.set(f"{REDIS_KEY}:{scope}", "1" if value else "0")
        logger.info(f"[JinmanParser] 开关状态已持久化 {scope}: {value}")
        return True
    except Exception as e:
        logger.debug(f"[JinmanParser] Redis 持久化失败，仅内存生效: {type(e).__name__}: {e}")
        return False


# ── HTTP 请求 ────────────────────────────────────────────────────

async def _get_session() -> aiohttp.ClientSession:
    global _session
    if _session is None or _session.closed:
        _, timeout = _get_config()
        _session = aiohttp.ClientSession(
            # 走系统代理环境变量（生产已注入 http_proxy 指向 mihomo）
            trust_env=True,
            timeout=aiohttp.ClientTimeout(total=timeout),
        )
    return _session


async def fetch_album_info(album_id: str) -> Optional[dict]:
    """
    获取相册信息（标题等）。

    Returns:
        相册信息字典；失败返回 None。
    """
    api_base, _ = _get_config()
    url = f"{api_base}/album/{album_id}"
    try:
        session = await _get_session()
        async with session.get(url, timeout=15) as response:
            if response.status != 200:
                return None
            data = await response.json(content_type=None)
            if not data.get("success"):
                return None
            return data.get("data") or {}
    except Exception as e:
        logger.error(f"[JinmanParser] 获取相册信息失败: {type(e).__name__}: {e}")
        return None


async def fetch_pdf(album_id: str, title: str = "") -> Tuple[Optional[str], Optional[str]]:
    """
    从 JMComic-Api 下载 PDF 到本地文件服务器并注册。

    Args:
        album_id: 禁漫相册 ID（车牌号）
        title: 相册标题（用于生成文件名）

    Returns:
        (本地访问 URL, 文件名)；失败时返回 (None, 错误信息)
    """
    api_base, timeout = _get_config()
    server = get_local_file_server()
    if server is None or server.site is None:
        logger.error("[JinmanParser] 本地文件服务器未启用，无法中转 PDF")
        return None, "本地文件服务未启用"

    url = f"{api_base}/get_pdf/{album_id}?pdf=true&passwd=false&Titletype=2"
    try:
        session = await _get_session()
        async with session.get(url, timeout=timeout) as response:
            if response.status != 200:
                error_msg = ""
                try:
                    err = await response.json(content_type=None)
                    error_msg = (err.get("message") or "").strip()
                except Exception:
                    pass
                logger.error(f"[JinmanParser] PDF 获取失败 HTTP {response.status}: {error_msg}")
                return None, error_msg or f"服务返回 HTTP {response.status}"

            file_id = server._generate_file_id(f"jm://{album_id}")
            dest = server.download_dir / file_id
            with open(dest, "wb") as f:
                while True:
                    chunk = await response.content.read(8192)
                    if not chunk:
                        break
                    f.write(chunk)

            if dest.stat().st_size == 0:
                dest.unlink(missing_ok=True)
                return None, "生成的 PDF 为空"

            server.file_map[file_id] = dest
            local_url = f"{server.base_url}/download?id={file_id}"
            filename = _build_pdf_filename(album_id, title)
            logger.success(
                f"[JinmanParser] PDF 已保存: {dest} ({dest.stat().st_size} bytes)"
            )
            return local_url, filename

    except asyncio.TimeoutError:
        logger.error(f"[JinmanParser] PDF 生成超时（{timeout}s）")
        return None, "生成超时"
    except Exception as e:
        logger.error(f"[JinmanParser] PDF 下载异常: {type(e).__name__}: {e}")
        return None, None


# ── 文件名 ─────────────────────────────────────────────────────

def _sanitize_filename(name: str) -> str:
    """去除 Windows/QQ 文件名的非法字符并截断。"""
    name = re.sub(r'[\\/:*?"<>|\r\n]', "", name).strip()
    return name[:120] or "JM"


def _build_pdf_filename(album_id: str, title: Optional[str]) -> str:
    """生成上传到群文件的 PDF 文件名：[<id>] <标题>.pdf"""
    if title:
        return f"[{album_id}] {_sanitize_filename(title)}.pdf"
    return f"[{album_id}].pdf"


# ── 车牌号提取 ─────────────────────────────────────────────────

def extract_album_id(text: str) -> Optional[str]:
    """
    从文本中提取禁漫相册 ID（车牌号）。

    支持：
    - 纯数字：`123456`
    - JM 前缀：`JM123456`
    - 完整链接：`https://18comic.vip/album/123456` 等镜像域名

    Returns:
        相册 ID 字符串；无法识别返回 None。
    """
    if not text:
        return None
    m = JM_ALBUM_URL_RE.search(text)
    if m:
        return m.group(1)
    m = ALBUM_ID_RE.match(text.strip())
    if m:
        return m.group(1)
    return None


# ── 发送 ─────────────────────────────────────────────────────────

def _get_event_target(event: MessageEvent) -> str:
    return str(getattr(event, "group_id", None) or getattr(event, "user_id", None) or "unknown")


async def reply_with_error_cooldown(event: MessageEvent, text: str) -> bool:
    """同一目标在冷却时间内不重复发送完全相同的错误提示。"""
    key = (_get_event_target(event), text)
    now = time.monotonic()
    if now - _error_reply_cooldown.get(key, 0.0) < _ERROR_COOLDOWN_SECONDS:
        logger.debug(f"[JinmanParser] 相同失败提示在冷却期内，跳过重复回复: {text[:40]}")
        return False

    if len(_error_reply_cooldown) > 256:
        oldest = sorted(_error_reply_cooldown, key=_error_reply_cooldown.get)[:128]
        for old_key in oldest:
            del _error_reply_cooldown[old_key]

    _error_reply_cooldown[key] = now
    await event.reply(text)
    return True


async def upload_pdf(event: MessageEvent, local_url: str, filename: str) -> bool:
    """
    把 PDF 上传到目标群聊/私聊文件系统。

    file 传本地文件服务器的 URL（NapCat 会自行下载后上传），
    name 为展示文件名（[<id>] <标题>.pdf）。
    """
    group_id = getattr(event, "group_id", None)
    try:
        if group_id:
            await event.bot.call_api(
                "upload_group_file",
                {"group_id": group_id, "file": local_url, "name": filename},
            )
        else:
            await event.bot.call_api(
                "upload_private_file",
                {"user_id": event.user_id, "file": local_url, "name": filename},
            )
        return True
    except Exception as e:
        logger.error(f"[JinmanParser] 上传 PDF 失败: {type(e).__name__}: {e}")
        return False


async def process_jm(event: MessageEvent, album_id: str):
    """生成并发送 PDF。"""
    # 先给用户即时反馈（标题查询可能耗时数秒，PDF 生成更久）
    await event.reply(f"⏳ 正在生成 [JM{album_id}] 的 PDF，可能需要几分钟…")

    info = await fetch_album_info(album_id)
    title = ""
    if info:
        title = (info.get("title") or "").strip()

    local_url, filename = await fetch_pdf(album_id, title)
    if not local_url:
        error_msg = filename or "生成失败"
        await reply_with_error_cooldown(event, f"禁漫 PDF 生成失败：{error_msg}")
        return

    ok = await upload_pdf(event, local_url, filename)
    if ok:
        title_part = f"《{title}》" if title else ""
        await event.reply(f"✅ [JM{album_id}] {title_part} PDF 已发送到本群文件。")
    else:
        await reply_with_error_cooldown(event, "PDF 生成成功但上传失败，请稍后再试。")


# ── 工具 ─────────────────────────────────────────────────────────

def _is_duplicate_message(message_id: int) -> bool:
    """自动解析的消息去重（带容量上限）。"""
    now = time.monotonic()
    if len(_processed_messages) > _MAX_PROCESSED:
        # 清掉最旧的一半
        old_ids = sorted(_processed_messages, key=_processed_messages.get)[: _MAX_PROCESSED // 2]
        for mid in old_ids:
            del _processed_messages[mid]
    if message_id in _processed_messages:
        return True
    _processed_messages[message_id] = now
    return False


async def _react_ok(event: MessageEvent):
    """
    给收到的消息回应 OK 表情（NapCat 扩展 API set_msg_emoji_like）。
    仅群消息可靠；私聊或失败时静默跳过。
    """
    try:
        message_id = getattr(event, "message_id", None)
        if not message_id:
            return
        await event.bot.call_api(
            "set_msg_emoji_like",
            {"message_id": message_id, "emoji_id": 86},
        )
    except Exception as e:
        logger.debug(f"[JinmanParser] 表情回应失败: {type(e).__name__}: {e}")


# ── 事件处理 ─────────────────────────────────────────────────────

@platform_message(["qq", "discord"], priority=5, block=False)
async def handle_jm_links(event: MessageEvent):
    """自动检测并解析禁漫相册链接（需管理员开启）。"""
    try:
        if not await is_enabled_for(_scope_key(event)):
            return

        if _is_duplicate_message(event.message_id):
            return

        raw = event.raw_message or ""
        match = JM_ALBUM_URL_RE.search(raw)
        if match:
            await _react_ok(event)
            await process_jm(event, match.group(1))
    except Exception as e:
        logger.error(f"[JinmanParser] 自动解析异常: {type(e).__name__}: {e}")


@platform_command(["qq", "discord"], "jmc", "禁漫")
async def handle_jmc_command(bot, event: MessageEvent, args: list):
    """手动生成 PDF：/jmc <车牌号或链接>"""
    if not await is_enabled_for(_scope_key(event)):
        await reply_with_error_cooldown(event, "禁漫解析未开启，请联系管理员使用 /jmc解析 开启。")
        return

    text = " ".join(args).strip()
    if not text:
        await reply_with_error_cooldown(event, "用法：/jmc <禁漫车牌号或相册链接>")
        return

    album_id = extract_album_id(text)
    if not album_id:
        await reply_with_error_cooldown(event, "未能识别禁漫车牌号，请发送纯数字 ID 或 18comic/jmcomic 相册链接。")
        return

    await process_jm(event, album_id)


@platform_command(["qq", "discord"], "jmc解析", "禁漫解析", permission=Permission.ADMIN)
async def handle_jmc_toggle(bot, event: MessageEvent, args: list):
    """管理员开关禁漫解析：/jmc解析 开启|关闭|状态"""
    sub = args[0].lower() if args else ""
    scope = _scope_key(event)

    if sub in ("开", "开启", "on", "enable", "1"):
        await _set_enabled(scope, True)
        await event.reply("✅ 禁漫解析已在本群开启，本群禁漫链接将自动解析。")
        return

    if sub in ("关", "关闭", "off", "disable", "0"):
        await _set_enabled(scope, False)
        await event.reply("⛔ 禁漫解析已在本群关闭。")
        return

    if sub in ("状态", "status", "?", "help"):
        api_base, _ = _get_config()
        state_text = "开启" if await is_enabled_for(scope) else "关闭"
        if scope.startswith("group:"):
            scope_label = f"群 {scope.split(':', 1)[1]}"
        elif scope.startswith("user:"):
            scope_label = f"私聊 {scope.split(':', 1)[1]}"
        else:
            scope_label = "全局"
        await event.reply(
            f"📊 禁漫解析当前状态（{scope_label}）：{state_text}\n"
            f"数据源：自建 JMComic-Api（{api_base}）\n"
            f"用法：/jmc 车牌号 | /jmc解析 开启 | 关闭 | 状态\n"
            f"（开关按群独立，各群互不影响）"
        )
        return

    await event.reply(
        "用法：/jmc解析 开启 | 关闭 | 状态\n"
        "（仅管理员可用）"
    )
