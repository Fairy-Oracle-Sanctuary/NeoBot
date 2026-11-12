"""每天早上的新闻早报。只发到配置里点名的群。"""
from __future__ import annotations

import asyncio
import html
import math
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from difflib import SequenceMatcher
from typing import Optional
from urllib.parse import urlparse
from xml.etree import ElementTree
from zoneinfo import ZoneInfo

import aiohttp

from neobot.plugin_api import (
    ModuleLogger,
    bot_manager,
    define_plugin,
    global_config,
    on_shutdown,
    on_startup,
    platform_command,
    redis_manager,
)

logger = ModuleLogger("DailyNews")
SHANGHAI = ZoneInfo("Asia/Shanghai")
FRESH_WINDOW = timedelta(hours=30)
SEND_WINDOW = timedelta(minutes=10)
SENT_TTL_SECONDS = 3 * 86400
SUMMARY_LIMIT = 56
DEFAULT_LIMIT = 1800
FOOTER = "今天先看到这里，慢慢看就好。"
WEEKDAYS = "一二三四五六日"
USER_AGENT = "NeoBot/1.0 (QQ group morning digest)"
_MISSING = object()

plugin_manifest = define_plugin(
    name="daily_news",
    description="每天早上把国际快讯和时事新闻送到指定群",
    usage="/早报 - 查看今天的早报（仅配置里的指定群，大约 10 分钟一次）",
    version="0.1.0",
)

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")
_PUNCT_RE = re.compile(r"[\s\W_]+", re.UNICODE)
_TIME_RE = re.compile(r"^(\d{1,2}):(\d{2})$")

_MEM_SENT: set[str] = set()
_MEM_COOLDOWN: dict[int, float] = {}
_WARNED: set[str] = set()
_task: Optional[asyncio.Task] = None


@dataclass(frozen=True)
class NewsSource:
    name: str
    url: str
    category: str


# 2026-11-12 实际抓过：这三条是当天的条目，而且能被解析。
# 人民网 world/politics 能打开，但停在 2025-06。
# 新华网 world/politics 能打开，但停在 2022，且没有日期。所以不放进默认列表。
DEFAULT_SOURCES = (
    NewsSource("中新网国际", "https://www.chinanews.com.cn/rss/world.xml", "international"),
    NewsSource("中新网国内", "https://www.chinanews.com.cn/rss/china.xml", "domestic"),
    NewsSource("中新网社会", "https://www.chinanews.com.cn/rss/society.xml", "domestic"),
)


@dataclass(frozen=True)
class Settings:
    enabled: bool
    groups: tuple[int, ...]
    time: str
    timezone: str
    max_items_international: int
    max_items_domestic: int
    sources: tuple[NewsSource, ...]
    request_timeout: int
    send_as_forward: bool
    cooldown_seconds: int


@dataclass
class NewsItem:
    title: str
    link: str
    summary: str
    published: Optional[datetime]
    source_name: str


def reset_runtime_state() -> None:
    """清掉进程内的发送记录。测试用，也方便热重载后重新计时。"""
    _MEM_SENT.clear()
    _MEM_COOLDOWN.clear()
    _WARNED.clear()


def _clamp(value, low: int, high: int, fallback: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return fallback
    return min(high, max(low, number))


def _zone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name or "Asia/Shanghai")
    except Exception:
        return SHANGHAI


def load_settings(section=None) -> Settings:
    """从配置段读早报设置。sources 为空时用内置的中新网来源。"""
    if section is None:
        try:
            section = global_config.daily_news
        except Exception:
            section = None

    raw_groups = getattr(section, "groups", []) if section is not None else []
    groups = []
    for item in raw_groups or []:
        try:
            groups.append(int(item))
        except (TypeError, ValueError):
            continue

    sources = []
    for item in getattr(section, "sources", []) or []:
        url = str(getattr(item, "url", "") or "").strip()
        category = str(getattr(item, "category", "") or "").strip().lower()
        if not url or category not in ("international", "domestic"):
            continue
        name = str(getattr(item, "name", "") or "").strip()
        sources.append(NewsSource(name, url, category))
    if not sources:
        sources = list(DEFAULT_SOURCES)

    timezone_name = str(getattr(section, "timezone", "") or "Asia/Shanghai")
    if not _valid_zone(timezone_name):
        timezone_name = "Asia/Shanghai"

    return Settings(
        enabled=bool(getattr(section, "enabled", False)) if section is not None else False,
        groups=tuple(groups),
        time=str(getattr(section, "time", "") or "08:00"),
        timezone=timezone_name,
        max_items_international=_clamp(getattr(section, "max_items_international", 8), 1, 30, 8),
        max_items_domestic=_clamp(getattr(section, "max_items_domestic", 6), 1, 30, 6),
        sources=tuple(sources),
        request_timeout=_clamp(getattr(section, "request_timeout", 12), 3, 60, 12),
        send_as_forward=bool(getattr(section, "send_as_forward", True)),
        cooldown_seconds=_clamp(getattr(section, "manual_cooldown_seconds", 600), 30, 86400, 600),
    )


