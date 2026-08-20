# -*- coding: utf-8 -*-
"""
MCC 插件层（2026-08-15 精简改造：假人操控转移到浏览器控制台）

neobot 对接 mcc-service，仅保留只读/凭证类能力：

1. /mcc 登录：签发网页登录密钥（POST /api/auth/issue，panel_token 鉴权，仅私聊）
2. /mcc agent <查询> 与 /ag <查询>：只读查询服务器状态（public 实例，POST /api/instances/public/agent）

假人操控（聊天/命令/传送/挂机/记忆/租赁等）全部在浏览器控制台 bot.wanfeng.cyou 完成，
QQ 内不再提供任何假人操控指令。
"""
from neobot.plugin_api import MccServiceClient, global_config, platform_command, ModuleLogger, define_plugin
from neobot.models import MessageEvent

logger = ModuleLogger("MccPlugin")

# 控制台地址
CONSOLE_URL = "https://bot.wanfeng.cyou"


async def _service_client() -> MccServiceClient:
    """
    返回共享的 mcc-service HTTP 客户端（单例，复用连接池）。
    通过 mcc_manager.get_client() 获取，避免每次调用新建 ClientSession 导致泄漏。
    """
    from neobot.plugin_api import mcc_manager
    return await mcc_manager.get_client()


plugin_manifest = define_plugin(
    name="mcc",
    description="MCC 插件层：/mcc 登录 签发密钥 + /mcc agent 与 /ag 只读查询。假人操控请移步浏览器控制台。",
    usage="/mcc 登录（私聊）：签发网页登录密钥\n"
        "/mcc agent <查询>（群聊/私聊）：只读查询服务器状态（public 实例）\n"
        "/ag <查询>：只读查询服务器状态（与 /mcc agent 相同）\n"
        "（假人操控请前往 https://bot.wanfeng.cyou 网页控制台）",
)


# ── 登录签发（内部复用，注册到 /mcc 登录）──────────────────────

async def _do_login(bot, event: MessageEvent, reason: str = "") -> None:
    """签发一次性登录密钥（原独立 /登录 逻辑，现由 /mcc 登录 调用）。"""
    if event.message_type != "private":
        await event.reply("❌ 登录仅支持私聊使用，请私聊机器人发送：/mcc 登录")
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
    if reason:
        reply = reason + "\n" + reply
    await event.reply(reply)



# ── /ag（只读，固定 public）──────────────────────────────────

@platform_command(["qq", "discord"], "ag")
async def handle_ag_command(bot, event: MessageEvent, args: list):
    """/ag <查询>：只读查询，固定 public 实例。"""
    task = " ".join(args).strip()
    if not task:
        await event.reply(
            "用法：/ag <要查询的内容>\n"
            "例如：/ag 看看服务器有多少人\n"
            "      /ag 服务器卡不卡\n"
            "（只读查询；操控假人请前往 https://bot.wanfeng.cyou 浏览器控制台）"
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



@platform_command(["qq", "discord"], "mcc")
async def handle_mcc_command(bot, event: MessageEvent, args: list):
    """
    /mcc 精简指令入口（2026-08-15 改造：假人操控移到浏览器控制台）：

    - /mcc 登录：签发网页登录密钥（原独立 /登录 逻辑）
    - /mcc agent <查询>：只读查询服务器状态（public 实例，与 /ag 相同）
    - 其他子命令一律提示去浏览器操作，不再提供 QQ 内假人操控。
    """
    sub0 = str(args[0]).strip() if args else ""
    sub0_lower = sub0.lower()

    # ── 登录：签发网页登录密钥 ─────────────────────────────
    if sub0_lower in ("登录", "login", "login_token"):
        await _do_login(bot, event)
        return

    # ── agent：只读查询（与 /ag 同一实现）──────────────────
    if sub0_lower in ("agent", "智能", "ai", "query", "查询"):
        rest_text = " ".join(args[1:]).strip()
        if not rest_text:
            await event.reply(
                "用法：/mcc agent <要查询的内容>\n"
                "例如：/mcc agent 看看服务器有多少人\n"
                "（只读查询；操控假人请前往 https://bot.wanfeng.cyou 网页控制台）"
            )
            return
        await event.reply("🤖 正在查询，请稍候…")
        caller = {
            "qq": str(getattr(event, "user_id", "") or ""),
            "group_id": str(getattr(event, "group_id", "") or ""),
        }
        try:
            from neobot.plugins.mcc_agent import run_mcc_agent
            reply = await run_mcc_agent(rest_text, caller=caller)
        except Exception as e:
            logger.error(f"MCC Agent 执行异常: {type(e).__name__}: {e}")
            reply = f"❌ Agent 执行异常：{type(e).__name__}: {e}"
        await event.reply(reply)
        return

    # ── 无参数 / help：简短帮助 ───────────────────────────
    if sub0_lower in ("help", "帮助", "用法", "?", "？"):
        await event.reply(plugin_manifest.usage)
        return
    if not sub0:
        await event.reply(
            "MCC 指令：\n"
            "/mcc 登录：签发网页登录密钥\n"
            "/mcc agent <查询>：只读查询服务器状态\n"
            "/ag <查询>：只读查询（同 /mcc agent）\n"
            "\n"
            "假人操控（聊天/命令/传送/挂机等）请前往浏览器控制台：\n"
            f"{CONSOLE_URL}"
        )
        return

    # ── 其他子命令：统一提示去浏览器 ──────────────────────
    await event.reply(
        f"❌ 已移除 QQ 内假人操控指令「{sub0}」。\n"
        "假人操作（聊天/命令/传送/挂机/记忆/租赁等）请前往浏览器控制台：\n"
        f"{CONSOLE_URL}\n"
        "\n"
        "仍可在 QQ 使用的：/mcc 登录、/mcc agent <查询>、/ag <查询>"
    )

