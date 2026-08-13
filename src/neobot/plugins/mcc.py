# -*- coding: utf-8 -*-
"""
MCC 插件层（纯转发，按 neobot-integration.md 改造）

neobot 对接 mcc-service，提供三类能力：

1. 私聊"登录"：签发网页登录密钥（POST /api/auth/issue，panel_token 鉴权）
2. 群聊 /ag <查询>：只读 agent，固定 public 实例（POST /api/instances/public/agent，auth_token 鉴权）
3. 群聊/私聊 /mcc <子指令>：操控该 QQ 绑定的假人
   - GET  /api/mcc/instances?qq=<qq>   列出可管理假人 + 当前选中
   - POST /api/mcc/select               切换当前假人
   - POST /api/mcc/exec                 执行子命令（mcc-service 返回 text/reply/message）

选中状态存 mcc-service 端 Redis，neobot 不再维护本地状态。
"""
from typing import Any, Dict, List, Optional

from neobot.adapters.mcc_adapter.service_client import MccServiceClient
from neobot.core.config_loader import global_config
from neobot.core.managers.command_manager import matcher
from neobot.core.utils.logger import ModuleLogger
from neobot.models import MessageEvent

logger = ModuleLogger("MccPlugin")

# 控制台地址
CONSOLE_URL = "https://bot.wanfeng.cyou"

# agent 子命令可能较慢，单独放大超时（毫秒）
_AGENT_TIMEOUT_MS = 60000

# 需要放大超时的子指令
_SLOW_SUBS = {"agent", "智能"}


async def _service_client() -> MccServiceClient:
    """
    返回共享的 mcc-service HTTP 客户端（单例，复用连接池）。
    通过 mcc_manager.get_client() 获取，避免每次调用新建 ClientSession 导致泄漏。
    """
    from neobot.adapters.mcc_adapter import mcc_manager
    return await mcc_manager.get_client()


__plugin_meta__ = {
    "name": "mcc",
    "description": "MCC 插件层：/登录 签发密钥 + /ag 只读查询 + /mcc 操控绑定实例",
    "usage": (
        "/登录（私聊）：签发网页登录密钥\n"
        "/ag <查询>（群聊）：只读查询服务器状态（public 实例）\n"
        "/mcc 切换实例 [序号|名称]：切换当前操作的假人（默认 1）\n"
        "/mcc 状态 | 聊天 <文本> | 命令 <命令> | 会话 | 服务器 | 玩家 | 历史 [n] | 事件 [n] | 性能 | 挂机 | agent <需求> | 记忆\n"
        "（/mcc 仅能管理该 QQ 绑定的实例）"
    ),
}


# ── /登录 ────────────────────────────────────────────────────

@matcher.platform_command(["qq"], "登录")
async def handle_login_command(bot, event: MessageEvent, args: list):
    """私聊"登录"：签发一次性登录密钥（POST /api/auth/issue，panel_token 鉴权）。"""
    if event.message_type != "private":
        await event.reply("❌ 该指令仅支持私聊使用，请私聊机器人发送：/登录")
        return

    if args:
        await event.reply("用法：/登录（无需参数）\n私聊发送 /登录 即可签发网页登录密钥。")
        return

    qq = str(getattr(event, "user_id", ""))
    if not qq:
        await event.reply("❌ 无法识别你的 QQ 号，请重试。")
        return

    cfg = global_config.mcc_adapter
    if not cfg.panel_token:
        logger.error("mcc_adapter.panel_token 未配置，无法调用 /api/auth/issue")
        await event.reply("❌ 服务未配置面板密钥（panel_token），请联系管理员。")
        return

    try:
        client = await _service_client()
        data = await client.issue_login_token(qq)
    except Exception as e:
        logger.error(f"issue_login_token 异常: {type(e).__name__}: {e}")
        await event.reply(f"❌ 登录服务不可用：{type(e).__name__}: {e}")
        return

    if not isinstance(data, dict):
        await event.reply("❌ 登录服务返回异常")
        return

    if not data.get("success"):
        await event.reply(f"❌ 签发失败：{data.get('message') or '未知原因'}")
        return

    login_token = data.get("login_token") or ""
    expires_in = data.get("expires_in") or 0
    try:
        minutes = int(expires_in) // 60
    except (TypeError, ValueError):
        minutes = 0

    reply = (
        "✅ 登录密钥已签发\n"
        f"登录密钥：{login_token}\n"
        f"有效期：{minutes} 分钟\n"
        f"请前往 {CONSOLE_URL} 输入此密钥完成登录"
    )
    await event.reply(reply)


