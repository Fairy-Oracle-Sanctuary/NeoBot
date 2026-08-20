# -*- coding: utf-8 -*-
"""
MCC Agent 转发层：Agent 逻辑（DeepSeek 循环、工具、对话上下文压缩）
已迁移到独立程序 mcc-service，neobot 只把任务转发过去。

按 neobot-integration.md 约定：agent 只读、仅绑定 public 实例。
"""
from typing import Optional
from neobot.plugin_api import McpAdapter, McpError, mcc_manager, ModuleLogger
logger = ModuleLogger("MccAgent")

# agent 只读、仅绑定 public 实例（mcc-service 端保证只读权限）
PUBLIC_INSTANCE = "public"


async def run_mcc_agent(task: str, adapter: Optional[McpAdapter] = None, caller: Optional[dict] = None) -> str:
    """
    转发 agent 任务到 mcc-service 的 public 实例，返回最终回复。

    Args:
        task: 自然语言查询（只读）
        adapter: 兼容旧签名，已忽略——固定使用 public 实例
        caller: 调用者信息（qq / group_id / name）
    """
    task = task.strip()
    if not task:
        return "❌ 请描述你要查询的内容，例如：/ag 看看服务器有多少人"

    public = await mcc_manager.get_by_name(PUBLIC_INSTANCE)
    if public is None:
        return "❌ 没有可用的 public 实例（mcc-service 未启动或未配置 public 实例）"

    try:
        return await public.agent(task, caller=caller)
    except McpError as e:
        logger.error(f"MCC Agent 转发失败: {type(e).__name__}: {e}")
        return f"❌ Agent 服务不可用：{type(e).__name__}: {e}"
    except Exception as e:
        logger.error(f"MCC Agent 转发异常: {type(e).__name__}: {e}")
        return f"❌ Agent 执行异常：{type(e).__name__}: {e}"
