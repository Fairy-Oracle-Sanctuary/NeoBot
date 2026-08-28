"""
maimaiDX B50 查分插件

用法:
  /b50 bind <用户名>   绑定自己的水鱼账号（含 OAuth 授权，可查隐私成绩）
  /b50 unbind          解绑
  /b50                 查询自己（需先 bind）
  /b50 <用户名>        按水鱼查分器用户名查询
  /b50 <QQ号>          按 QQ 查询（需在水鱼绑定过 QQ 且允许公开查询）
  /b50 @某人           按被 @ 者的 QQ 查询

数据来源: 水鱼查分器 https://www.diving-fish.com（B50 = Best35 + Recent15, 服务端计算）
OAuth 绑定用户可读隐私成绩；无游玩时间戳时按 Best50 近似并标注。
"""
import re
import time
from typing import List, Optional

from neobot.plugin_api import Bot, platform_command, image_manager, ModuleLogger, define_plugin
from neobot.models.events.message import MessageEvent
from neobot.models.message import MessageSegment

from .service import (
    B50QueryError, OAuthNotConfigured, build_best50, build_song_list, clear_bind,
    dan_name, fetch_b50, fetch_covers_b64, fetch_full_records, get_bind,
    mask_qq, set_bind, start_binding,
)

logger = ModuleLogger("maimaidx")

plugin_manifest = define_plugin(
    name="maimaidx",
    description="maimaiDX 查分：B50 图片查询（水鱼查分器）",
    usage="/b50 bind <用户名> | /b50 [用户名|QQ|@某人]",
)

HELP_TEXT = """🎵 maimaiDX B50 查分

绑定:
  /b50 bind <用户名>   绑定自己的水鱼账号（点击授权链接可查隐私成绩）
  /b50 unbind          解绑

查询:
  /b50                 查询自己（需先绑定）
  /b50 <用户名>        按水鱼用户名查询（如 /b50 turou）
  /b50 <QQ号>          按 QQ 查询（需在水鱼绑定过 QQ 且允许公开查询）
  /b50 @某人           按被 @ 者的 QQ 查询

数据来自水鱼查分器（diving-fish.com），B50 = 最佳 35 首 + 最近 15 首。
未绑定用户查询受限：对方未开启「允许公开查询」时查不到。"""

