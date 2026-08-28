"""
maimaiDX B50 查分插件

用法:
  /b50 <用户名>      按水鱼查分器用户名查询
  /b50 <QQ号>        按 QQ 查询（需在水鱼绑定过 QQ 且允许公开查询）

数据来源: 水鱼查分器 https://www.diving-fish.com（B50 = Best35 + Recent15, 服务端计算）
"""
import re
import time
from typing import List, Optional

from neobot.plugin_api import Bot, platform_command, image_manager, ModuleLogger, define_plugin
from neobot.models.events.message import MessageEvent
from neobot.models.message import MessageSegment

from .service import (
    B50QueryError, dan_name, fetch_b50, fetch_covers_b64, build_song_list,
)

logger = ModuleLogger("maimaidx")

plugin_manifest = define_plugin(
    name="maimaidx",
    description="maimaiDX 查分：B50 图片查询（水鱼查分器）",
    usage="/b50 <用户名|QQ>",
)

HELP_TEXT = """🎵 maimaiDX B50 查分

用法:
  /b50 <用户名>      按水鱼查分器用户名查询（如 /b50 turou）
  /b50 <QQ号>        按 QQ 查询（需在水鱼绑定过 QQ 且允许公开查询）
  /b50 @某人         按被 @ 者的 QQ 查询

示例:
  /b50 turou
  /b50 @张三

数据来自水鱼查分器（diving-fish.com），B50 = 最佳 35 首 + 最近 15 首。
查询不到时：确认用户名正确，或该玩家未开启「允许公开查询」（水鱼设置 → 隐私）。"""

PRIVACY_HINT = (
    "查无此人或该玩家未开启公开查询。\n"
    "确认用户名无误后，请对方在水鱼查分器登录后到「编辑个人资料」打开「允许公开查询」，再试一次。"
)


def _extract_at_qq(event: MessageEvent, raw: str) -> Optional[str]:
    """从消息中提取被 @ 的 QQ（CQ 码）：优先事件消息段，其次 raw 文本正则兜底。"""
    for seg in getattr(event, "message", None) or []:
        if getattr(seg, "type", "") == "at":
            qq = (getattr(seg, "data", None) or {}).get("qq")
            if qq is not None and str(qq).isdigit():
                return str(qq)
    m = re.search(r"\[CQ:at,qq=(\d+)\]", raw)
    if m:
        return m.group(1)
    return None


@platform_command(["qq", "discord"], "b50")
async def b50_handler(bot: Bot, event: MessageEvent, args: List[str]):
    raw = " ".join(args).strip()

    # @某人 → 取被 @ 者 QQ
    at_qq = _extract_at_qq(event, raw)
    if at_qq:
        identifier = {"qq": at_qq}
    elif not raw:
        await event.reply(HELP_TEXT)
        return
    elif raw.lower().startswith("qq:"):
        identifier = {"qq": raw[3:].strip()}
    elif raw.isdigit():
        identifier = {"qq": raw}
    else:
        identifier = {"username": raw}

    await event.reply("⏳ 正在查询 B50 并拉取封面，请稍候...")
    start = time.time()

    try:
        data = await fetch_b50(identifier)
    except B50QueryError as e:
        logger.warning(f"[b50] query failed user={raw} status={e.status} msg={e.message}")
        if e.status in (400, 403):
            await event.reply(f"❌ {PRIVACY_HINT}")
        elif e.status == 429:
            await event.reply("❌ 查分器今日查询次数已达上限，请明天再试。")
        else:
            await event.reply(f"❌ 查询失败（{e.message}）")
        return
    except Exception as e:
        logger.exception(f"[b50] unexpected error user={raw}")
        await event.reply(f"❌ 查询出错：{e}")
        return

    try:
        songs = build_song_list(data)
    except Exception:
        logger.exception(f"[b50] parse failed user={raw}")
        await event.reply("❌ 成绩数据解析失败，请稍后重试。")
        return
    if not songs:
        await event.reply("❌ 该玩家暂无成绩记录。")
        return

    # 并发拉取封面（Redis 缓存）
    try:
        covers = await fetch_covers_b64([s["song_id"] for s in data.get("charts", {}).get("dx", [])]
                                        + [s["song_id"] for s in data.get("charts", {}).get("sd", [])])
    except Exception as e:
        logger.warning(f"[b50] cover fetch failed: {e}")
        covers = {}

    for s in songs:
        s["cover"] = covers.get(int(s["song_id"]), "")

    fetched_ms = int((time.time() - start) * 1000)

    template_data = {
        "width": 1360,
        "height": 3600,
        "nickname": data.get("nickname", data.get("username", "")),
        "username": data.get("username", ""),
        "rating": data.get("rating", 0),
        "plate": data.get("plate", "") or "",
        "dan": dan_name(data.get("additional_rating")),
        "songs": songs,
        "fetched_ms": fetched_ms,
        "total_ra": sum(s["ra"] for s in songs),
    }

    try:
        base64_image = await image_manager.render_template_to_base64(
            "maimaidx_b50.html", template_data, output_name="maimaidx_b50.png",
            width=1360, height=3600,
        )
        if base64_image:
            await event.reply(MessageSegment.image(base64_image))
            logger.info(f"[b50] ok user={raw} nickname={data.get('nickname')} rating={data.get('rating')} cost={fetched_ms}ms")
            return
        raise RuntimeError("image generation returned empty result")
    except Exception as img_err:
        logger.error(f"[b50] image generation failed: {img_err}")
        await event.reply(_build_text_fallback(data, songs))
        return


def _build_text_fallback(data, songs) -> str:
    lines = [
        f"🎵 {data.get('nickname', '')} ({data.get('username', '')})  B50 Rating: {data.get('rating', 0)}",
        f"📛 段位: {dan_name(data.get('additional_rating')) or '未取得'}  |  牌子: {data.get('plate') or '无'}",
        "",
    ]
    for s in songs[:20]:
        lines.append(
            f"{s['rank']:>2}. {s['title'][:24]}  "
            f"[{s['level']}] {s['achievements']:.2f}%  ra {s['ra']}"
        )
    if len(songs) > 20:
        lines.append(f"... 共 {len(songs)} 首")
    lines.append("")
    lines.append("📊 数据来源: 水鱼查分器 (diving-fish.com)")
    return "\n".join(lines)