def _valid_zone(name: str) -> bool:
    try:
        ZoneInfo(name)
        return True
    except Exception:
        return False


def local_now(now: Optional[datetime], timezone_name: str) -> datetime:
    zone = _zone(timezone_name)
    if now is None:
        return datetime.now(zone)
    if now.tzinfo is None:
        return now.replace(tzinfo=zone)
    return now.astimezone(zone)


def parse_hhmm(text: str) -> tuple[int, int]:
    matched = _TIME_RE.fullmatch((text or "").strip())
    if not matched:
        return 8, 0
    hour, minute = int(matched.group(1)), int(matched.group(2))
    if hour > 23 or minute > 59:
        return 8, 0
    return hour, minute


def in_send_window(now: datetime, settings: Settings) -> bool:
    moment = local_now(now, settings.timezone)
    hour, minute = parse_hhmm(settings.time)
    start = moment.replace(hour=hour, minute=minute, second=0, microsecond=0)
    return start <= moment < start + SEND_WINDOW


def strip_html(text: str) -> str:
    cleaned = _TAG_RE.sub(" ", text or "")
    cleaned = html.unescape(cleaned)
    cleaned = cleaned.replace("\xa0", " ").replace("\u3000", " ")
    return _WS_RE.sub(" ", cleaned).strip()


def one_line(text: str, limit: int = SUMMARY_LIMIT) -> str:
    cleaned = strip_html(text)
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[:limit].rstrip() + "…"


def _normalize(title: str) -> str:
    return _PUNCT_RE.sub("", strip_html(title)).lower()


def titles_similar(left: str, right: str, threshold: float = 0.72) -> bool:
    a, b = _normalize(left), _normalize(right)
    if not a or not b:
        return False
    if a == b or a in b or b in a:
        short, long = sorted((a, b), key=len)
        if a == b or (len(short) >= 6 and len(short) / len(long) >= 0.6):
            return True
    return SequenceMatcher(None, a, b).ratio() >= threshold


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _child_text(element, name: str) -> str:
    for child in list(element):
        if _local_name(child.tag) == name:
            return "".join(child.itertext()).strip()
    return ""


def _link_of(element) -> str:
    for child in list(element):
        if _local_name(child.tag) != "link":
            continue
        href = (child.attrib.get("href") or "").strip()
        if href:
            return href
        if child.text and child.text.strip():
            return child.text.strip()
    return ""


def parse_timestamp(text: str) -> Optional[datetime]:
    raw = (text or "").strip()
    if not raw:
        return None
    try:
        parsed = parsedate_to_datetime(raw)
        if parsed is not None:
            return parsed
    except (TypeError, ValueError, IndexError, OverflowError):
        pass
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


def parse_feed(xml_text: str) -> list[NewsItem]:
    if not isinstance(xml_text, str) or "<" not in xml_text:
        return []
    try:
        root = ElementTree.fromstring(xml_text)
    except ElementTree.ParseError:
        return []
    items = []
    for element in root.iter():
        if _local_name(element.tag) not in ("item", "entry"):
            continue
        title = strip_html(_child_text(element, "title"))
        if not title:
            continue
        summary = (
            _child_text(element, "description")
            or _child_text(element, "summary")
            or _child_text(element, "content")
        )
        published = parse_timestamp(
            _child_text(element, "pubDate")
            or _child_text(element, "updated")
            or _child_text(element, "published")
        )
        items.append(NewsItem(title, _link_of(element), summary, published, ""))
    return items


