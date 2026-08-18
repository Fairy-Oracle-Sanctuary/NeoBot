# -*- coding: utf-8 -*-
"""
群管理插件：/群管

群主/管理员可开启或关闭本群的部分功能开关，仅当前群生效。

当前可管理功能：
  - 视频解析（video_parse）：自动解析 B站/抖音/小红书/GitHub 等链接
  - 主动推送（push）：跨平台互通转发、入群提醒等机器人主动发送的消息

存储：Redis hash  `neobot:group:settings:{group_id}`，field=功能key，value="1"/"0"。
未设置一律视为开启（默认全开，管理员可关闭）。
"""
from neobot.core.managers.command_manager import matcher
from neobot.core.managers.redis_manager import redis_manager
from neobot.core.utils.logger import logger

# 无 __plugin_meta__：低调指令，不进 /help

# 功能开关定义（可扩展）：key -> 中文名
FEATURES = {
    "video_parse": "视频解析",
    "push": "主动推送",
}

# 功能别名 -> 功能 key（兼容 "视频解析"/"解析"/"链接解析" 等叫法）
FEATURE_ALIASES = {
    "视频解析": "video_parse",
    "解析": "video_parse",
    "链接解析": "video_parse",
    "主动推送": "push",
    "推送": "push",
    "互通": "push",
    "互通转发": "push",
}

ADMIN_ROLES = ("owner", "admin")

_SETTINGS_KEY_PREFIX = "neobot:group:settings:"


def _settings_key(group_id) -> str:
    return f"{_SETTINGS_KEY_PREFIX}{group_id}"


async def is_feature_enabled(group_id, feature: str) -> bool:
    """
    查询某群某功能是否开启（供其他插件调用）。

    未设置（键或字段不存在）视为开启；查询失败也保守地视为开启，避免误伤正常功能。
    """
    try:
        val = await redis_manager.redis.hget(_settings_key(group_id), feature)
    except Exception as e:
        logger.error(f"[群管] 查询群 {group_id} 功能 {feature} 失败: {type(e).__name__}: {e}")
        return True
    if val is None:
        return True
    return str(val) == "1"


async def _set_feature(group_id, feature: str, enabled: bool) -> None:
    try:
        await redis_manager.redis.hset(_settings_key(group_id), feature, "1" if enabled else "0")
    except Exception as e:
        logger.error(f"[群管] 写入群 {group_id} 功能 {feature} 失败: {type(e).__name__}: {e}")
        raise


async def _is_group_admin(bot, event) -> bool:
    """判断事件发送者是否为当前群的群主/管理员。"""
    group_id = getattr(event, "group_id", None)
    user_id = getattr(event, "user_id", None)
    if not group_id or not user_id:
        return False
    try:
        member = await bot.get_group_member_info(group_id, user_id, no_cache=True)
        return getattr(member, "role", "") in ADMIN_ROLES
    except Exception as e:
        logger.error(f"[群管] 查询成员角色失败: {type(e).__name__}: {e}")
        return False


async def _format_status(group_id) -> str:
    """构造当前群所有开关的状态文案。"""
    lines = [f"本群功能开关（群 {group_id}）："]
    for feature, name in FEATURES.items():
        state = "开启" if await is_feature_enabled(group_id, feature) else "关闭"
        lines.append(f"  {name}：{state}")
    lines.append("")
    lines.append("用法：/群管 查看 ｜ /群管 开/关 <功能名>")
    lines.append(f"可管理功能：{'、'.join(FEATURES.values())}")
    return "\n".join(lines)


def _parse_args(args):
    """
    解析 /群管 参数。

    返回 (action, feature_key) 或 (None, 错误信息)：
      /群管                     -> (None, None) 表示仅查看
      /群管 查看                -> (None, None) 表示仅查看
      /群管 开 视频解析          -> ("开", "video_parse")
      /群管 关闭 推送            -> ("关", "push")
      /群管 视频解析 开          -> ("开", "video_parse")（兼容顺序）
    """
    if not args:
        return None, None
    first = args[0]
    actions = ("开", "关", "开启", "关闭", "on", "off")
    if first in actions:
        # /群管 开 <功能>
        if len(args) < 2:
            return None, "格式：/群管 开 <功能> 或 /群管 关 <功能>"
        return first, args[1]
    # /群管 查看 或 /群管 <功能> 开
    if first in ("查看", "状态", "列表", "help", "帮助"):
        return None, None
    if len(args) >= 2 and args[1] in actions:
        return args[1], first
    return None, "格式：/群管 开 <功能> 或 /群管 关 <功能>"


@matcher.platform_command(["qq"], "群管", override_permission_check=True)
async def handle_group_manage(bot, event, args):
    """
    处理 /群管 指令。

    仅群聊内可用，且仅本群群主/管理员可触发（含查看）。
    用法：
      /群管            查看本群开关状态
      /群管 开 <功能>   开启功能
      /群管 关 <功能>   关闭功能
    """
    group_id = getattr(event, "group_id", None)
    if not group_id:
        await event.reply("该指令仅在群聊中可用。")
        return

    # 整个指令仅限本群群主/管理员（含查看）
    if not await _is_group_admin(bot, event):
        await event.reply("只有本群的群主/管理员才能使用 /群管。")
        return

    action, feature_arg = _parse_args(args)
    # _parse_args 的错误返回：action 为 None，feature_arg 携带错误文案
    if action is None and feature_arg is not None:
        await event.reply(feature_arg)
        return
    if action is None:
        await event.reply(await _format_status(group_id))
        return

    enabled = action in ("开", "开启", "on")
    feature = FEATURE_ALIASES.get(feature_arg, feature_arg) if feature_arg else ""
    if feature not in FEATURES:
        await event.reply(f"没有这个功能：{feature_arg}。可管理：{'、'.join(FEATURES.values())}")
        return

    try:
        await _set_feature(group_id, feature, enabled)
    except Exception:
        await event.reply("设置失败：Redis 暂不可用，请稍后重试。")
        return
    state = "开启" if enabled else "关闭"
    await event.reply(f"已将本群「{FEATURES[feature]}」{state}。")
    logger.info(f"[群管] 群 {group_id} 用户 {getattr(event, 'user_id', '?')} 将 {feature} 设为 {state}")
