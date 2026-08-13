# -*- coding: utf-8 -*-
"""
推特/X 链接解析插件

功能：
- 管理员通过 `/推特解析 开启|关闭|状态` 控制解析功能的开关（状态持久化到 Redis）
- 开启后自动解析群聊/私聊中的 twitter.com / x.com 推文链接（含 t.co 短链）
- `/推特 <链接>` 手动解析

数据源：FixTweet (fxtwitter) 公开 API，无需 API Key / SDK。
接口：GET https://api.fxtwitter.com/status/<tweet_id>
"""
import asyncio
import os
import re
import time
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

import aiohttp

from neobot.core.managers.command_manager import matcher
from neobot.core.managers.redis_manager import redis_manager
from neobot.core.permission import Permission
from neobot.core.services.local_file_server import download_to_local
from neobot.core.utils.logger import ModuleLogger
from neobot.models.events.message import MessageEvent
from neobot.models.message import MessageSegment

logger = ModuleLogger("TwitterParser")

__plugin_meta__ = {
    "name": "推特解析",
    "description": "解析 Twitter/X 链接（需管理员开启，数据源 fxtwitter 无需 API Key）",
    "usage": (
        "/推特解析 开启|关闭|状态 （管理员）\n"
        "/推特 <链接> 手动解析\n"
        "开启后自动解析 twitter.com / x.com / t.co 链接"
    ),
}

# FixTweet API，可通过环境变量覆盖（例如自建实例）
API_BASE = os.environ.get("TWITTER_PARSER_API", "https://api.fxtwitter.com").rstrip("/")
REQUEST_TIMEOUT = 15
REDIS_KEY = "neobot:plugin:twitter_parser:enabled"

# twitter.com/x.com 状态页链接（支持 /i/status 形式）
STATUS_URL_RE = re.compile(
    r"https?://(?:www\.)?(?:twitter\.com|x\.com)/(?:[A-Za-z0-9_]{1,20}|i)/status/(\d+)",
    re.IGNORECASE,
)
# X 短链
TCO_URL_RE = re.compile(r"https?://t\.co/[A-Za-z0-9]+", re.IGNORECASE)

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

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

# twimg 媒体下载请求头
_TWIMG_HEADERS = {
    "User-Agent": _USER_AGENT,
    "Referer": "https://x.com/",
}


# ── 开关状态 ─────────────────────────────────────────────────────