def _is_fresh(published: Optional[datetime], now: datetime) -> bool:
    if published is None:
        return True
    moment = published if published.tzinfo else published.replace(tzinfo=now.tzinfo or SHANGHAI)
    moment = moment.astimezone(now.tzinfo or SHANGHAI)
    if moment - now > timedelta(hours=6):
        return False
    return now - moment <= FRESH_WINDOW


def _sort_key(item: NewsItem) -> datetime:
    if item.published is None:
        return datetime.min.replace(tzinfo=timezone.utc)
    if item.published.tzinfo is None:
        return item.published.replace(tzinfo=timezone.utc)
    return item.published


def _select(buckets: dict[str, list[NewsItem]], settings: Settings) -> dict[str, list[NewsItem]]:
    limits = {
        "international": settings.max_items_international,
        "domestic": settings.max_items_domestic,
    }
    chosen = {"international": [], "domestic": []}
    seen: list[str] = []
    for category in ("international", "domestic"):
        ordered = sorted(buckets.get(category, []), key=_sort_key, reverse=True)
        for item in ordered:
            if len(chosen[category]) >= limits[category]:
                break
            if any(titles_similar(item.title, previous) for previous in seen):
                continue
            chosen[category].append(item)
            seen.append(item.title)
    return chosen


def header_line(day) -> str:
    return f"📰 卡尔戈洛早报 · {day.isoformat()} 周{WEEKDAYS[day.weekday()]}"


def _section_block(title: str, items: list[NewsItem]) -> str:
    if not items:
        return f"{title}\n暂无新条目。"
    lines = [title]
    for index, item in enumerate(items, 1):
        lines.append(f"{index}. {item.title}")
        summary = one_line(item.summary)
        if summary and _normalize(summary) != _normalize(item.title):
            lines.append(f"   {summary}")
        if item.link:
            credit = f"{item.source_name} {item.link}".strip()
            lines.append(f"   {credit}")
    return "\n".join(lines)


def render_digest(day, international: list[NewsItem], domestic: list[NewsItem], limit: int = DEFAULT_LIMIT) -> str:
    international = list(international)
    domestic = list(domestic)
    header = header_line(day)
    while True:
        parts = [
            header,
            _section_block("国际快讯", international),
            _section_block("时事新闻", domestic),
            FOOTER,
        ]
        text = "\n\n".join(parts)
        if len(text) <= limit or (not international and not domestic):
            if len(text) <= limit:
                return text
            return text[:limit]
        if domestic:
            domestic.pop()
        else:
            international.pop()


def assemble_digest(settings: Settings, payloads, now: datetime, limit: int = DEFAULT_LIMIT) -> Optional[str]:
    moment = local_now(now, settings.timezone)
    buckets = {"international": [], "domestic": []}
    for source, payload in payloads:
        if not isinstance(source, NewsSource) or source.category not in buckets:
            continue
        if isinstance(payload, Exception) or not isinstance(payload, str):
            continue
        for item in parse_feed(payload):
            if not _is_fresh(item.published, moment):
                continue
            buckets[source.category].append(
                NewsItem(item.title, item.link, item.summary, item.published, source.name)
            )
    chosen = _select(buckets, settings)
    if not chosen["international"] and not chosen["domestic"]:
        return None
    return render_digest(moment.date(), chosen["international"], chosen["domestic"], limit)


def warn_once(token: str, message: str) -> None:
    if token in _WARNED:
        return
    _WARNED.add(token)
    logger.warning(message)


def _sent_key(day, group_id: int) -> str:
    return f"neobot:daily_news:sent:{day.isoformat()}:{group_id}"


def _cooldown_key(group_id: int) -> str:
    return f"neobot:daily_news:cooldown:{group_id}"


def _redis_client():
    try:
        return redis_manager.redis
    except Exception:
        return getattr(redis_manager, "_redis", None)


async def already_sent(client, day, group_id: int) -> bool:
    key = _sent_key(day, group_id)
    if client is None:
        return key in _MEM_SENT
    try:
        return await client.get(key) is not None
    except Exception:
        return key in _MEM_SENT


async def claim_sent(client, day, group_id: int) -> bool:
    key = _sent_key(day, group_id)
    if client is None:
        if key in _MEM_SENT:
            return False
        _MEM_SENT.add(key)
        return True
    try:
        return bool(await client.set(key, "1", nx=True, ex=SENT_TTL_SECONDS))
    except Exception:
        if key in _MEM_SENT:
            return False
        _MEM_SENT.add(key)
        return True


