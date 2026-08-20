# -*- coding: utf-8 -*-
"""
E-Hentai / ExHentai 画廊解析插件

功能：
- 管理员通过 `/eh解析 开启|关闭|状态` 控制解析功能的开关（状态持久化到 Redis，默认关闭）
- 开启后 `/eh <链接>` 手动解析；群聊/私聊中发送 e-hentai.org / exhentai.org 画廊链接也会自动解析
- 回复画廊信息：封面图 + 标题 + 页数 + 评分 + 标签
- `/ehpdf <链接或gid_token>` 生成完整 PDF 并上传到群文件（参考 jmc 解析模式）

数据源：自建 RESTful-ehentai-api 服务（https://github.com/bandcomic/RESTful-ehentai-api）
接口：
- GET {api_base}/comic/<gid>_<token>       画廊详情（标题/页数/评分/封面/标签）
- GET {api_base}/photo/<id>/<chapter>      虚拟章节图片列表（每 20 张一章）
- GET {api_base}/image/proxy?url=...       图片代理（下载原图用）

注意：ExHentai 需要 Cookie 才能访问全部内容；服务端无 Cookie 时以游客身份
访问公开 E-Hentai 内容。Cookie 可在 [ehentai] 配置块中提供（可选）。
"""
import asyncio
import math
import re
import time
from typing import Dict, List, Optional, Tuple

import aiohttp
from neobot.plugin_api import platform_command, platform_message, redis_manager, Permission, get_local_file_server, ModuleLogger, global_config, define_plugin
from neobot.models.events.message import MessageEvent
from neobot.models.message import MessageSegment

logger = ModuleLogger("EhentaiParser")

plugin_manifest = define_plugin(
    name="ehentai_parser",
    description="E-Hentai / ExHentai 画廊链接解析与 PDF 生成（需管理员开启，自建 RESTful-ehentai-api 服务）",
    usage="/eh解析 开启|关闭|状态 （管理员）\n"
        "/eh <链接> 手动解析\n"
        "/ehpdf <链接或gid_token> 生成完整 PDF\n"
        "开启后自动解析 e-hentai.org / exhentai.org 画廊链接",
)

# 默认服务地址与超时，可通过 [ehentai] 配置块覆盖
DEFAULT_API_BASE = "http://127.0.0.1:8677"
DEFAULT_TIMEOUT = 30

REDIS_KEY = "neobot:plugin:ehentai_parser:enabled"

# E-Hentai / ExHentai 画廊链接（/g/<gid>/<token>/）
EH_GALLERY_URL_RE = re.compile(
    r"https?://(?:www\.)?(?:e-hentai|exhentai)\.org/g/(\d+)/([a-f0-9]+)",
    re.IGNORECASE,
)
# gid_token 直接输入（如 3645215_4db836130d）
GID_TOKEN_RE = re.compile(r"^\s*(\d+)_([a-f0-9]+)\s*$", re.IGNORECASE)

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

# PDF 图片并发下载数
_PDF_DOWNLOAD_CONCURRENCY = 8


# ── 配置 ──────────────────────────────────────────────────────

def _get_config() -> Tuple[str, int, str]:
    """
    读取 [ehentai] 配置块（延迟 import，避免模块加载时解析全局配置）。

    Returns:
        (api_base, timeout, cookie)
    """
    try:
        cfg = global_config.ehentai
        return (
            (cfg.api_base or DEFAULT_API_BASE).rstrip("/"),
            cfg.timeout or DEFAULT_TIMEOUT,
            (cfg.cookie or "").strip(),
        )
    except Exception as e:
        logger.debug(f"[EhentaiParser] 读取配置失败，使用默认值: {type(e).__name__}: {e}")
        return DEFAULT_API_BASE, DEFAULT_TIMEOUT, ""


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
        logger.debug(f"[EhentaiParser] Redis 不可用，使用内存状态: {type(e).__name__}: {e}")
        enabled = False
    _enabled_map[scope] = enabled
    logger.debug(f"[EhentaiParser] 加载开关状态 {scope}: {enabled}")
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
        logger.info(f"[EhentaiParser] 开关状态已持久化 {scope}: {value}")
        return True
    except Exception as e:
        logger.debug(f"[EhentaiParser] Redis 持久化失败，仅内存生效: {type(e).__name__}: {e}")
        return False