def _scope_key(event: MessageEvent) -> str:
    """
    计算开关的作用域：群聊按群号，私聊按对方QQ。

    状态精确到群聊，各群互不影响；私聊则按用户独立。
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
        logger.debug(f"[TwitterParser] Redis 不可用，使用内存状态: {type(e).__name__}: {e}")
        enabled = False
    _enabled_map[scope] = enabled
    logger.debug(f"[TwitterParser] 加载开关状态 {scope}: {enabled}")
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
        logger.info(f"[TwitterParser] 开关状态已持久化 {scope}: {value}")
        return True
    except Exception as e:
        logger.debug(f"[TwitterParser] Redis 持久化失败，仅内存生效: {type(e).__name__}: {e}")
        return False


# ── HTTP 请求 ────────────────────────────────────────────────────

async def _get_session() -> aiohttp.ClientSession:
    global _session
    if _session is None or _session.closed:
        _session = aiohttp.ClientSession(
            headers={
                "User-Agent": _USER_AGENT,
                "Accept": "application/json",
            },
            # 走系统代理环境变量（neobot 服务已注入 http_proxy 指向 mihomo）
            trust_env=True,
            timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT),
        )
    return _session


async def fetch_tweet(tweet_id: str) -> Optional[dict]:
    """
    通过 FixTweet API 获取推文数据。

    Returns:
        API 返回的完整 JSON；网络错误/非 JSON 响应返回 None。
    """
    url = f"{API_BASE}/status/{tweet_id}"
    try:
        session = await _get_session()
        async with session.get(url) as response:
            try:
                return await response.json(content_type=None)
            except (ValueError, aiohttp.ClientError) as e:
                logger.error(f"[TwitterParser] API 响应解析失败: {type(e).__name__}: {e}")
                return None
    except (aiohttp.ClientError, asyncio.TimeoutError) as e:
        logger.error(f"[TwitterParser] 请求 FixTweet API 失败: {type(e).__name__}: {e}")
        return None
    except Exception as e:
        logger.error(f"[TwitterParser] 获取推文异常: {type(e).__name__}: {e}")
        return None


async def resolve_short_url(url: str) -> Optional[str]:
    """跟随 t.co 短链跳转，返回最终 URL。"""
    try:
        session = await _get_session()
        async with session.get(url, allow_redirects=True, timeout=10) as response:
            final_url = str(response.url)
            return final_url if final_url != url else None
    except (aiohttp.ClientError, asyncio.TimeoutError) as e:
        logger.error(f"[TwitterParser] 短链解析失败: {type(e).__name__}: {e}")
        return None
    except Exception as e:
        logger.error(f"[TwitterParser] 短链解析异常: {type(e).__name__}: {e}")
        return None


# ── 格式化 ───────────────────────────────────────────────────────

def _fmt_num(value) -> str:
    """数字格式化为可读形式（1.2万）。"""
    try:
        n = int(value)
    except (TypeError, ValueError):
        return str(value)
    if abs(n) < 10000:
        return str(n)
    return f"{n / 10000:.1f}万"


def _format_created_at(created_at: Optional[str]) -> str:
    """把 "Tue Feb 15 21:21:13 +0000 2022" 格式化为 "2022-02-15 21:21"。"""
    if not created_at:
        return ""
    try:
        dt = datetime.strptime(created_at.strip(), "%a %b %d %H:%M:%S %z %Y")
        return dt.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M")
    except (ValueError, TypeError):
        return created_at


def _build_tweet_card(tweet: dict) -> str:
    """构建推文文本卡片。"""
    author = tweet.get("author") or {}
    name = author.get("name") or "未知用户"
    screen_name = author.get("screen_name") or "unknown"
    text = (tweet.get("text") or "").strip() or "（无文字内容）"
    if len(text) > 500:
        text = text[:500] + "…"

    lines = [
        "🐦 推特解析",
        "━━━━━━━━━━━━━━━━",
        f"👤 {name} @{screen_name}",
        "━━━━━━━━━━━━━━━━",
        text,
    ]

    if tweet.get("possibly_sensitive"):
        lines.append("")
        lines.append("⚠️ 可能包含敏感内容")

    lines.append("━━━━━━━━━━━━━━━━")
    stats = []
    if tweet.get("likes") is not None:
        stats.append(f"❤️ {_fmt_num(tweet['likes'])}")
    if tweet.get("retweets") is not None:
        stats.append(f"🔁 {_fmt_num(tweet['retweets'])}")
    if tweet.get("replies") is not None:
        stats.append(f"💬 {_fmt_num(tweet['replies'])}")
    if tweet.get("views") is not None:
        stats.append(f"👀 {_fmt_num(tweet['views'])}")
    if stats:
        lines.append("  ".join(stats))

    created = _format_created_at(tweet.get("created_at"))
    if created:
        lines.append(f"🕐 {created} (UTC)")
    if tweet.get("url"):
        lines.append(f"🔗 {tweet['url']}")
    return "\n".join(lines)


def _collect_media(tweet: dict) -> Tuple[List[str], List[str]]:
    """
    提取推文媒体。

    Returns:
        (图片URL列表, 视频URL列表)
    """
    media = tweet.get("media") or {}
    photos: List[str] = []
    videos: List[str] = []

    for item in media.get("all") or []:
        if not isinstance(item, dict):
            continue
        item_type = item.get("type", "")
        url = item.get("url") or ""
        if not url:
            continue
        if item_type == "photo":
            photos.append(url)
        elif item_type in ("video", "gif"):
            videos.append(url)

    # 兼容旧版/缺失 all 字段的响应
    if not photos:
        photos = [
            p.get("url", "")
            for p in (media.get("photos") or [])
            if isinstance(p, dict) and p.get("url")
        ]
    if not videos:
        videos = [
            v.get("url", "")
            for v in (media.get("videos") or [])
            if isinstance(v, dict) and v.get("url")
        ]

    return photos, videos


# ── 发送 ─────────────────────────────────────────────────────────

def _get_event_target(event: MessageEvent) -> str:
    return str(getattr(event, "group_id", None) or getattr(event, "user_id", None) or "unknown")


async def reply_with_error_cooldown(event: MessageEvent, text: str) -> bool:
    """同一目标在冷却时间内不重复发送完全相同的错误提示。"""
    key = (_get_event_target(event), text)
    now = time.monotonic()
    if now - _error_reply_cooldown.get(key, 0.0) < _ERROR_COOLDOWN_SECONDS:
        logger.debug(f"[TwitterParser] 相同失败提示在冷却期内，跳过重复回复: {text[:40]}")
        return False

    if len(_error_reply_cooldown) > 256:
        oldest = sorted(_error_reply_cooldown, key=_error_reply_cooldown.get)[:128]
        for old_key in oldest:
            del _error_reply_cooldown[old_key]

    _error_reply_cooldown[key] = now
    await event.reply(text)
    return True


async def _send_media(event: MessageEvent, photos: List[str], videos: List[str]):
    """
    下载富媒体并发送：图片/视频先由机器人下载到本地文件服务器，
    NapCat 只需从 127.0.0.1 拉取，不再依赖外网直连。
    下载失败时回退为原始链接（NapCat 侧代理可兜底）。
    """
    if photos:
        media_urls = await _download_media_urls(photos[:4], timeout=60)
        image_segments = [MessageSegment.image(url) for url in media_urls]
        try:
            await event.reply(image_segments)
        except Exception as e:
            logger.error(f"[TwitterParser] 图片发送失败: {type(e).__name__}: {e}")
            await event.reply("图片发送失败，原图链接：\n" + "\n".join(photos[:4]))

    if videos:
        video_url = videos[0]
        try:
            local_url = await download_to_local(video_url, timeout=120, headers=_TWIMG_HEADERS)
            if local_url:
                logger.info(f"[TwitterParser] 视频已下载到本地: {local_url}")
                video_url = local_url
        except Exception as e:
            logger.error(f"[TwitterParser] 视频下载失败: {type(e).__name__}: {e}")
        try:
            await event.reply(MessageSegment.video(video_url))
        except Exception as e:
            logger.error(f"[TwitterParser] 视频发送失败: {type(e).__name__}: {e}")
            await event.reply("视频发送失败，直链：\n" + videos[0])


async def _download_media_urls(urls: List[str], timeout: int = 60) -> List[str]:
    """批量下载媒体到本地文件服务器；失败时回退原始链接。"""
    async def _download_one(url: str) -> str:
        try:
            local_url = await download_to_local(url, timeout=timeout, headers=_TWIMG_HEADERS)
            if local_url:
                logger.info(f"[TwitterParser] 媒体已下载到本地: {local_url}")
                return local_url
        except Exception as e:
            logger.error(f"[TwitterParser] 媒体下载失败: {type(e).__name__}: {e}")
        return url

    return await asyncio.gather(*(_download_one(u) for u in urls))


async def _send_tweet(event: MessageEvent, tweet: dict):
    """
    发送推文解析结果：
    - 解析文本作为独立消息直接发到群里（不放进合并转发/聊天记录）
    - 富媒体直发（与抖音解析一致）；敏感内容（possibly_sensitive）的富媒体
      包裹在合并转发（聊天记录）中发出来，避免敏感图/视频直接刷屏
    """
    share_text = _extract_share_text(event)
    photos, videos = _collect_media(tweet)
    sensitive = bool(tweet.get("possibly_sensitive"))

    card = _build_tweet_card(tweet)
    if share_text:
        card = f"分享内容：{share_text}\n\n{card}"
    try:
        await event.reply(card)
    except Exception as e:
        logger.error(f"[TwitterParser] 文本卡片发送失败: {type(e).__name__}: {e}")

    if not photos and not videos:
        return
    if sensitive:
        await _send_sensitive_media(event, photos, videos)
    else:
        await _send_media(event, photos, videos)


async def _send_sensitive_media(event: MessageEvent, photos: List[str], videos: List[str]):
    """敏感内容的富媒体包裹在合并转发（聊天记录）中发送；失败时回退为直发。"""
    try:
        nodes = await _build_media_forward_nodes(event, photos, videos)
        if not nodes:
            await _send_media(event, photos, videos)
            return
        await event.bot.send_forwarded_messages(target=event, nodes=nodes)
        logger.info("[TwitterParser] 敏感内容富媒体已包裹在聊天记录中发送")
    except Exception as e:
        logger.error(f"[TwitterParser] 聊天记录发送敏感媒体失败，回退直发: {type(e).__name__}: {e}")
        await _send_media(event, photos, videos)


def _extract_share_text(event: MessageEvent) -> str:
    """从触发解析的消息中提取分享文字（去掉链接与空白）。"""
    raw = event.raw_message or ""
    text = re.sub(STATUS_URL_RE, " ", raw)
    text = re.sub(TCO_URL_RE, " ", text)
    text = re.sub(r"https?://\S+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _sender_identity(event: MessageEvent) -> Tuple[int, str]:
    """聊天记录节点的身份：取触发解析的人的 QQ 号与昵称。"""
    qq = int(getattr(event, "user_id", 0) or 0)
    nickname = ""
    sender = getattr(event, "sender", None)
    if sender is not None:
        nickname = getattr(sender, "nickname", "") or ""
    return qq, (nickname or "推特解析")


async def _build_media_forward_nodes(
    event: MessageEvent,
    photos: List[str],
    videos: List[str],
) -> List[dict]:
    """
    构建仅包含富媒体的合并转发（聊天记录）节点：
    - 每张推文图片一个节点
    - 末节点为推文视频
    QQ 号取触发解析的人；媒体先下载到本地文件服务器。
    """
    qq, nickname = _sender_identity(event)
    nodes: List[dict] = []

    photo_count = min(len(photos), 4)
    photo_urls = await _download_media_urls(photos[:4], timeout=60)
    for i, url in enumerate(photo_urls, 1):
        try:
            nodes.append(
                event.bot.build_forward_node(
                    user_id=qq,
                    nickname=nickname,
                    message=[
                        MessageSegment.text(f"推文图片 {i}/{photo_count}：\n"),
                        MessageSegment.image(url),
                    ],
                )
            )
        except Exception as e:
            logger.warning(f"[TwitterParser] 聊天记录图片节点失败: {type(e).__name__}: {e}")

    if videos:
        video_url = videos[0]
        try:
            local_url = await download_to_local(video_url, timeout=120, headers=_TWIMG_HEADERS)
            if local_url:
                video_url = local_url
        except Exception as e:
            logger.error(f"[TwitterParser] 敏感视频下载失败: {type(e).__name__}: {e}")
        try:
            nodes.append(
                event.bot.build_forward_node(
                    user_id=qq,
                    nickname=nickname,
                    message=[
                        MessageSegment.text("推文视频：\n"),
                        MessageSegment.video(video_url),
                    ],
                )
            )
        except Exception as e:
            logger.warning(f"[TwitterParser] 聊天记录视频节点失败: {type(e).__name__}: {e}")

    return nodes


async def process_tweet(event: MessageEvent, tweet_id: str):
    """获取并发送推文解析结果。"""
    data = await fetch_tweet(tweet_id)
    if data is None:
        await reply_with_error_cooldown(event, "推特解析失败，请稍后再试。")
        return

    tweet = data.get("tweet")
    if data.get("code") != 200 or not tweet:
        message = (data.get("message") or "").strip()
        if not message or message.upper() in ("NOT_FOUND", "UNKNOWN"):
            message = "推文不存在或不可访问（可能已删除、私密或被限制）。"
        await reply_with_error_cooldown(event, f"推特解析失败：{message}")
        return

    # tombstone = 推文已不可用
    if isinstance(tweet, dict) and tweet.get("type") == "tombstone":
        reason = (tweet.get("message") or "该推文已不可用").strip()
        await reply_with_error_cooldown(event, f"推特解析失败：{reason}")
        return

    await _send_tweet(event, tweet)


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


async def _handle_tweet_url(event: MessageEvent, url: str) -> bool:
    """解析单个推特链接，返回是否成功识别并处理。"""
    match = STATUS_URL_RE.search(url)
    if match:
        await process_tweet(event, match.group(1))
        return True

    tco_match = TCO_URL_RE.search(url)
    if tco_match:
        final_url = await resolve_short_url(tco_match.group(0))
        match = STATUS_URL_RE.search(final_url or "")
        if match:
            await process_tweet(event, match.group(1))
            return True

    return False


async def _react_ok(event: MessageEvent):
    """
    给收到的消息回应 OK 表情（NapCat 扩展 API set_msg_emoji_like）。

    仅群消息可靠；私聊或失败时静默跳过，不影响解析流程。
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
        logger.debug(f"[TwitterParser] 表情回应失败: {type(e).__name__}: {e}")


