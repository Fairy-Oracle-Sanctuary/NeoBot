from dataclasses import dataclass

from ..service import BeatmapMeta


@dataclass
class FetchedBeatmap:
    osu_text: str
    meta: BeatmapMeta


@dataclass
class FetchError:
    code: str
    message: str


FETCH_INVALID_INPUT = FetchError("INVALID_INPUT", "无法从输入中识别谱面 ID，请提供谱面链接或 bid")
FETCH_NOT_MANIA = FetchError("NOT_MANIA", "该谱面不是 osu!mania 模式，本插件仅支持 mania (Mode: 3)")

WARNING_NOT_MANIA_TEMPLATES = {
    0: "osu!standard",
    1: "osu!taiko",
    2: "osu!catch",
}


async def resolve_and_fetch(user_input: str) -> "FetchedBeatmap | FetchError":
    from ..service import parse_beatmap_id, fetch_beatmap_meta, download_osu_text

    bid = parse_beatmap_id(user_input)
    if bid is None:
        return FETCH_INVALID_INPUT

    meta_result = await fetch_beatmap_meta(bid)
    if meta_result.error:
        return FetchError(meta_result.error_code or "fetch_error", meta_result.error)

    meta = meta_result.meta
    if meta.mode_int != 3:
        mode_name = WARNING_NOT_MANIA_TEMPLATES.get(meta.mode_int, f"Mode={meta.mode_int}")
        return FetchError(
            "NOT_MANIA",
            f"该谱面不是 osu!mania 模式 (当前模式: {mode_name})\n"
            f"本插件仅支持 mania (Mode: 3) 谱面",
        )

    dl_result = await download_osu_text(bid)
    if dl_result.error:
        return FetchError(dl_result.error_code or "download_error", dl_result.error)

    return FetchedBeatmap(osu_text=dl_result.osu_text, meta=meta)
