from dataclasses import dataclass
from typing import Optional


@dataclass
class MapDiagnostics:
    map_type: str = ""
    map_type_emoji: str = ""
    rc_dan: str = ""
    rc_numeric: Optional[float] = None
    ln_dan: str = ""
    sr_deviation: float = 0.0

_GHOST_SR_DEVIATION = 1.0
_PP_SR_DEVIATION = 1.0


def _safe_float(value, default=0.0) -> float:
    try:
        v = float(value)
        return v if v == v else default
    except (ValueError, TypeError):
        return default


def _split_difficulty_parts(est_diff: str):
    text = str(est_diff or "").strip()
    parts = [p.strip() for p in text.split("||") if p.strip()]
    if len(parts) >= 2:
        return parts[0], parts[1]
    return (parts[0] if parts else ""), ""


def diagnose(analysis, official_sr: Optional[float] = None) -> MapDiagnostics:
    e = analysis.estimator
    sunny_sr = _safe_float(e.star)

    # ── Ghost / PP detection: simple SR comparison ──
    sr_deviation = 0.0
    if official_sr is not None and official_sr > 0:
        sr_deviation = sunny_sr - _safe_float(official_sr)

    if sr_deviation >= _GHOST_SR_DEVIATION:
        map_type = "鬼歌"
        map_type_emoji = "👻"
    elif sr_deviation <= -_PP_SR_DEVIATION:
        map_type = "PP铺"
        map_type_emoji = "💧"
    else:
        map_type = "正常"
        map_type_emoji = "🎵"

    # ── RC / LN dan from est_diff split ──
    rc_dan, ln_dan = _split_difficulty_parts(e.est_diff)
    rc_numeric = e.numeric_difficulty

    return MapDiagnostics(
        map_type=map_type,
        map_type_emoji=map_type_emoji,
        rc_dan=rc_dan,
        rc_numeric=rc_numeric,
        ln_dan=ln_dan,
        sr_deviation=sr_deviation,
    )