# ── /ag（只读，固定 public）──────────────────────────────────

@matcher.platform_command(["qq", "discord"], "ag")
async def handle_ag_command(bot, event: MessageEvent, args: list):
    """/ag <查询>：只读查询，固定 public 实例。"""
    task = " ".join(args).strip()
    if not task:
        await event.reply(
            "用法：/ag <要查询的内容>\n"
            "例如：/ag 看看服务器有多少人\n"
            "      /ag 服务器卡不卡\n"
            "（只读查询；操作自己的假人请用 /mcc）"
        )
        return

    await event.reply("🤖 正在查询，请稍候…")
    caller = {
        "qq": str(getattr(event, "user_id", "") or ""),
        "group_id": str(getattr(event, "group_id", "") or ""),
    }
    sender = getattr(event, "sender", None)
    if sender is not None:
        try:
            if isinstance(sender, dict):
                name = sender.get("nickname") or sender.get("card")
            else:
                name = getattr(sender, "nickname", None)
            if name:
                caller["name"] = name
        except Exception:
            pass

    try:
        from neobot.plugins.mcc_agent import run_mcc_agent
        reply = await run_mcc_agent(task, caller=caller)
    except Exception as e:
        logger.error(f"MCC Agent 执行异常: {type(e).__name__}: {e}")
        reply = f"❌ Agent 执行异常：{type(e).__name__}: {e}"
    await event.reply(reply)


# ── /mcc（纯转发到 mcc-service）──────────────────────────────

def _extract_reply(data: Dict[str, Any], cmd: str = "") -> str:
    """从 mcc-service 响应提取回显文本，按 cmd 分发到专用格式化。"""
    if not isinstance(data, dict):
        return str(data)
    if not data.get("success", True):
        return f"❌ {data.get('message') or '操作失败'}"

    # 1) 优先顶层文本字段（标记/区域/挂机/agent 等）
    for key in ("text", "reply"):
        val = data.get(key)
        if isinstance(val, str) and val:
            return val

    # 2) 顶层 message（切换实例/申请挂机/释放/记忆保存/清空动态 等）
    message = data.get("message")
    if isinstance(message, str) and message:
        # 切换实例补充运行状态提示
        if cmd == "切换实例" and data.get("running") is False:
            message += "\n⚠️ 该假人当前未运行，可能需要先启动"
        return message

    # 3) 按 cmd 格式化 data 字段
    inner = data.get("data")
    fmt = _FORMATTERS.get(cmd)
    if fmt is not None:
        try:
            return fmt(inner, data)
        except Exception as e:
            logger.warning(f"格式化 {cmd} 响应失败：{e}，回退 JSON")
            return _compact_json(data)

    # 4) 记忆查看/租赁状态 等顶层结构化字段
    if cmd == "记忆":
        return _fmt_memory_view(data)
    if cmd == "租赁状态":
        return _fmt_rental_status(data)

    # 5) 兜底
    return _compact_json(data)


def _compact_json(data: Any) -> str:
    """结构化响应的紧凑回显（截断过长内容）。"""
    import json
    try:
        text = json.dumps(data, ensure_ascii=False)
    except Exception:
        text = str(data)
    if len(text) > 800:
        text = text[:800] + "…"
    return text


# ── 各子命令的 data 字段格式化 ────────────────────────────────