# ── HTTP 请求 ────────────────────────────────────────────────────

async def _get_session() -> aiohttp.ClientSession:
    global _session
    if _session is None or _session.closed:
        _, timeout, _ = _get_config()
        _session = aiohttp.ClientSession(
            # 走系统代理环境变量（生产已注入 http_proxy 指向 mihomo）
            trust_env=True,
            timeout=aiohttp.ClientTimeout(total=timeout),
        )
    return _session


async def fetch_comic_info(comic_id: str) -> Optional[dict]:
    """
    获取画廊详情（标题/页数/评分/封面/标签）。

    Args:
        comic_id: 画廊 ID，格式 `gid_token`（如 3645215_4db836130d）

    Returns:
        画廊信息字典；失败返回 None。
    """
    api_base, _, cookie = _get_config()
    url = f"{api_base}/comic/{comic_id}"
    headers = {}
    if cookie:
        headers["Cookie"] = cookie
    try:
        session = await _get_session()
        async with session.get(url, headers=headers, timeout=15) as response:
            if response.status != 200:
                logger.error(f"[EhentaiParser] 获取画廊详情失败 HTTP {response.status}: {comic_id}")
                return None
            data = await response.json(content_type=None)
            if not data or not data.get("name"):
                return None
            return data
    except Exception as e:
        logger.error(f"[EhentaiParser] 获取画廊详情异常: {type(e).__name__}: {e}")
        return None


async def fetch_photo_chapter(comic_id: str, chapter: int) -> Optional[List[str]]:
    """
    获取画廊某一虚拟章节的图片代理 URL 列表。

    Args:
        comic_id: 画廊 ID（gid_token）
        chapter: 虚拟章节编号（从 1 开始，每 20 张一章）

    Returns:
        图片 URL 列表；失败返回 None。
    """
    api_base, _, cookie = _get_config()
    url = f"{api_base}/photo/{comic_id}/{chapter}"
    headers = {}
    if cookie:
        headers["Cookie"] = cookie
    try:
        session = await _get_session()
        async with session.get(url, headers=headers, timeout=15) as response:
            if response.status != 200:
                logger.error(f"[EhentaiParser] 获取章节图片失败 HTTP {response.status}: {comic_id}/{chapter}")
                return None
            data = await response.json(content_type=None)
            if not data or not data.get("images"):
                return None
            return [img.get("url", "") for img in data["images"] if img.get("url")]
    except Exception as e:
        logger.error(f"[EhentaiParser] 获取章节图片异常: {type(e).__name__}: {e}")
        return None


async def collect_all_image_urls(comic_id: str, info: dict) -> Optional[List[str]]:
    """
    遍历所有虚拟章节，收集画廊全部图片的代理 URL。

    Args:
        comic_id: 画廊 ID（gid_token）
        info: fetch_comic_info 返回的详情

    Returns:
        全部图片 URL 列表（按章节顺序）；失败返回 None。
    """
    page_count = info.get("page_count") or 0
    total_chapters = info.get("total_chapters") or max(1, math.ceil(page_count / 20))
    if total_chapters <= 0:
        return None

    urls: List[str] = []
    for chapter in range(1, total_chapters + 1):
        chapter_urls = await fetch_photo_chapter(comic_id, chapter)
        if chapter_urls:
            urls.extend(chapter_urls)
        else:
            logger.warning(f"[EhentaiParser] 章节 {chapter}/{total_chapters} 获取失败，跳过")
        # 章节间轻微间隔，避免压垮代理服务
        await asyncio.sleep(0.2)

    return urls or None


async def _download_one_image(session: aiohttp.ClientSession, url: str, sem: asyncio.Semaphore) -> Optional[bytes]:
    """下载单张图片（并发受限），失败返回 None。"""
    async with sem:
        try:
            async with session.get(url, timeout=30) as response:
                if response.status != 200:
                    return None
                return await response.read()
        except Exception as e:
            logger.debug(f"[EhentaiParser] 图片下载失败: {type(e).__name__}: {e}")
            return None


