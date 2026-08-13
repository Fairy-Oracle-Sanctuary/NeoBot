import time
from typing import List

from neobot.core.bot import Bot
from neobot.core.managers.command_manager import matcher
from neobot.core.managers.image_manager import image_manager
from neobot.core.utils.logger import ModuleLogger
from neobot.models.events.message import MessageEvent
from neobot.models.message import MessageSegment

from .service import BeatmapMeta
from .ghost_song.fetcher import resolve_and_fetch, FetchError as FetcherError
from .difficulty.calculator import calculate_difficulty, DIFFICULTY_HELP
from .difficulty.diagnostics import diagnose, MapDiagnostics

logger = ModuleLogger("osu_plugin")

__plugin_meta__ = {
    "name": "osu! Plugin",
    "description": "osu! 综合工具：谱面重算难度 + 难度查询",
    "usage": "/omm <链接/bid> | /难度 <链接/bid>",
}

SLOW_THRESHOLD_MS = 5000


def _check_slow(elapsed_ms: int) -> str:
    if elapsed_ms >= SLOW_THRESHOLD_MS:
        return f"\n⚠️ 计算耗时较长 ({elapsed_ms}ms)，谱面可能非常复杂"
    return ""


# ── OMM Help ─────────────────────────────────────────────────────

OMM_HELP_TEXT = """🎹 osu!mania 重算难度查询

命令格式:
  /omm <谱面链接>     通过 osu! 链接查询重算难度
  /omm <bid>          通过谱面 ID 查询

示例:
  /omm https://osu.ppy.sh/beatmapsets/123#mania/456
  /omm 4549003

基于 ts_oma (Node.js) 引擎重新计算:
  • 鬼歌/PP铺 检测
  • RC / LN Dan 预估
  • Sunny SR + Interlude SR
  • 难度标签 + 模式类别"""


# ── OMM Result Formatting ────────────────────────────────────────

def _build_omm_text(analysis, meta: "BeatmapMeta", elapsed_ms: int, dx: MapDiagnostics) -> str:
    lines = []
    e = analysis.estimator
    i = analysis.interlude
    p = analysis.patterns

    lines.append(f"🎵 谱面: {meta.artist} - {meta.title} [{meta.version}]")
    lines.append(f"👤 Mapper: {meta.mapper} | ⭐ 官方SR: {meta.official_sr}")
    lines.append(f"🎹 键位: {meta.cs}K | BPM: {meta.bpm} | LN: {e.ln_ratio:.0%}")
    lines.append("")

    type_line = f"🏷 谱面类型: {dx.map_type_emoji} {dx.map_type}"
    if dx.sr_deviation != 0.0:
        type_line += f" (SR偏差: {dx.sr_deviation:+.1f})"
    lines.append(type_line)
    lines.append("")

    lines.append("📊 重算难度:")
    sr_label = "Azusa SR" if e.numeric_difficulty_hint == "azusa-rc-v1" else "Rework SR"
    lines.append(f"  {sr_label}:   {e.star:.2f} ★")
    if i.overall > 0:
        lines.append(f"  Interlude:  {i.overall:.2f} ISR")
    lines.append(f"  难度标签:   {e.est_diff}")
    lines.append(f"  模式标签:   {analysis.mode_tag}")
    if e.pattern_category:
        lines.append(f"  键型类别:   {e.pattern_category}")
    if e.pattern_mode_tag and e.pattern_mode_tag != analysis.mode_tag:
        lines.append(f"  键型标签:   {e.pattern_mode_tag}")
    if e.sv_amount >= 2000:
        lines.append(f"  ⚠️ SV铺面 (SV时间: {e.sv_amount:.0f}ms)")
    if e.numeric_difficulty is not None:
        lines.append(f"  难度数值:   {e.numeric_difficulty:.1f}")

    category = ""
    if p.report:
        category = p.report.get("Category", "")
    if category:
        lines.append(f"  模式类别:   {category}")

    if dx.rc_dan or dx.ln_dan:
        lines.append("")
        lines.append("📈 Dan 预估:")
        if dx.rc_dan:
            num_part = f" ({dx.rc_numeric:.1f})" if dx.rc_numeric is not None else ""
            lines.append(f"  RC Dan:     {dx.rc_dan}{num_part}")
        if dx.ln_dan:
            lines.append(f"  LN Dan:     {dx.ln_dan}")

    lines.append(f"\n⏱ 耗时: {elapsed_ms}ms")
    slow = _check_slow(elapsed_ms)
    if slow:
        lines.append(slow)
    lines.append("")
    lines.append("难度计算引擎由 https://github.com/LeoBlackMT/osumania_map_analyser/ (Node.js) 提供,本插件仅进行了封装操作，无任何修改")
    lines.append(OMM_HELP_TEXT)
    return "\n".join(lines)


