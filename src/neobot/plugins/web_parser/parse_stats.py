# -*- coding: utf-8 -*-
"""
解析耗时统计与超时告警（B站/推特/抖音/小红书等解析器共用）。

- 记录每次解析耗时到 Redis List（`neobot:stats:parse_cost:<parser>`，限长 50）
- 计算最近 N 次平均耗时
- 单次解析超过 1s 时私聊提醒开发者（带冷却，避免刷屏）
- 所有 Redis/发送失败静默降级，绝不影响解析主流程
"""
import time
from typing import Optional

from neobot.plugin_api import redis_manager, bot_manager, logger

# 开发者 QQ（与 wanfeng_review.py 保持一致）
ADMIN_QQ = 2221577113
# 单次解析超时阈值（毫秒），超过则告警
SLOW_THRESHOLD_MS = 1000
# Redis 保留最近样本数
MAX_SAMPLES = 50
# 同解析器告警冷却（秒），防止高频解析时刷屏
ALERT_COOLDOWN_SECONDS = 300
# 当前告警冷却状态：parser -> 上次告警时间戳
_alert_cooldowns: dict = {}

# 内存缓存：parser -> [耗时ms...]，Redis 不可用时降级到内存统计
_mem_samples: dict = {}
_mem_mode = False


def _redis_key(parser: str) -> str:
    return f"neobot:stats:parse_cost:{parser}"


async def _record_redis(parser: str, cost_ms: int) -> None:
    """写 Redis（限长 List，LPUSH + 裁剪）。"""
    r = redis_manager.redis
    if r is None:
        raise ConnectionError("Redis 未初始化")
    key = _redis_key(parser)
    await r.lpush(key, str(cost_ms))
    await r.ltrim(key, 0, MAX_SAMPLES - 1)


async def record_parse(parser: str, cost_ms: float) -> None:
    """
    记录一次解析耗时并触发超时告警。

    Args:
        parser: 解析器名（bili / douyin / xhs / github / twitter）
        cost_ms: 本次解析耗时（毫秒）
    """
    global _mem_mode
    cost = int(cost_ms)
    parser = parser or "unknown"

    try:
        await _record_redis(parser, cost)
    except Exception as e:
        # Redis 不可用 → 降级内存统计
        _mem_mode = True
        samples = _mem_samples.setdefault(parser, [])
        samples.append(cost)
        if len(samples) > MAX_SAMPLES:
            del samples[: len(samples) - MAX_SAMPLES]
        logger.debug(f"[ParseStats] Redis 不可用，降级内存统计: {type(e).__name__}")

    if cost > SLOW_THRESHOLD_MS:
        await _alert_slow(parser, cost)


async def average_parse(parser: str) -> Optional[float]:
    """
    计算某解析器最近解析的平均耗时（毫秒）。

    Returns:
        平均毫秒数；无样本返回 None。
    """
    try:
        r = redis_manager.redis
        if r is None:
            raise ConnectionError("Redis 未初始化")
        values = await r.lrange(_redis_key(parser), 0, MAX_SAMPLES - 1)
        if not values:
            return None
        total = sum(int(v) for v in values)
        return total / len(values)
    except Exception:
        # 降级：内存样本
        samples = _mem_samples.get(parser, [])
        if not samples:
            return None
        return sum(samples) / len(samples)


async def _alert_slow(parser: str, cost_ms: int) -> None:
    """单次解析超过 1s 时私聊提醒开发者（带冷却，仅发送成功才消耗冷却）。"""
    now = time.monotonic()
    last = _alert_cooldowns.get(parser, 0.0)
    if now - last < ALERT_COOLDOWN_SECONDS:
        return

    try:
        bots = bot_manager.get_all_bots()
        if not bots:
            return
        avg = await average_parse(parser)
        avg_str = f"{avg:.0f}ms" if avg is not None else "暂无"
        sent = False
        for bot in bots:
            try:
                await bot.send_private_msg(
                    ADMIN_QQ,
                    f"⚠️ 解析偏慢提醒\n"
                    f"解析器：{parser}\n"
                    f"本次耗时：{cost_ms}ms（>1000ms）\n"
                    f"最近平均：{avg_str}",
                )
                sent = True
                break
            except Exception:
                continue
        if sent:
            # 仅发送成功才记录冷却；失败则下次继续尝试
            _alert_cooldowns[parser] = now
            logger.info(f"[ParseStats] 已提醒开发者：{parser} 解析 {cost_ms}ms")
    except Exception as e:
        logger.debug(f"[ParseStats] 告警发送失败（静默）: {type(e).__name__}: {e}")


def fmt_cost(cost_ms: float) -> str:
    """耗时格式化：>=1s 显示 x.xs，否则显示 xms。"""
    if cost_ms >= 1000:
        return f"{cost_ms / 1000:.1f}s"
    return f"{int(cost_ms)}ms"