def _build_pdf(images: List[bytes]) -> Optional[bytes]:
    """
    用 Pillow 把图片列表合成 PDF（内存中完成）。

    每张图片先转 RGB（去掉 alpha 通道），再追加到单页 PDF。
    图片解码失败时跳过该页（不中断整个画廊）。
    """
    from PIL import Image
    import io

    try:
        pages = []
        for idx, img_bytes in enumerate(images, 1):
            try:
                img = Image.open(io.BytesIO(img_bytes))
                if img.mode != "RGB":
                    img = img.convert("RGB")
                pages.append(img)
            except Exception as e:
                logger.debug(f"[EhentaiParser] 第 {idx} 张图片解码失败，跳过: {type(e).__name__}: {e}")
                continue

        if not pages:
            return None

        buf = io.BytesIO()
        pages[0].save(buf, format="PDF", save_all=True, append_images=pages[1:])
        return buf.getvalue()
    except Exception as e:
        logger.error(f"[EhentaiParser] PDF 合成失败: {type(e).__name__}: {e}")
        return None


def _sanitize_filename(name: str) -> str:
    """去除 Windows/QQ 文件名的非法字符并截断。"""
    import re as _re

    name = _re.sub(r'[\\/:*?"<>|\r\n]', "", name).strip()
    return name[:120] or "EH"


async def generate_pdf(comic_id: str, info: dict) -> Tuple[Optional[str], Optional[str]]:
    """
    生成画廊 PDF 并注册到本地文件服务器。

    Args:
        comic_id: 画廊 ID（gid_token）
        info: fetch_comic_info 返回的详情（含标题）

    Returns:
        (本地访问 URL, 文件名)；失败时返回 (None, 错误信息)
    """
    server = get_local_file_server()
    if server is None or server.site is None:
        logger.error("[EhentaiParser] 本地文件服务器未启用，无法中转 PDF")
        return None, "本地文件服务未启用"

    title = (info.get("name") or "").strip()
    page_count = info.get("page_count") or 0
    logger.info(f"[EhentaiParser] 开始收集图片: {comic_id} ({page_count} 页)")

    urls = await collect_all_image_urls(comic_id, info)
    if not urls:
        return None, "未能获取画廊图片列表"

    session = await _get_session()
    sem = asyncio.Semaphore(_PDF_DOWNLOAD_CONCURRENCY)
    tasks = [_download_one_image(session, u, sem) for u in urls]
    results = await asyncio.gather(*tasks)
    images = [b for b in results if b]

    if not images:
        return None, "图片下载全部失败"

    logger.info(f"[EhentaiParser] 图片下载完成: {len(images)}/{len(urls)}，开始合成 PDF")

    pdf_bytes = _build_pdf(images)
    if not pdf_bytes:
        return None, "PDF 合成失败"

    file_id = server._generate_file_id(f"eh://{comic_id}")
    dest = server.download_dir / file_id
    with open(dest, "wb") as f:
        f.write(pdf_bytes)

    server.file_map[file_id] = dest
    local_url = f"{server.base_url}/download?id={file_id}"
    filename = _build_pdf_filename(comic_id, title)
    logger.success(f"[EhentaiParser] PDF 已保存: {dest} ({dest.stat().st_size} bytes)")
    return local_url, filename


def _build_pdf_filename(comic_id: str, title: Optional[str]) -> str:
    """生成上传到群文件的 PDF 文件名：[<id>] <标题>.pdf"""
    if title:
        return f"[{comic_id}] {_sanitize_filename(title)}.pdf"
    return f"[{comic_id}].pdf"


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
        logger.error(f"[EhentaiParser] 上传 PDF 失败: {type(e).__name__}: {e}")
        return False