# ── Difficulty Result Formatting ─────────────────────────────────

def _build_difficulty_text(analysis, meta: "BeatmapMeta", elapsed_ms: int) -> str:
    lines = []
    e = analysis.estimator
    i = analysis.interlude
    p = analysis.patterns

    lines.append(f"🎵 谱面: {meta.artist} - {meta.title} [{meta.version}]")
    lines.append(f"👤 Mapper: {meta.mapper} | ⭐ 官方SR: {meta.official_sr}")
    lines.append(f"🎹 键位: {meta.cs}K | LN: {e.ln_ratio:.0%} | 模式: {analysis.mode_tag}")
    lines.append("")
    lines.append("📊 难度分析结果:")
    sr_label = "Azusa SR" if e.numeric_difficulty_hint == "azusa-rc-v1" else "Rework SR"
    lines.append(f"  • {sr_label}:   {e.star:.2f} ★")
    if i.overall > 0:
        lines.append(f"  • Interlude SR: {i.overall:.2f} ISR")
    lines.append(f"  • 难度标签:   {e.est_diff}")
    lines.append(f"  • 模式标签:   {analysis.mode_tag}")
    if e.numeric_difficulty is not None:
        lines.append(f"  • 难度数值:   {e.numeric_difficulty:.1f}")
    if e.pattern_category:
        lines.append(f"  • 键型类别:   {e.pattern_category}")
    if e.pattern_mode_tag and e.pattern_mode_tag != analysis.mode_tag:
        lines.append(f"  • 键型标签:   {e.pattern_mode_tag}")

    lines.append(f"  • 键位数:     {e.column_count}K")
    lines.append(f"⏱ 耗时: {elapsed_ms}ms")
    slow = _check_slow(elapsed_ms)
    if slow:
        lines.append(slow)

    lines.append("")
    lines.append("难度计算引擎由 https://github.com/LeoBlackMT/osumania_map_analyser/ (Node.js) 提供,本插件仅进行了封装操作，无任何修改")

    return "\n".join(lines)


# ── Shared Processing ────────────────────────────────────────────

async def _process_beatmap_query(event: MessageEvent, user_input: str, build_text):
    start = time.time()

    fetched = await resolve_and_fetch(user_input)
    if isinstance(fetched, FetcherError):
        logger.warning(
            f"[query] user={event.user_id} input={user_input[:60]} "
            f"error_code={fetched.code} error={fetched.message}"
        )
        await event.reply(f"❌ {fetched.message}")
        return

    diff_result = calculate_difficulty(fetched.osu_text)
    if diff_result.error:
        logger.error(
            f"[calc] user={event.user_id} bid={fetched.meta.bid} "
            f"error_code={diff_result.error_code} error={diff_result.error}"
        )
        await event.reply(f"❌ {diff_result.error}")
        return

    analysis = diff_result.analysis
    assert analysis is not None
    elapsed_ms = int((time.time() - start) * 1000)
    text = build_text(analysis, fetched.meta, elapsed_ms)

    if elapsed_ms >= SLOW_THRESHOLD_MS:
        logger.warning(
            f"[slow] user={event.user_id} bid={fetched.meta.bid} elapsed={elapsed_ms}ms"
        )

    if len(text) > 4000:
        text = text[:3900] + "\n\n... (输出过长已截断)"

    logger.info(
        f"[ok] user={event.user_id} bid={fetched.meta.bid} "
        f"sunny={analysis.estimator.star:.1f} "
        f"elapsed={elapsed_ms}ms"
    )

    await event.reply(text)


# ── Command Handlers ─────────────────────────────────────────────