async def release_sent(client, day, group_id: int) -> None:
    key = _sent_key(day, group_id)
    _MEM_SENT.discard(key)
    if client is None:
        return
    try:
        await client.delete(key)
    except Exception:
        return


async def cooldown_remaining(client, group_id: int, now_ts: float, seconds: int) -> float:
    if client is None:
        until = _MEM_COOLDOWN.get(group_id)
        if until is None:
            return 0.0
        return max(0.0, until - now_ts)
    try:
        raw = await client.get(_cooldown_key(group_id))
    except Exception:
        until = _MEM_COOLDOWN.get(group_id)
        return 0.0 if until is None else max(0.0, until - now_ts)
    if not raw:
        return 0.0
    try:
        last = float(raw)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, seconds - (now_ts - last))


async def mark_cooldown(client, group_id: int, now_ts: float, seconds: int) -> None:
    _MEM_COOLDOWN[group_id] = now_ts + seconds
    if client is None:
        return
    try:
        await client.set(_cooldown_key(group_id), str(now_ts), ex=seconds + 30)
    except Exception:
        return


def _allowed_url(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.scheme in ("http", "https") and bool(parsed.netloc)


async def fetch_text(url: str, timeout: int) -> str:
    if not _allowed_url(url):
        raise RuntimeError("unsupported url")
    client_timeout = aiohttp.ClientTimeout(total=max(3, int(timeout)))
    headers = {"User-Agent": USER_AGENT, "Accept": "application/rss+xml, application/xml, text/xml, */*"}
    async with aiohttp.ClientSession(timeout=client_timeout, headers=headers) as session:
        async with session.get(url, allow_redirects=True) as response:
            if response.status >= 400:
                raise RuntimeError(f"http {response.status}")
            return await response.text(errors="replace")


async def _load_payloads(settings: Settings, fetch):
    async def one(source: NewsSource):
        try:
            return await fetch(source.url, settings.request_timeout)
        except Exception as exc:
            return exc

    results = await asyncio.gather(*(one(source) for source in settings.sources))
    return list(zip(settings.sources, results))


def _forward_nodes(bot, text: str) -> list:
    parts = [part for part in text.split("\n\n") if part.strip()]
    user_id = int(getattr(bot, "self_id", 0) or 0)
    builder = getattr(bot, "build_forward_node", None)
    nodes = []
    for part in parts:
        if builder is not None:
            nodes.append(builder(user_id, "卡尔戈洛", part))
        else:
            nodes.append({
                "type": "node",
                "data": {"uin": user_id, "name": "卡尔戈洛", "content": part},
            })
    return nodes


async def deliver(bot, group_id: int, text: str, settings: Settings) -> str:
    """先尝试合并转发。失败就改发普通文字。两种都失败时返回 failed。"""
    if settings.send_as_forward:
        try:
            send_forward = getattr(bot, "send_group_forward_msg", None)
            if send_forward is None:
                raise RuntimeError("no forward api")
            await send_forward(group_id, _forward_nodes(bot, text))
            return "forward"
        except Exception as exc:
            logger.warning(f"[早报] 合并转发没发出去，改用文字: {type(exc).__name__}")
    try:
        await bot.send_group_msg(group_id, text)
    except Exception as exc:
        logger.warning(f"[早报] 文字也没发出去: {type(exc).__name__}")
        return "failed"
    return "text"


async def _default_sender(group_id: int, text: str, settings: Settings) -> bool:
    bots = bot_manager.get_all_bots()
    if not bots:
        logger.warning("[早报] 还没有连上的机器人，这轮先不发")
        return False
    return await deliver(bots[0], group_id, text, settings) != "failed"


async def _feature_on(feature_enabled, group_id: int) -> bool:
    if feature_enabled is None:
        from neobot.plugins.group_manage import is_feature_enabled
        feature_enabled = is_feature_enabled
    try:
        return bool(await feature_enabled(group_id))
    except Exception:
        return True


async def scheduled_push(
    now: Optional[datetime] = None,
    fetch=None,
    sender=None,
    settings: Optional[Settings] = None,
    client=_MISSING,
    feature_enabled=None,
) -> int:
    """到点向仍开启早报的指定群发一条。返回实际发出的群数。"""
    settings = settings or load_settings()
    if not settings.enabled or not settings.groups:
        return 0
    moment = local_now(now, settings.timezone)
    if not in_send_window(moment, settings):
        return 0
    if client is _MISSING:
        client = _redis_client()
    sender = sender or _default_sender
    fetch = fetch or fetch_text

    pending = []
    for group_id in settings.groups:
        if not await _feature_on(feature_enabled, group_id):
            continue
        if await already_sent(client, moment.date(), group_id):
            continue
        pending.append(group_id)
    if not pending:
        return 0

    payloads = await _load_payloads(settings, fetch)
    text = assemble_digest(settings, payloads, moment)
    if text is None:
        warn_once(f"empty:{moment.date().isoformat()}", "[早报] 来源没有取到可用条目，这轮不发。")
        return 0

    sent = 0
    for group_id in pending:
        if not await claim_sent(client, moment.date(), group_id):
            continue
        try:
            ok = await sender(group_id, text, settings)
        except Exception as exc:
            logger.warning(f"[早报] 发到群 {group_id} 失败: {type(exc).__name__}")
            ok = False
        if not ok:
            await release_sent(client, moment.date(), group_id)
            continue
        await mark_cooldown(client, group_id, moment.timestamp(), settings.cooldown_seconds)
        sent += 1
        logger.info(f"[早报] 已送到群 {group_id}")
    return sent


async def manual_push(
    bot,
    event,
    now: Optional[datetime] = None,
    fetch=None,
    settings: Optional[Settings] = None,
    client=_MISSING,
    feature_enabled=None,
) -> None:
    group_id = getattr(event, "group_id", None)
    if not group_id:
        return
    group_id = int(group_id)
    settings = settings or load_settings()
    if not settings.enabled or group_id not in settings.groups:
        return
    if not await _feature_on(feature_enabled, group_id):
        await event.reply("这个群的早报关掉了。管理员可以用 /群管 开 早报。")
        return
    if client is _MISSING:
        client = _redis_client()
    moment = local_now(now, settings.timezone)
    remain = await cooldown_remaining(client, group_id, moment.timestamp(), settings.cooldown_seconds)
    if remain > 0:
        minutes = max(1, math.ceil(remain / 60))
        await event.reply(f"早报刚刚看过，约 {minutes} 分钟后再来哦。")
        return

    payloads = await _load_payloads(settings, fetch or fetch_text)
    text = assemble_digest(settings, payloads, moment)
    if text is None:
        warn_once(f"empty:{moment.date().isoformat()}", "[早报] 来源没有取到可用条目，这轮不发。")
        await event.reply("今天的早报暂时没取到，过一会儿再试试。")
        return
    mode = await deliver(bot, group_id, text, settings)
    if mode == "failed":
        await event.reply("早报没发出去，过一会儿再试。")
        return
    await mark_cooldown(client, group_id, moment.timestamp(), settings.cooldown_seconds)
    if in_send_window(moment, settings):
        await claim_sent(client, moment.date(), group_id)


def _register_group_feature() -> None:
    try:
        from neobot.plugins import group_manage
    except Exception:
        return
    group_manage.FEATURES.setdefault("daily_news", "早报")
    group_manage.FEATURE_ALIASES.setdefault("早报", "daily_news")
    group_manage.FEATURE_ALIASES.setdefault("日报", "daily_news")


_register_group_feature()


@platform_command(["qq"], "早报")
async def handle_daily_news(bot, event, args):
    await manual_push(bot, event)


async def _loop() -> None:
    await asyncio.sleep(8)
    while True:
        try:
            await scheduled_push()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            hour = datetime.now(SHANGHAI).strftime("%Y%m%d%H")
            warn_once(f"loop:{type(exc).__name__}:{hour}", f"[早报] 这一轮没有发出去: {exc}")
        await asyncio.sleep(30)


@on_startup
async def start_daily_news() -> None:
    global _task
    if _task is not None and not _task.done():
        return
    _task = asyncio.create_task(_loop())
    logger.info("[早报] 已开始留意早上八点")


@on_shutdown
async def stop_daily_news() -> None:
    global _task
    task = _task
    _task = None
    if task is not None:
        task.cancel()