async def process_eh_pdf(event: MessageEvent, comic_id: str):
    """生成并发送画廊 PDF。"""
    # 先给用户即时反馈（图片收集 + 合成可能耗时较长）
    await event.reply(f"⏳ 正在生成 [{comic_id}] 的 PDF，可能需要几分钟…")

    info = await fetch_comic_info(comic_id)
    if not info:
        await reply_with_error_cooldown(event, "未能获取画廊信息，可能是链接不存在或服务异常。")
        return

    local_url, filename = await generate_pdf(comic_id, info)
    if not local_url or not filename:
        error_msg = filename or "生成失败"
        await reply_with_error_cooldown(event, f"E站 PDF 生成失败：{error_msg}")
        return

    ok = await upload_pdf(event, local_url, filename)
    if ok:
        title_part = f"《{(info.get('name') or '').strip()}》" if (info.get('name') or '').strip() else ""
        await event.reply(f"✅ [{comic_id}] {title_part} PDF 已发送到本群文件。")
    else:
        await reply_with_error_cooldown(event, "PDF 生成成功但上传失败，请稍后再试。")


# ── 链接提取 ─────────────────────────────────────────────────

def extract_comic_id(text: str) -> Optional[str]:
    """
    从文本中提取 E-Hentai 画廊 ID（gid_token）。

    支持：
    - 完整链接：`https://e-hentai.org/g/3645215/4db836130d/`
    - gid_token：`3645215_4db836130d`

    Returns:
        画廊 ID 字符串（gid_token）；无法识别返回 None。
    """
    if not text:
        return None
    m = EH_GALLERY_URL_RE.search(text)
    if m:
        return f"{m.group(1)}_{m.group(2)}"
    m = GID_TOKEN_RE.match(text.strip())
    if m:
        return f"{m.group(1)}_{m.group(2)}"
    return None


# ── 发送 ─────────────────────────────────────────────────────────

def _get_event_target(event: MessageEvent) -> str:
    return str(getattr(event, "group_id", None) or getattr(event, "user_id", None) or "unknown")


async def reply_with_error_cooldown(event: MessageEvent, text: str) -> bool:
    """同一目标在冷却时间内不重复发送完全相同的错误提示。"""
    key = (_get_event_target(event), text)
    now = time.monotonic()
    if now - _error_reply_cooldown.get(key, 0.0) < _ERROR_COOLDOWN_SECONDS:
        logger.debug(f"[EhentaiParser] 相同失败提示在冷却期内，跳过重复回复: {text[:40]}")
        return False

    if len(_error_reply_cooldown) > 256:
        oldest = sorted(_error_reply_cooldown, key=_error_reply_cooldown.get)[:128]
        for old_key in oldest:
            del _error_reply_cooldown[old_key]

    _error_reply_cooldown[key] = now
    await event.reply(text)
    return True


def _format_tags(tags) -> str:
    """格式化标签：最多展示 12 个，逗号分隔。"""
    if not tags:
        return "无"
    return "、".join(str(t) for t in tags[:12])


async def send_gallery_info(event: MessageEvent, info: dict):
    """
    发送画廊信息（封面图 + 文本详情）。
    封面图发送失败时降级为纯文本。
    """
    name = (info.get("name") or "未知标题").strip()
    page_count = info.get("page_count", 0)
    rate = info.get("rate", 0)
    cover = (info.get("cover") or "").strip()
    tags_text = _format_tags(info.get("tags"))

    text_lines = [
        f"📖 {name}",
        f"页数: {page_count}  评分: {rate}",
        f"标签: {tags_text}",
        f"来源: https://e-hentai.org/g/{info.get('item_id', '')}",
    ]

    try:
        if cover:
            await event.reply(
                [
                    MessageSegment.image(cover),
                    MessageSegment.text("\n".join(text_lines)),
                ]
            )
            return
    except Exception as e:
        logger.warning(f"[EhentaiParser] 封面图发送失败，降级纯文本: {type(e).__name__}: {e}")

    await event.reply("\n".join(text_lines))


async def process_eh(event: MessageEvent, comic_id: str):
    """查询并发送画廊信息。"""
    info = await fetch_comic_info(comic_id)
    if not info:
        await reply_with_error_cooldown(event, "未能获取画廊信息，可能是链接不存在或服务异常。")
        return
    await send_gallery_info(event, info)


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
        logger.debug(f"[EhentaiParser] 表情回应失败: {type(e).__name__}: {e}")