# ── 事件处理 ─────────────────────────────────────────────────────

@matcher.platform_message(["qq", "discord"], priority=5, block=False)
async def handle_twitter_links(event: MessageEvent):
    """自动检测并解析 twitter.com / x.com / t.co 链接（需管理员开启）。"""
    try:
        if not await is_enabled_for(_scope_key(event)):
            return

        if _is_duplicate_message(event.message_id):
            return

        raw = event.raw_message or ""
        if STATUS_URL_RE.search(raw) or TCO_URL_RE.search(raw):
            await _react_ok(event)
            await _handle_tweet_url(event, raw)
    except Exception as e:
        logger.error(f"[TwitterParser] 自动解析异常: {type(e).__name__}: {e}")


@matcher.platform_command(["qq", "discord"], "推特", "twitter")
async def handle_twitter_command(bot, event: MessageEvent, args: list):
    """手动解析推特链接：/推特 <链接>"""
    if not await is_enabled_for(_scope_key(event)):
        await reply_with_error_cooldown(event, "推特解析未开启，请联系管理员使用 /推特解析 开启。")
        return

    url = " ".join(args).strip()
    if not url:
        await reply_with_error_cooldown(event, "用法：/推特 <推文链接>")
        return

    handled = await _handle_tweet_url(event, url)
    if handled:
        await _react_ok(event)
    else:
        await reply_with_error_cooldown(event, "未能从链接中识别推文，请发送 twitter.com 或 x.com 的推文链接。")