@matcher.platform_command(["qq", "discord"], "omm")
async def omm_handler(bot: Bot, event: MessageEvent, args: List[str]):
    user_input = " ".join(args).strip()
    if not user_input:
        await event.reply(OMM_HELP_TEXT)
        return

    speed_rate = 1.0
    speed_label = ""
    upper_args = [a.upper() for a in args]
    if "DT" in upper_args:
        speed_rate = 1.5
        speed_label = "DT"
    elif "HT" in upper_args:
        speed_rate = 0.75
        speed_label = "HT"

    if speed_label:
        mod_arg = " DT" if speed_label == "DT" else " HT"
        if user_input.upper().endswith(mod_arg):
            user_input = user_input[: -len(mod_arg)]

    action_text = "⏳ 正在获取谱面数据并计算重算难度，请稍候..."
    if speed_label:
        action_text = f"⏳ 正在获取谱面数据并计算{speed_label}难度，请稍候..."
    await event.reply(action_text)

    start = time.time()

    fetched = await resolve_and_fetch(user_input)
    if isinstance(fetched, FetcherError):
        logger.warning(
            f"[omm] user={event.user_id} input={user_input[:60]} "
            f"error_code={fetched.code} error={fetched.message}"
        )
        await event.reply(f"❌ {fetched.message}")
        return

    diff_result = calculate_difficulty(fetched.osu_text, speed_rate=speed_rate)
    if diff_result.error:
        logger.error(
            f"[omm] user={event.user_id} bid={fetched.meta.bid} "
            f"error_code={diff_result.error_code} error={diff_result.error}"
        )
        await event.reply(f"❌ {diff_result.error}")
        return

    analysis = diff_result.analysis
    assert analysis is not None

    dx = diagnose(analysis, official_sr=fetched.meta.official_sr)

    elapsed_ms = int((time.time() - start) * 1000)

    e = analysis.estimator

    sr_deviation_str = ""
    delta_class = "delta-normal"
    if dx.sr_deviation != 0.0:
        sr_deviation_str = f"{dx.sr_deviation:+.1f}"
        if dx.sr_deviation >= 1.0:
            delta_class = "delta-ghost"
        elif dx.sr_deviation <= -1.0:
            delta_class = "delta-pp"

    badge_class = "badge-normal"
    if dx.map_type == "鬼歌":
        badge_class = "badge-ghost"
    elif dx.map_type == "PP铺":
        badge_class = "badge-pp"

    template_data = {
        "cover_url": fetched.meta.cover_url or "",
        "artist": fetched.meta.artist,
        "title": fetched.meta.title,
        "version": fetched.meta.version,
        "mapper": fetched.meta.mapper,
        "official_sr_fmt": f"{fetched.meta.official_sr:.2f}",
        "recalc_sr_fmt": f"{e.star:.2f}",
        "sr_label": "Azusa SR" if e.numeric_difficulty_hint == "azusa-rc-v1" else "Rework SR",
        "sr_deviation": dx.sr_deviation,
        "sr_deviation_fmt": sr_deviation_str,
        "delta_class": delta_class,
        "badge_class": badge_class,
        "map_type_emoji": dx.map_type_emoji,
        "map_type": dx.map_type,
        "bpm": f"{fetched.meta.bpm:.0f}",
        "keys": e.column_count,
        "ln_pct": f"{e.ln_ratio:.0%}",
        "mode_tag": analysis.mode_tag,
        "est_diff": e.est_diff,
        "pattern_category": e.pattern_category,
        "sv_amount": e.sv_amount,
        "is_sv_heavy": e.sv_amount >= 2000,
        "numeric_difficulty": f"{e.numeric_difficulty:.1f}" if e.numeric_difficulty is not None else None,
        "rc_dan": dx.rc_dan or "—",
        "rc_numeric": f"{dx.rc_numeric:.1f}" if dx.rc_numeric is not None else None,
        "ln_dan": dx.ln_dan or "—",
        "elapsed_ms": f"{elapsed_ms}ms",
        "speed_label": speed_label,
        "has_graph": e.graph is not None and bool(e.graph.get("times")),
    }

    if e.graph and e.graph.get("times"):
        import json as _json
        graph_times = [float(t) for t in e.graph.get("times", [])]
        graph_values = [float(v) for v in e.graph.get("values", [])]
        template_data["graph_json"] = _json.dumps({
            "times": graph_times,
            "values": graph_values,
        })

    if elapsed_ms >= SLOW_THRESHOLD_MS:
        logger.warning(
            f"[slow] user={event.user_id} bid={fetched.meta.bid} elapsed={elapsed_ms}ms"
        )

    logger.info(
        f"[omm] user={event.user_id} bid={fetched.meta.bid} "
        f"type={dx.map_type} sunny={analysis.estimator.star:.1f} "
        f"elapsed={elapsed_ms}ms"
    )

    try:
        base64_image = await image_manager.render_template_to_base64(
            "osu_difficulty.html", template_data, output_name="omm_result.png"
        )
        if base64_image:
            await event.reply(MessageSegment.image(base64_image))
        else:
            raise RuntimeError("image generation returned empty result")
    except Exception as img_err:
        logger.error(f"[omm] image generation failed: {img_err}")
        text = _build_omm_text(analysis, fetched.meta, elapsed_ms, dx)
        if len(text) > 4000:
            text = text[:3900] + "\n\n... (输出过长已截断)"
        await event.reply(text)


@matcher.platform_command(["qq", "discord"], "难度", "sr")
async def difficulty_handler(bot: Bot, event: MessageEvent, args: List[str]):
    user_input = " ".join(args).strip()
    if not user_input:
        await event.reply(DIFFICULTY_HELP)
        return

    await event.reply("⏳ 正在获取谱面数据并计算难度，请稍候...")
    await _process_beatmap_query(event, user_input, _build_difficulty_text)


@matcher.platform_command(["qq", "discord"], "难度帮助", "srhelp")
async def difficulty_help_handler(bot: Bot, event: MessageEvent, args: List[str]):
    await event.reply(DIFFICULTY_HELP)