def _fmt_session(data: Any, full: Dict[str, Any]) -> str:
    """状态/会话：MCC 原样 session_status。"""
    if not isinstance(data, dict):
        return _compact_json(data)
    connected = data.get("connected")
    user = data.get("username") or data.get("user") or "?"
    host = data.get("serverHost") or data.get("host") or "?"
    port = data.get("serverPort") or data.get("port") or 25565
    head = f"{'🟢 已连接' if connected else '🔴 未连接'} {user} @ {host}:{port}"
    # 其他字段紧凑展示
    extras = []
    for k, v in data.items():
        if k in ("connected", "username", "user", "serverHost", "host", "serverPort", "port"):
            continue
        if v is None or v == "":
            continue
        extras.append(f"{k}: {v}")
    body = "\n".join(extras)
    return head + (f"\n{body}" if body else "")


def _fmt_command_result(data: Any, full: Dict[str, Any]) -> str:
    """命令：data.result 为 MCC 命令输出。"""
    if isinstance(data, dict):
        result = data.get("result")
        if isinstance(result, str) and result:
            return result if len(result) <= 1500 else result[:1500] + "…"
    return _compact_json(data)


def _fmt_chat_sent(data: Any, full: Dict[str, Any]) -> str:
    """聊天：data.sent。"""
    return "✅ 聊天已发送"


def _fmt_server(data: Any, full: Dict[str, Any]) -> str:
    """服务器：MCC 原样。"""
    if not isinstance(data, dict):
        return _compact_json(data)
    lines = []
    for k, v in data.items():
        if v is None or v == "":
            continue
        lines.append(f"{k}: {v}")
    return "\n".join(lines) if lines else "（无服务器信息）"


def _fmt_players(data: Any, full: Dict[str, Any]) -> str:
    """玩家：data.players 列表。"""
    if not isinstance(data, dict):
        return _compact_json(data)
    players = data.get("players") or []
    if not players:
        return "当前没有在线玩家"
    names = [p.get("name", "?") if isinstance(p, dict) else str(p) for p in players]
    return f"在线玩家（{len(names)}）：\n" + "、".join(names)


def _fmt_perf(data: Any, full: Dict[str, Any]) -> str:
    """性能：多种来源。"""
    if not isinstance(data, dict):
        return _compact_json(data)
    # 来源 1：实时地图文本
    if isinstance(data.get("text"), str):
        return data["text"]
    # 来源 2：tps/mspt 数值
    tps = data.get("tps")
    mspt = data.get("mspt")
    mspt_err = data.get("mspt_error")
    parts = []
    if tps is not None:
        parts.append(f"TPS {tps}")
    if mspt is not None:
        parts.append(f"MSPT {mspt}ms")
    if mspt_err:
        parts.append(f"MSPT: {mspt_err}")
    return " / ".join(parts) if parts else _compact_json(data)


def _fmt_history(data: Any, full: Dict[str, Any]) -> str:
    """历史：data.entries。"""
    if not isinstance(data, dict):
        return _compact_json(data)
    entries = data.get("entries") or []
    if not entries:
        return "（无聊天记录）"
    lines = []
    for e in entries[-50:]:
        if not isinstance(e, dict):
            lines.append(str(e))
            continue
        kind = e.get("kind", "")
        text = e.get("text", "")
        ts = e.get("timestampUtc") or e.get("timestamp") or ""
        time_str = ""
        if ts:
            try:
                import datetime
                t = datetime.datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
                time_str = t.strftime("%H:%M ")
            except Exception:
                pass
        prefix = {"chat": "", "system": "[系统] ", "leave": "[离开] ", "join": "[加入] "}.get(kind, f"[{kind}] ")
        lines.append(f"{time_str}{prefix}{text}")
    return "\n".join(lines)


