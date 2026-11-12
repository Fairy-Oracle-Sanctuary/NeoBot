"""被戳的时候回一句可爱的话。可用 /群管 关闭。"""
from __future__ import annotations

import random

from neobot.plugin_api import Bot, ModuleLogger, define_plugin, global_config, on_notice

from .cooldown import Cooldown

logger = ModuleLogger("PokeReply")

plugin_manifest = define_plugin(
    name="poke_reply",
    description="被戳一戳时回一句",
    usage="被戳到机器人时随机回一句。/群管 关 戳一戳 可在本群关闭。",
    version="0.1.0",
)

_LINES = (
    "耳朵抖了一下，你戳到我啦。",
    "尾巴甩甩，干嘛戳我。",
    "呜，爪垫被戳到了。",
    "在的在的，毛都蓬起来了。",
    "戳一下就好，再戳要害羞了。",
    "收到你的爪子，轻轻碰回去。",
    "被你找到啦。",
    "好痒，鼻子皱了一下。",
)

_cooldown = Cooldown()


def poke_line(rng: random.Random | None = None) -> str:
    chooser = rng or random
    return chooser.choice(_LINES)


def _settings() -> tuple[float, bool]:
    try:
        cfg = global_config.poke
        return float(cfg.cooldown_seconds), bool(cfg.poke_back)
    except Exception:
        return 20.0, False


@on_notice(notice_type="notify")
async def handle_poke(bot: Bot, event):
    if getattr(event, "sub_type", "") != "poke":
        return
    target = int(getattr(event, "target_id", 0) or 0)
    self_id = int(getattr(event, "self_id", 0) or getattr(bot, "self_id", 0) or 0)
    if not self_id or target != self_id:
        return
    group_id = int(getattr(event, "group_id", 0) or 0)
    user_id = int(getattr(event, "user_id", 0) or 0)
    if group_id:
        from neobot.plugins.group_manage import is_feature_enabled

        if not await is_feature_enabled(group_id, "poke"):
            return
    cooldown, poke_back = _settings()
    key = f"group:{group_id}" if group_id else f"user:{user_id}"
    if not _cooldown.allow(key, cooldown):
        return
    try:
        await bot.send(event, poke_line())
    except Exception as exc:
        logger.error(f"[戳一戳] 回复失败: {type(exc).__name__}: {exc}")
        return
    if poke_back and user_id:
        try:
            if group_id:
                await bot.group_poke(group_id, user_id)
            else:
                await bot.friend_poke(user_id)
        except Exception as exc:
            logger.warning(f"[戳一戳] 回戳失败: {type(exc).__name__}: {exc}")
