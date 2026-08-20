import math
from dataclasses import dataclass
from typing import Optional

from ..ts_oma.node_bridge import (
    run_mixed_estimator,
    SimpleAnalysis,
    SimpleEstimator,
    SimpleInterlude,
    SimplePatterns,
)


@dataclass
class DifficultyResult:
    analysis: Optional[SimpleAnalysis] = None
    error: Optional[str] = None
    error_code: Optional[str] = None
    speed_rate: float = 1.0


def _mode_tag_from_ln_ratio(ln_ratio: float) -> str:
    if not math.isfinite(ln_ratio):
        return "Mix"
    if ln_ratio <= 0.15:
        return "RC"
    if ln_ratio >= 0.9:
        return "LN"
    return "Mix"


def calculate_difficulty(osu_text: str, speed_rate: float = 1.0) -> DifficultyResult:
    result = run_mixed_estimator(osu_text, speed_rate=speed_rate)
    if result.error:
        return DifficultyResult(
            error=f"难度计算出错: {result.error}",
            error_code="calc_error",
            speed_rate=speed_rate,
        )

    estimator = SimpleEstimator(
        star=result.star,
        column_count=result.column_count,
        ln_ratio=result.ln_ratio,
        est_diff=result.est_diff,
        numeric_difficulty=result.numeric_difficulty,
        numeric_difficulty_hint=result.numeric_difficulty_hint,
        graph=result.graph,
        pattern_category=result.pattern_category,
        pattern_mode_tag=result.pattern_mode_tag,
        sv_amount=result.sv_amount,
    )

    mode_tag = _mode_tag_from_ln_ratio(result.ln_ratio)

    analysis = SimpleAnalysis(
        estimator=estimator,
        interlude=SimpleInterlude(overall=0.0),
        patterns=SimplePatterns(report=None),
        mode_tag=mode_tag,
    )

    return DifficultyResult(analysis=analysis, speed_rate=speed_rate)


DIFFICULTY_HELP = """📊 难度查询帮助

命令格式:
  /难度 <谱面链接>    查询谱面的详细难度数据
  /sr <谱面链接>      同上
  /难度 <bid>         通过谱面 ID 查询

示例:
  /难度 https://osu.ppy.sh/beatmapsets/123#mania/456
  /sr 4549003

查询结果包含:
  • Sunny SR / Interlude SR / Mixed SR
  • 难度标签 (est_diff)
  • 模式标签 (RC/LN/HB/Mix)
  • 键位数 / LN比例
  • 模式分类 (Category)
"""