def _fmt_events(data: Any, full: Dict[str, Any]) -> str:
    """事件：data.events。"""
    if not isinstance(data, dict):
        return _compact_json(data)
    events = data.get("events") or []
    if not events:
        return "（无事件记录）"
    lines = []
    for e in events[-50:]:
        if not isinstance(e, dict):
            lines.append(str(e))
            continue
        etype = e.get("type", "?")
        ts = e.get("timestampUtc") or e.get("timestamp") or ""
        time_str = ""
        if ts:
            try:
                import datetime
                t = datetime.datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
                time_str = t.strftime("%H:%M ")
            except Exception:
                pass
        edata = e.get("data")
        detail = ""
        if isinstance(edata, dict):
            detail = " ".join(f"{k}={v}" for k, v in edata.items())
        elif edata:
            detail = str(edata)
        lines.append(f"{time_str}[{etype}] {detail}".rstrip())
    return "\n".join(lines)


def _fmt_memory_view(data: Dict[str, Any]) -> str:
    """记忆 查看：server_memory + facts。"""
    server_mem = data.get("server_memory") or ""
    facts = data.get("facts") or []
    lines = []
    if server_mem:
        lines.append("【服务器记忆】")
        lines.append(str(server_mem))
    if facts:
        lines.append(f"\n【已保存记忆（{len(facts)} 条）】")
        for f in facts:
            if not isinstance(f, dict):
                lines.append(str(f))
                continue
            topic = f.get("topic", "通用")
            content = f.get("content", "")
            t = f.get("time")
            time_str = ""
            if t:
                try:
                    import datetime
                    time_str = datetime.datetime.fromtimestamp(float(t)).strftime("%m-%d %H:%M ")
                except Exception:
                    pass
            lines.append(f"[{topic}] {time_str}{content}")
    if not lines:
        return "（暂无记忆）"
    return "\n".join(lines)


