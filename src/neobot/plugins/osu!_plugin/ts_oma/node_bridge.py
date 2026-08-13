import json
import subprocess
import os
from dataclasses import dataclass, field
from typing import Optional


_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_ESTIMATOR_SCRIPT = os.path.join(_SCRIPT_DIR, "js", "run_estimator.mjs")
_JS_DIR = os.path.join(_SCRIPT_DIR, "js")


@dataclass
class NodeEstimatorResult:
    star: float = 0.0
    column_count: int = 0
    ln_ratio: float = 0.0
    est_diff: str = ""
    numeric_difficulty: Optional[float] = None
    numeric_difficulty_hint: Optional[str] = None
    graph: Optional[dict] = None
    pattern_category: str = ""
    pattern_mode_tag: str = ""
    sv_amount: float = 0.0
    error: Optional[str] = None


def run_mixed_estimator(osu_text: str, speed_rate: float = 1.0) -> NodeEstimatorResult:
    try:
        proc = subprocess.run(
            ["node", _ESTIMATOR_SCRIPT, str(speed_rate)],
            input=osu_text,
            capture_output=True,
            text=True,
            timeout=60,
            cwd=_JS_DIR,
        )
        if proc.returncode != 0:
            stderr = (proc.stderr or "").strip()
            return NodeEstimatorResult(error=f"Node.js error: {stderr}")
        data = json.loads(proc.stdout.strip())
        if "error" in data:
            return NodeEstimatorResult(error=data["error"])
        return NodeEstimatorResult(
            star=data.get("star", 0.0),
            column_count=data.get("column_count", 0),
            ln_ratio=data.get("ln_ratio", 0.0),
            est_diff=data.get("est_diff", ""),
            numeric_difficulty=data.get("numeric_difficulty"),
            numeric_difficulty_hint=data.get("numeric_difficulty_hint"),
            graph=data.get("graph"),
            pattern_category=data.get("pattern_category", ""),
            pattern_mode_tag=data.get("pattern_mode_tag", ""),
            sv_amount=data.get("sv_amount", 0.0),
        )
    except subprocess.TimeoutExpired:
        return NodeEstimatorResult(error="Node.js 计算超时（60秒）")
    except FileNotFoundError:
        return NodeEstimatorResult(error="Node.js 未安装或不可用")
    except json.JSONDecodeError:
        return NodeEstimatorResult(error="Node.js 返回了无效的 JSON")
    except Exception as e:
        return NodeEstimatorResult(error=f"桥接异常: {e}")


@dataclass
class SimpleEstimator:
    star: float = 0.0
    column_count: int = 0
    ln_ratio: float = 0.0
    est_diff: str = ""
    numeric_difficulty: Optional[float] = None
    numeric_difficulty_hint: Optional[str] = None
    graph: Optional[dict] = None
    pattern_category: str = ""
    pattern_mode_tag: str = ""
    sv_amount: float = 0.0


@dataclass
class SimpleInterlude:
    overall: float = 0.0


@dataclass
class SimplePatterns:
    report: Optional[dict] = None


@dataclass
class SimpleAnalysis:
    estimator: SimpleEstimator = field(default_factory=SimpleEstimator)
    interlude: SimpleInterlude = field(default_factory=SimpleInterlude)
    patterns: SimplePatterns = field(default_factory=SimplePatterns)
    mode_tag: str = "Mix"
    errors: list = field(default_factory=list)