# ── 事件处理 ─────────────────────────────────────────────────────

@platform_message(["qq", "discord"], priority=5, block=False)
async def handle_eh_links(event: MessageEvent):
    """自动检测并解析 E-Hentai 画廊链接（需管理员开启）。"""
    try:
        if not await is_enabled_for(_scope_key(event)):
            return

        if _is_duplicate_message(event.message_id):
            return

        raw = event.raw_message or ""
        match = EH_GALLERY_URL_RE.search(raw)
        if match:
            await _react_ok(event)
            await process_eh(event, f"{match.group(1)}_{match.group(2)}")
    except Exception as e:
        logger.error(f"[EhentaiParser] 自动解析异常: {type(e).__name__}: {e}")


@platform_command(["qq", "discord"], "eh", "E站", "ehentai")
async def handle_eh_command(bot, event: MessageEvent, args: list):
    """手动解析：/eh <链接或 gid_token>"""
    if not await is_enabled_for(_scope_key(event)):
        await reply_with_error_cooldown(event, "E站解析未开启，请联系管理员使用 /eh解析 开启。")
        return

    text = " ".join(args).strip()
    if not text:
        await reply_with_error_cooldown(event, "用法：/eh <E-Hentai画廊链接或 gid_token>")
        return

    comic_id = extract_comic_id(text)
    if not comic_id:
        await reply_with_error_cooldown(
            event, "未能识别画廊链接，请发送 e-hentai.org / exhentai.org 的 /g/ 链接。"
        )
        return

    await process_eh(event, comic_id)


@platform_command(["qq", "discord"], "ehpdf", "E站pdf")
async def handle_eh_pdf_command(bot, event: MessageEvent, args: list):
    """生成完整 PDF：/ehpdf <链接或 gid_token>（参考 jmc 模式，上传到群文件）"""
    if not await is_enabled_for(_scope_key(event)):
        await reply_with_error_cooldown(event, "E站解析未开启，请联系管理员使用 /eh解析 开启。")
        return

    text = " ".join(args).strip()
    if not text:
        await reply_with_error_cooldown(event, "用法：/ehpdf <E-Hentai画廊链接或 gid_token>")
        return

    comic_id = extract_comic_id(text)
    if not comic_id:
        await reply_with_error_cooldown(
            event, "未能识别画廊链接，请发送 e-hentai.org / exhentai.org 的 /g/ 链接。"
        )
        return

    await process_eh_pdf(event, comic_id)


@platform_command(["qq", "discord"], "eh解析", "E站解析", permission=Permission.ADMIN)
async def handle_eh_toggle(bot, event: MessageEvent, args: list):
    """管理员开关 E站解析：/eh解析 开启|关闭|状态"""
    sub = args[0].lower() if args else ""
    scope = _scope_key(event)

    if sub in ("开", "开启", "on", "enable", "1"):
        await _set_enabled(scope, True)
        await event.reply("✅ E站解析已在本群开启，本群 E-Hentai 画廊链接将自动解析。")
        return

    if sub in ("关", "关闭", "off", "disable", "0"):
        await _set_enabled(scope, False)
        await event.reply("⛔ E站解析已在本群关闭。")
        return

    if sub in ("状态", "status", "?", "help"):
        api_base, _, _ = _get_config()
        state_text = "开启" if await is_enabled_for(scope) else "关闭"
        if scope.startswith("group:"):
            scope_label = f"群 {scope.split(':', 1)[1]}"
        elif scope.startswith("user:"):
            scope_label = f"私聊 {scope.split(':', 1)[1]}"
        else:
            scope_label = "全局"
        await event.reply(
            f"📊 E站解析当前状态（{scope_label}）：{state_text}\n"
            f"数据源：自建 RESTful-ehentai-api（{api_base}）\n"
            f"用法：/eh 链接 | /eh解析 开启 | 关闭 | 状态\n"
            f"（开关按群独立，各群互不影响）"
        )
        return

    await event.reply(
        "用法：/eh解析 开启 | 关闭 | 状态\n"
        "（仅管理员可用）"
    )
