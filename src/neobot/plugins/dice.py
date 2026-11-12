"""掷骰与简易 COC 检定。"""
from __future__ import annotations

import random
import re
from typing import List, Optional, Sequence, Tuple

from neobot.plugin_api import MessageEvent, ModuleLogger, define_plugin, global_config, platform_command

from .cooldown import Cooldown

logger = ModuleLogger("Dice")

plugin_manifest = define_plugin(
    name="dice",
    description="掷骰和简易 COC 检定",
    usage=(
        "/r 1d20（别名 /骰）- 掷骰，支持 2d6+3、1d20+2d4-1\n"
        "/coc <技能名> <数值> - COC 检定：大成功 / 极难 / 困难 / 成功 / 失败 / 大失败"
    ),
    version="0.1.0",
)

_DICE_PART = re.compile(r"^(\d*)d(\d+)$")
_cooldown = Cooldown()

Term = Tuple[str, ...]


class DiceParseError(ValueError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def parse_dice_expression(
    expr: str,
    max_dice: int = 100,
    max_faces: int = 1000,
    max_terms: int = 20,
) -> List[Term]:
    """
    解析掷骰表达式。

    骰子项为 ("dice", sign, count, faces)，修正项为 ("mod", sign, value)。
    sign 为 1 或 -1。
    """
    text = (
        (expr or "")
        .replace(" ", "")
        .replace("＋", "+")
        .replace("－", "-")
        .replace("—", "-")
        .lower()
    )
    if not text or not re.fullmatch(r"[0-9d+\-]+", text):
        raise DiceParseError("bad")
    parts = re.findall(r"[+-]?[^+-]+", text)
    if not parts or "".join(parts) != text:
        raise DiceParseError("bad")
    terms: List[Term] = []
    total_dice = 0
    for part in parts:
        sign = 1
        body = part
        if body[0] == "+":
            body = body[1:]
        elif body[0] == "-":
            sign = -1
            body = body[1:]
        if not body:
            raise DiceParseError("bad")
        dice = _DICE_PART.fullmatch(body)
        if dice:
            count = int(dice.group(1) or "1")
            faces = int(dice.group(2))
            if count <= 0 or faces <= 0:
                raise DiceParseError("bad")
            if faces > max_faces:
                raise DiceParseError("faces")
            if count > max_dice:
                raise DiceParseError("dice")
            total_dice += count
            if total_dice > max_dice:
                raise DiceParseError("dice")
            terms.append(("dice", sign, count, faces))
        elif body.isdigit():
            value = int(body)
            if value > 10000:
                raise DiceParseError("bad")
            terms.append(("mod", sign, value))
        else:
            raise DiceParseError("bad")
    if not terms or len(terms) > max_terms:
        raise DiceParseError("bad")
    if not any(term[0] == "dice" for term in terms):
        raise DiceParseError("bad")
    return terms


def roll_terms(terms: Sequence[Term], rng: Optional[random.Random] = None) -> Tuple[int, List[str]]:
    chooser = rng or random
    total = 0
    details: List[str] = []
    for term in terms:
        sign = int(term[1])
        prefix = "+" if sign > 0 else "-"
        if term[0] == "mod":
            value = int(term[2])
            total += sign * value
            details.append(f"{prefix}{value}")
            continue
        count = int(term[2])
        faces = int(term[3])
        rolls = [chooser.randint(1, faces) for _ in range(count)]
        subtotal = sum(rolls)
        total += sign * subtotal
        shown = "+".join(str(item) for item in rolls)
        details.append(f"{prefix}{count}d{faces}({shown})")
    return total, details


def format_roll(expr: str, total: int, details: Sequence[str]) -> str:
    compact = "".join(details)
    if compact.startswith("+"):
        compact = compact[1:]
    return f"掷骰 {expr}\n{compact}\n合计 {total}"


def coc_rank(roll: int, skill: int) -> str:
    """COC7：大成功优先于极难；技能不足 50 时 96–100 为大失败，否则仅 100。"""
    if not 1 <= roll <= 100:
        raise ValueError("roll")
    if not 0 <= skill <= 100:
        raise ValueError("skill")
    critical_max = 5 if skill >= 50 else 1
    if roll <= critical_max:
        return "大成功"
    fumble = roll == 100 if skill >= 50 else roll >= 96
    if fumble:
        return "大失败"
    if roll <= skill // 5:
        return "极难成功"
    if roll <= skill // 2:
        return "困难成功"
    if roll <= skill:
        return "成功"
    return "失败"


def format_coc(name: str, skill: int, roll: int, rank: str) -> str:
    return f"COC 检定 · {name} {skill}\n1d100 = {roll}\n{rank}"


def parse_coc_args(args: Sequence[str]) -> Tuple[str, int]:
    if len(args) < 2 or not str(args[-1]).isdigit():
        raise DiceParseError("usage")
    skill = int(args[-1])
    name = " ".join(args[:-1]).strip()
    if not name:
        raise DiceParseError("usage")
    if not 0 <= skill <= 100:
        raise DiceParseError("skill")
    return name, skill


def _limits() -> Tuple[int, int, float]:
    try:
        cfg = global_config.dice
        return int(cfg.max_dice), int(cfg.max_faces), float(cfg.cooldown_seconds)
    except Exception:
        return 100, 1000, 3.0


def _error_text(code: str, max_dice: int, max_faces: int) -> str:
    if code == "dice":
        return f"骰子太多啦，一次最多 {max_dice} 个。"
    if code == "faces":
        return f"面数太大啦，最多 {max_faces} 面。"
    if code == "skill":
        return "技能值要在 0 到 100 之间。"
    if code == "usage":
        return "用法：/coc 侦查 60"
    return "这个表达式我看不懂。例子：/r 2d6+3"


def _cooldown_key(event: MessageEvent) -> str:
    group_id = getattr(event, "group_id", None)
    if group_id:
        return f"group:{group_id}"
    return f"user:{getattr(event, 'user_id', 0)}"


@platform_command(["qq", "discord"], "r", "骰")
async def handle_roll(bot, event: MessageEvent, args: list):
    max_dice, max_faces, cooldown = _limits()
    if not _cooldown.allow(_cooldown_key(event), cooldown):
        await event.reply("骰子转得太快了，歇一会儿再掷。")
        return
    expr = "".join(args).strip()
    if not expr:
        await event.reply("用法：/r 1d20 或 /骰 2d6+3")
        return
    try:
        terms = parse_dice_expression(expr, max_dice=max_dice, max_faces=max_faces)
    except DiceParseError as exc:
        await event.reply(_error_text(exc.code, max_dice, max_faces))
        return
    total, details = roll_terms(terms)
    await event.reply(format_roll(expr, total, details))
    logger.debug(f"[Dice] roll user={getattr(event, 'user_id', '')} expr={expr} total={total}")


@platform_command(["qq", "discord"], "coc")
async def handle_coc(bot, event: MessageEvent, args: list):
    max_dice, max_faces, cooldown = _limits()
    if not _cooldown.allow(_cooldown_key(event), cooldown):
        await event.reply("骰子转得太快了，歇一会儿再掷。")
        return
    try:
        name, skill = parse_coc_args(args)
    except DiceParseError as exc:
        await event.reply(_error_text(exc.code, max_dice, max_faces))
        return
    roll = random.randint(1, 100)
    await event.reply(format_coc(name, skill, roll, coc_rank(roll, skill)))
