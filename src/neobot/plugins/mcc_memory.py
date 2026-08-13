# -*- coding: utf-8 -*-
"""
MCC Agent 长期记忆

- 服务器长期记忆：服务器资料/wiki 知识（静态，由管理员维护）
- 动态记忆：Agent 在交互中学到的事实（玩家信息、组织、常用传送等）

存储使用 Redis（neobot 自带 redis_manager），key 前缀 neobot:mcc_agent:。
"""
import json
from typing import Any, Dict, List, Optional

from neobot.core.managers.redis_manager import redis_manager
from neobot.core.utils.logger import ModuleLogger

logger = ModuleLogger("MccMemory")

SERVER_MEMORY_KEY = "neobot:mcc_agent:server_memory"
FACTS_KEY = "neobot:mcc_agent:facts"

# 注入 prompt 时的长度上限（字符）
SERVER_MEMORY_MAX_CHARS = 6000
FACTS_MAX_CHARS = 2000
# 动态记忆条数上限
MAX_FACTS = 100


async def load_server_memory() -> str:
    """读取服务器长期记忆（wiki/服务器资料）。"""
    try:
        value = await redis_manager.get(SERVER_MEMORY_KEY)
        return value or ""
    except Exception as e:
        logger.debug(f"读取服务器记忆失败: {type(e).__name__}: {e}")
        return ""


async def save_server_memory(text: str) -> bool:
    """写入服务器长期记忆（覆盖）。"""
    try:
        await redis_manager.set(SERVER_MEMORY_KEY, text)
        logger.info(f"服务器长期记忆已更新（{len(text)} 字符）")
        return True
    except Exception as e:
        logger.error(f"保存服务器记忆失败: {type(e).__name__}: {e}")
        return False


async def load_facts() -> List[Dict[str, Any]]:
    """读取动态记忆（Agent 学到的实事列表）。"""
    try:
        value = await redis_manager.get(FACTS_KEY)
        if not value:
            return []
        parsed = json.loads(value)
        return parsed if isinstance(parsed, list) else []
    except Exception as e:
        logger.debug(f"读取动态记忆失败: {type(e).__name__}: {e}")
        return []


async def add_fact(topic: str, content: str) -> str:
    """
    添加一条动态记忆。topic 为空时自动取内容前 12 字作为主题。
    超过条数上限时丢弃最旧的一条。
    """
    topic = (topic or "").strip()
    content = (content or "").strip()
    if not content:
        return "内容为空，未保存"
    if not topic:
        topic = content[:12]
    facts = await load_facts()
    facts.append({"topic": topic, "content": content})
    if len(facts) > MAX_FACTS:
        facts = facts[-MAX_FACTS:]
    try:
        await redis_manager.set(FACTS_KEY, json.dumps(facts, ensure_ascii=False))
        return f"已记住：{topic}：{content}"
    except Exception as e:
        return f"保存失败：{type(e).__name__}: {e}"


async def clear_facts() -> str:
    """清空动态记忆。"""
    try:
        await redis_manager.set(FACTS_KEY, "[]")
        return "动态记忆已清空"
    except Exception as e:
        return f"清空失败：{type(e).__name__}: {e}"


async def memory_prompt_block() -> str:
    """组装注入 system prompt 的记忆文本（服务器记忆 + 动态记忆）。"""
    parts: List[str] = []
    server_memory = await load_server_memory()
    if server_memory:
        parts.append("【服务器长期记忆】\n" + server_memory[:SERVER_MEMORY_MAX_CHARS])
    facts = await load_facts()
    if facts:
        lines = []
        total = 0
        for f in facts:
            line = f"- {f.get('topic')}：{f.get('content')}"
            total += len(line)
            if total > FACTS_MAX_CHARS:
                break
            lines.append(line)
        parts.append("【动态记忆】\n" + "\n".join(lines))
    if not parts:
        return ""
    return "\n\n".join(parts)