def _fmt_rental_status(data: Dict[str, Any]) -> str:
    """租赁状态：rental + rentals。"""
    rentals = data.get("rentals") or []
    rental = data.get("rental")
    if not rentals and not rental:
        return "你当前没有借用假人"
    items = rentals if rentals else ([rental] if rental else [])
    lines = [f"当前借用（{len(items)} 个）："]
    for r in items:
        if not isinstance(r, dict):
            lines.append(str(r))
            continue
        bot = r.get("bot") or r.get("instance_name") or "?"
        qq = r.get("qq", "")
        game = r.get("game_name") or ""
        exp = r.get("expires_at")
        time_str = ""
        if exp:
            try:
                import datetime
                remain = float(exp) - datetime.datetime.now().timestamp()
                if remain > 0:
                    mins = int(remain // 60)
                    time_str = f" 剩余 {mins} 分钟"
                else:
                    time_str = " 已过期"
            except Exception:
                pass
        lines.append(f"  {bot}（{game}）{time_str}".rstrip())
    return "\n".join(lines)


# cmd → data 字段格式化函数
_FORMATTERS = {
    "状态": _fmt_session,
    "会话": _fmt_session,
    "命令": _fmt_command_result,
    "聊天": _fmt_chat_sent,
    "服务器": _fmt_server,
    "玩家": _fmt_players,
    "性能": _fmt_perf,
    "历史": _fmt_history,
    "事件": _fmt_events,
}


async def _format_instances(data: Dict[str, Any]) -> str:
    """格式化 GET /api/mcc/instances 的响应为列表展示。"""
    if not data.get("success"):
        msg = data.get("message") or "查询失败"
        if "没有" in msg or "无" in msg:
            return f"你当前没有可管理的假人。\n请先私聊 /登录 获取密钥，在网页登录并租用假人后再使用 /mcc。"
        return f"❌ {msg}"

    instances = data.get("instances") or []
    if not instances:
        return (
            "你当前没有可管理的假人。\n"
            "请先私聊 /登录 获取密钥，在网页登录并租用假人后再使用 /mcc。"
        )

    current = data.get("current")
    lines = [f"🎮 可管理的假人（{len(instances)} 个）："]
    for i, inst in enumerate(instances, 1):
        name = inst.get("name", "?")
        display = inst.get("display") or name
        running = "在线" if inst.get("running") else "离线"
        kind = "私有" if inst.get("private") else "租赁"
        mark = " ★" if inst.get("current") or name == current else ""
        line = f"{i}. {display}（{kind}/{running}）{mark}"
        # 租赁到期时间
        expires = inst.get("expires_at")
        if expires:
            import datetime
            try:
                t = datetime.datetime.fromtimestamp(float(expires))
                line += f"  到期 {t:%m-%d %H:%M}"
            except (TypeError, ValueError, OSError):
                pass
        lines.append(line)
    if current:
        lines.append(f"当前选中：{current}")
    else:
        lines.append("提示：/mcc 切换实例 <序号> 选择假人")
    return "\n".join(lines)


@matcher.platform_command(["qq", "discord"], "mcc")
async def handle_mcc_command(bot, event: MessageEvent, args: list):
    """
    /mcc 指令入口：纯转发到 mcc-service。

    - 无参数或 help：GET /api/mcc/instances 展示列表
    - 切换实例：POST /api/mcc/select（或 mcc_exec cmd=切换实例）
    - 其他子命令：POST /api/mcc/exec 转发
    """
    qq = str(getattr(event, "user_id", "") or "")
    if not qq:
        await event.reply("❌ 无法识别你的 QQ 号。")
        return

    sub0 = str(args[0]).strip() if args else ""
    sub0_lower = sub0.lower()

    # ── 无参数：展示可管理假人列表 ──────────────────────────
    if not sub0:
        try:
            client = await _service_client()
            data = await client.mcc_instances(qq)
        except Exception as e:
            logger.error(f"mcc_instances 异常: {type(e).__name__}: {e}")
            await event.reply(f"❌ 查询实例列表失败：{type(e).__name__}: {e}")
            return
        await event.reply(await _format_instances(data))
        return

    # ── help ───────────────────────────────────────────────
    if sub0_lower in ("help", "帮助", "用法", "?", "？"):
        await event.reply(
            "MCC 指令用法：\n"
            "/mcc：查看可管理的假人列表\n"
            "/mcc 切换实例 [序号|名称]：切换当前操作的假人（默认 1）\n"
            "/mcc 状态：查看当前实例与连接状态\n"
            "/mcc 聊天 <文本>：在服务器发送一条聊天\n"
            "/mcc 命令 <MCC内部命令>：执行 MCC 内部命令（如 respawn）\n"
            "/mcc 会话 | 服务器 | 玩家 | 性能：查询服务器状态\n"
            "/mcc 历史 [n] | 事件 [n]：查询聊天记录/事件\n"
            "/mcc 标记 [关键词] | 区域：查询实时地图标记/区域\n"
            "/mcc 挂机 [组名|挂机点]：查看挂机点菜单或传送\n"
            "/mcc agent <需求>：自然语言操控当前实例\n"
            "/mcc 记忆 查看 | 保存 <内容> | 清空动态：管理长期记忆（管理员）\n"
            "/mcc 申请挂机 | 租赁状态 | 释放：租赁相关\n"
            "\n"
            "提示：/mcc 仅能管理该 QQ 绑定的实例；先用 /mcc 切换实例 选择假人"
        )
        return

    rest_args = args[1:] if len(args) > 1 else []
    rest_text = " ".join(rest_args).strip()

    # ── 切换实例：走 select 接口（更高效）─────────────────
    if sub0 in ("切换实例", "实例", "instance", "instances", "切换", "switch"):
        try:
            client = await _service_client()
            if not rest_text:
                # 无参数：展示列表
                data = await client.mcc_instances(qq)
                await event.reply(await _format_instances(data))
                return

            if rest_text.isdigit():
                data = await client.mcc_select(qq, index=int(rest_text))
            else:
                data = await client.mcc_select(qq, name=rest_text)
        except Exception as e:
            logger.error(f"mcc_select 异常: {type(e).__name__}: {e}")
            await event.reply(f"❌ 切换实例失败：{type(e).__name__}: {e}")
            return
        await event.reply(_extract_reply(data, cmd="切换实例"))
        return

    # ── 其余子命令：统一走 mcc_exec 转发 ───────────────────
    # 子命令名映射（中英文 → 中文 cmd）
    cmd_map = {
        # 状态类
        "状态": "状态", "status": "状态", "info": "状态", "session": "会话", "会话": "会话",
        # 操作类
        "聊天": "聊天", "chat": "聊天", "say": "聊天",
        "命令": "命令", "command": "命令", "cmd": "命令",
        # 查询类
        "服务器": "服务器", "server": "服务器",
        "玩家": "玩家", "players": "玩家", "list": "玩家",
        "性能": "性能", "tps": "性能", "mspt": "性能", "perf": "性能",
        "历史": "历史", "history": "历史", "chatlog": "历史",
        "事件": "事件", "events": "事件",
        "标记": "标记", "marker": "标记", "markers": "标记", "地标": "标记",
        "区域": "区域", "region": "区域", "regions": "区域",
        # 挂机
        "挂机": "挂机", "afk": "挂机", "menu": "挂机",
        # agent
        "agent": "agent", "智能": "agent",
        # 记忆
        "记忆": "记忆", "memory": "记忆", "记住": "记忆",
        # 租赁
        "申请挂机": "申请挂机", "申请": "申请挂机",
        "租赁状态": "租赁状态", "挂机查询": "租赁状态", "租借状态": "租赁状态", "借用查询": "租赁状态",
        "释放": "释放",
    }

    cmd = cmd_map.get(sub0_lower) or cmd_map.get(sub0)
    if cmd is None:
        await event.reply(
            f"未知子命令：{sub0}\n"
            "发送 /mcc help 查看完整用法"
        )
        return

    # agent 提示"思考中..."
    if cmd == "agent":
        await event.reply("🤖 正在理解并执行，请稍候…")

    # 组装请求
    timeout_ms = _AGENT_TIMEOUT_MS if cmd in _SLOW_SUBS else None

    # 特殊处理具名字段（按文档映射表）
    fields: Dict[str, Any] = {}
    exec_args: Optional[list] = None

    if cmd == "聊天" and rest_text:
        fields["text"] = rest_text
    elif cmd == "命令" and rest_text:
        fields["command"] = rest_text.lstrip("/")
    elif cmd == "agent" and rest_text:
        fields["task"] = rest_text
    elif cmd == "记忆":
        # /mcc 记忆 查看 | 保存 <内容> | 清空动态
        if rest_text:
            sub_parts = rest_text.split(maxsplit=1)
            exec_args = [sub_parts[0]]
            # 写操作（保存/清空动态）仅限管理员，防止任意用户篡改长期记忆
            if sub_parts[0] in ("保存", "set", "写入", "清空动态", "clear", "清除"):
                from neobot.core.managers.permission_manager import permission_manager
                from neobot.core.permission import Permission
                if not await permission_manager.check_permission(event.user_id, Permission.ADMIN):
                    await event.reply("权限不足：/mcc 记忆 保存/清空动态 仅限管理员使用。")
                    return
                if sub_parts[0] in ("保存", "set", "写入") and len(sub_parts) > 1:
                    fields["content"] = sub_parts[1]
        else:
            exec_args = ["查看"]
    elif cmd == "申请挂机" and rest_text:
        fields["game_name"] = rest_text
    elif rest_text and cmd in ("历史", "事件", "标记", "挂机"):
        # 这些命令的位置参数是 args[0]
        exec_args = [rest_text]

    try:
        client = await _service_client()
        data = await client.mcc_exec(
            qq=qq,
            cmd=cmd,
            args=exec_args,
            timeout_ms=timeout_ms,
            **fields,
        )
    except Exception as e:
        logger.error(f"mcc_exec({cmd}) 异常: {type(e).__name__}: {e}")
        await event.reply(f"❌ 执行失败：{type(e).__name__}: {e}")
        return

    await event.reply(_extract_reply(data, cmd=cmd))