@matcher.platform_command(["qq", "discord"], "推特解析", "twitter_parse", permission=Permission.ADMIN)
async def handle_twitter_toggle(bot, event: MessageEvent, args: list):
    """管理员开关推特解析：/推特解析 开启|关闭|状态"""
    sub = args[0].lower() if args else ""
    scope = _scope_key(event)

    if sub in ("开", "开启", "on", "enable", "1"):
        await _set_enabled(scope, True)
        await event.reply("✅ 推特解析已在本群开启，本群推特链接将自动解析。")
        return

    if sub in ("关", "关闭", "off", "disable", "0"):
        await _set_enabled(scope, False)
        await event.reply("⛔ 推特解析已在本群关闭。")
        return

    if sub in ("状态", "status", "?", "help"):
        state_text = "开启" if await is_enabled_for(scope) else "关闭"
        if scope.startswith("group:"):
            scope_label = f"群 {scope.split(':', 1)[1]}"
        elif scope.startswith("user:"):
            scope_label = f"私聊 {scope.split(':', 1)[1]}"
        else:
            scope_label = "全局"
        await event.reply(
            f"📊 推特解析当前状态（{scope_label}）：{state_text}\n"
            f"数据源：FixTweet API（无需 API Key）\n"
            f"用法：/推特解析 开启 | 关闭 | 状态\n"
            f"（开关按群独立，各群互不影响）"
        )
        return

    await event.reply(
        "用法：/推特解析 开启 | 关闭 | 状态\n"
        "（仅管理员可用）"
    )