PRIVACY_HINT = (
    "查无此人或该玩家未开启公开查询。\n"
    "确认用户名无误后，请对方在水鱼查分器登录后到「编辑个人资料」打开「允许公开查询」，再试一次。\n"
    "绑定自己的账号（/b50 bind <用户名>）可无视此限制查询自己的成绩。"
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


# ── 渲染 ────────────────────────────────────────────────────────

async def _render_b50(event: MessageEvent, data: dict, groups: dict, approx: bool = False) -> None:
    """拉封面 + 渲染图片回复（B35/B15 分区）；图片失败回退文本。"""
    start = time.time()
    b35, b15 = groups.get("b35", []), groups.get("b15", [])
    try:
        covers = await fetch_covers_b64([s["song_id"] for s in b35 + b15])
    except Exception as e:
        logger.warning(f"[b50] cover fetch failed: {e}")
        covers = {}
    for s in b35 + b15:
        s["cover"] = covers.get(s["song_id"], "")

    fetched_ms = int((time.time() - start) * 1000)

    template_data = {
        "width": 1360,
        "height": 3800,
        "nickname": data.get("nickname", data.get("username", "")),
        "username": data.get("username", ""),
        "rating": data.get("rating", 0),
        "plate": data.get("plate", "") or "",
        "dan": dan_name(data.get("additional_rating")),
        "songs_b35": b35,
        "songs_b15": b15,
        "fetched_ms": fetched_ms,
        "approx": approx,
        "total_ra": sum(s["ra"] for s in b35 + b15),
    }

    try:
        base64_image = await image_manager.render_template_to_base64(
            "maimaidx_b50.html", template_data, output_name="maimaidx_b50.png",
            width=1360, height=3800,
        )
        if base64_image:
            await event.reply(MessageSegment.image(base64_image))
            logger.info(
                f"[b50] ok nickname={data.get('nickname')} rating={data.get('rating')} "
                f"approx={approx} cost={fetched_ms}ms"
            )
            return
        raise RuntimeError("image generation returned empty result")
    except Exception as img_err:
        logger.error(f"[b50] image generation failed: {img_err}")
        await event.reply(_build_text_fallback(data, groups, approx))
        return


def _build_text_fallback(data: dict, groups: dict, approx: bool) -> str:
    label = "Best50(近似)" if approx else "B50"
    lines = [
        f"🎵 {data.get('nickname', '')} ({data.get('username', '')})  {label} Rating: {data.get('rating', 0)}",
        f"📛 段位: {dan_name(data.get('additional_rating')) or '未取得'}  |  牌子: {data.get('plate') or '无'}",
        "",
    ]
    b35, b15 = groups.get("b35", []), groups.get("b15", [])
    lines.append(f"── B35 · 旧版本曲目最佳 {len(b35)} 首 ──")
    for s in b35[:15]:
        lines.append(
            f"{s['rank']:>2}. {s['title'][:24]}  [{s['level']}] {s['achievements']:.2f}%  ra {s['ra']}"
        )
    if b15:
        lines.append(f"── B15 · 新版本曲目最佳 {len(b15)} 首 ──")
        for s in b15[:15]:
            lines.append(
                f"{s['rank']:>2}. {s['title'][:24]}  [{s['level']}] {s['achievements']:.2f}%  ra {s['ra']}"
            )
    lines.append("")
    lines.append("📊 数据来源: 水鱼查分器 (diving-fish.com)")
    return "\n".join(lines)


async def _query_and_render(event: MessageEvent, raw: str, identifier: dict, approx: bool = False) -> None:
    """公开接口查询 + 渲染。"""
    await event.reply("⏳ 正在查询 B50 并拉取封面，请稍候...")
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
        groups = build_song_list(data)
    except Exception:
        logger.exception(f"[b50] parse failed user={raw}")
        await event.reply("❌ 成绩数据解析失败，请稍后重试。")
        return
    if not groups.get("b35") and not groups.get("b15"):
        await event.reply("❌ 该玩家暂无成绩记录。")
        return

    await _render_b50(event, data, groups, approx=approx)


@platform_command(["qq", "discord"], "b50")
async def b50_handler(bot: Bot, event: MessageEvent, args: List[str]):
    raw = " ".join(args).strip()
    at_qq = _extract_at_qq(event, raw)
    qq = str(event.user_id)

    # ── bind / unbind 子命令 ───────────────────────────────────
    if raw == "unbind":
        ok = await clear_bind(qq)
        await event.reply("✅ 已解绑。" if ok else "❌ 解绑失败，请稍后重试。")
        return

    if raw.startswith("bind"):
        username = raw[4:].strip()
        if not username or username.lower().startswith("qq:"):
            await event.reply("用法: /b50 bind <水鱼用户名>\n用户名是查分器登录名，如 /b50 bind turou")
            return
        ok = await set_bind(qq, username)
        if not ok:
            await event.reply("❌ 绑定写入失败，请稍后重试。")
            return
        try:
            link = await start_binding(qq, mask_qq(qq))
            if link:
                await event.reply(
                    f"✅ 已绑定 {username}。\n\n"
                    f"请点击链接完成水鱼授权（10 分钟有效），之后 /b50 可查完整成绩（含隐私）：\n{link}\n\n"
                    f"未完成授权也不影响 /b50 查询公开数据。"
                )
            else:
                await event.reply(f"✅ 已绑定 {username}。")
        except OAuthNotConfigured:
            await event.reply(f"✅ 已绑定 {username}（未配置 OAuth 凭据，仅能查公开数据）。")
        except Exception as e:
            logger.warning(f"[b50] bind oauth failed qq={qq}: {e}")
            await event.reply(f"✅ 已绑定 {username}（授权链接生成失败：{e}，仍可查公开数据）。")
        return

    # ── 无参数：查自己 ─────────────────────────────────────────
    if not raw and not at_qq:
        bound = await get_bind(qq)
        if not bound:
            await event.reply(
                "你还没绑定水鱼账号。\n"
                "用法: /b50 bind <水鱼用户名>\n"
                "之后直接 /b50 即可查询自己的成绩。\n\n"
                "查别人: /b50 <用户名> | /b50 <QQ> | /b50 @某人"
            )
            return
        # OAuth 优先：绑定用户可读隐私成绩
        try:
            records = await fetch_full_records(qq)
            if records:
                best = build_best50(records.get("records", []))
                if not best:
                    await event.reply("❌ 该玩家暂无成绩记录。")
                    return
                await _render_b50(event, records, {"b35": best, "b15": []}, approx=True)
                return
        except OAuthNotConfigured:
            pass
        except Exception as e:
            logger.warning(f"[b50] oauth query failed qq={qq}: {e}，回落公开接口")
        # 回落：公开接口按绑定用户名查
        await _query_and_render(event, bound, {"username": bound})
        return

    # ── 指定目标查询 ───────────────────────────────────────────
    if at_qq:
        identifier = {"qq": at_qq}
    elif raw.lower().startswith("qq:"):
        identifier = {"qq": raw[3:].strip()}
    elif raw.isdigit():
        identifier = {"qq": raw}
    elif raw:
        identifier = {"username": raw}
    else:
        await event.reply(HELP_TEXT)
        return
    await _query_and_render(event, raw, identifier)
