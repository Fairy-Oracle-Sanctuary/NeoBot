# -*- coding: utf-8 -*-
"""
MCC 服务器内监听：让 Agent 与游戏内玩家双向互动

后台轮询 MCC 聊天历史，当游戏内玩家聊天中提到机器人（触发词）时，
调用 MCC Agent 理解需求并在游戏内回复。

用法（管理员）：/mcc 监听 开 | 关 | 状态
"""
import asyncio
import re
import time
from typing import Dict, Set, Tuple
from neobot.plugin_api import McpAdapter, mcc_manager, ModuleLogger, global_config
from neobot.plugins.mcc_agent import run_mcc_agent

logger = ModuleLogger("MccListener")

# 轮询间隔（秒）
POLL_INTERVAL = 4.0
# 已处理消息去重上限
MAX_SEEN = 200

_seen: Set[str] = set()
_tasks: list = []
_running = False
# 机器人自己最近发出的回复（实例名, 内容）→ 时间，用于防自触发循环
_sent_replies: Dict[Tuple[str, str], float] = {}
_SENT_REPLY_TTL = 180.0


def _build_call_re(trigger_words: list) -> re.Pattern:
    """构建"称呼开头"触发正则（消息开头或转发冒号后紧跟称呼）。

    用 ASCII 单词字符负向断言 (?![A-Za-z0-9_]) 代替 \\b：
    Python 的 \\b 把中文也算单词字符，"luoxiaolei查…" 会因无词边界而漏触发；
    同时避免误触发 "luoxiaolei7567"（机器人全名）。
    """
    pattern = "|".join(re.escape(w) for w in trigger_words)
    return re.compile(rf"(?:^|[:：])\s*(?:{pattern})(?![A-Za-z0-9_])", re.IGNORECASE)


def is_running() -> bool:
    return _running


async def _ignored_bot_names() -> set:
    """监听需要忽略的机器人名字（所有 MCC 实例 + 配置的外部桥接机器人）。"""
    names = set()
    try:
        for ad in await mcc_manager.all():
            if ad.role_name:
                names.add(ad.role_name)
                if ad.role_name.startswith("_"):
                    names.add(ad.role_name[1:])
                else:
                    names.add("_" + ad.role_name)
    except Exception:
        pass
    try:
        names.update(global_config.mcc_adapter.listener_ignore_senders or [])
    except Exception:
        pass
    return names


async def start() -> bool:
    """为所有已配置的 MCC 实例启动后台监听任务。"""
    global _tasks, _running
    if _running:
        return True
    _running = True
    for adapter in await mcc_manager.all():
        # 热重载会产生新的模块实例：先取消挂在 adapter 上的旧任务，避免双监听
        old_task = getattr(adapter, "_listener_task", None)
        if old_task is not None and not old_task.done():
            old_task.cancel()
            try:
                await old_task
            except asyncio.CancelledError:
                pass
        task = asyncio.create_task(_poll_loop(adapter))
        adapter._listener_task = task
        _tasks.append(task)
        logger.info(f"MCC 服务器内监听已启动: {adapter.role_name or adapter.url}")
    return True


async def stop() -> bool:
    """停止后台监听任务。"""
    global _tasks, _running
    _running = False
    for adapter in await mcc_manager.all():
        task = getattr(adapter, "_listener_task", None)
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        adapter._listener_task = None
    for task in _tasks:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
    _tasks = []
    logger.info("MCC 服务器内监听已停止")
    return True


async def _poll_loop(adapter: McpAdapter):
    while _running:
        # 互斥锁防止热重载产生的双任务并发处理
        async with adapter.listener_poll_guard():
            try:
                await _poll_once(adapter)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error(f"监听轮询异常: {type(e).__name__}: {e}")
        await asyncio.sleep(POLL_INTERVAL)


def _clean_markdown(text: str) -> str:
    """清理 Agent 回复中的 Markdown 符号，适合游戏内聊天展示。"""
    text = re.sub(r"\*\*|__|`|~~", "", text)
    text = re.sub(r"^[#>*\-\s]+", "", text, flags=re.MULTILINE)
    text = text.strip()
    # 游戏聊天不支持多行：压缩所有空白为单空格，避免服务器按行拆成多条消息
    text = " ".join(text.split())
    # 兜底：截掉"已回复 xxx"之类的自我描述尾巴（Agent 可能无视提示词）
    for marker in ("已回复", "我已在游戏里", "已回他", "已在游戏里回复"):
        idx = text.find(marker)
        if idx > 0:
            text = text[:idx].strip()
            break
    return text


def _dedup_key(sender: str, message: str) -> tuple:
    """
    计算监听去重键：同一玩家消息可能以多种形态出现（游戏内直接消息、
    粉丝群互通回传的 "[前缀] 玩家名: 内容"、"[前缀] : 内容" 甚至嵌套多层转发），
    迭代剥离前缀/空名冒号/"名: "后取最里层的 (玩家名, 内容) 作为去重键。
    """
    name, content = sender, message.strip()
    for _ in range(6):  # 最多剥 6 层
        # 1) 剥离开头 [xxx] 前缀（可能嵌套多层）
        prefix = re.match(r"^\[[^\]]*\]\s*", content)
        if prefix:
            content = content[prefix.end():]
            continue
        # 2) 剥离空名冒号 "[前缀] : 内容" → 内容
        empty_colon = re.match(r"^[:：]\s*", content)
        if empty_colon:
            content = content[empty_colon.end():]
            continue
        # 3) 剥离 "名字: 内容"
        named = re.match(r"^([^:：]+?)[:：]\s*(.+)$", content)
        if named and named.group(1).strip():
            name = named.group(1).strip()
            content = named.group(2).strip()
            continue
        break
    return (name, content)


async def _handle_mention(adapter: McpAdapter, sender: str, message: str):
    """玩家对机器人说话：与 /ag /mcc agent 完全一致地调用 Agent。"""
    try:
        reply = await run_mcc_agent(message, adapter=adapter, caller={"name": sender})
    except Exception as e:
        logger.error(f"Agent 应答异常: {type(e).__name__}: {e}")
        reply = "抱歉，我暂时处理不了，可以稍后再试。"

    text = _clean_markdown(reply).strip()
    if not text:
        return
    # 游戏聊天有长度限制，截断
    text = text[:200]
    await adapter.send_chat(text)
    _sent_replies[(adapter.name, text)] = time.monotonic()
    logger.info(f"已回复游戏内玩家 {sender}: {text[:80]}")


async def _poll_once(adapter: McpAdapter):
    """轮询指定实例的聊天历史，处理提到机器人的新消息。"""
    try:
        history = await adapter.chat_history(max_count=30)
    except Exception as e:
        logger.debug(f"读取聊天历史失败: {type(e).__name__}: {e}")
        return
    self_name = adapter.role_name
    call_re = _build_call_re(adapter.trigger_words)
    entries = (history.get("data") or {}).get("entries") or []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        kind = entry.get("kind")
        if kind == "chat":
            pass  # 游戏内玩家聊天
        elif kind == "system":
            # 系统消息只处理粉丝群互通（玩家在 QQ 群对机器人说话）；
            # 成就/ECO节能/加入服务器/私信等其他系统消息一律不响应
            if not (entry.get("text") or "").startswith("[粉丝群]"):
                continue
        else:
            continue
        sender = (entry.get("sender") or "").strip()
        message = (entry.get("message") or entry.get("text") or "").strip()
        if not message:
            continue
        key = f"{entry.get('timestampUtc')}|{message}"
        if key in _seen:
            continue
        _seen.add(key)
        if len(_seen) > MAX_SEEN:
            _seen.clear()
        if self_name:
            # 兼容游戏内显示名带 "_" 前缀的情况（如 _FAKE_LUO_1）
            display_variants = {self_name}
            if self_name.startswith("_"):
                display_variants.add(self_name[1:])
            else:
                display_variants.add("_" + self_name)
            if sender in display_variants:
                continue
            # 防循环：机器人自己发言经粉丝群互通回传的消息（带"机器人名:"发言标记）不触发
            if any(f"{v}:" in message or f"{v}：" in message for v in display_variants):
                continue
        if call_re.search(message):
            dedup_key = _dedup_key(sender, message)
            dedup_name, dedup_content = dedup_key
            now = time.monotonic()
            # 防循环：机器人自己刚发出的回复（粉丝群互通回传）不再触发
            sent_at = _sent_replies.get((adapter.name, dedup_content))
            if sent_at is not None and now - sent_at < _SENT_REPLY_TTL:
                logger.debug("忽略机器人自己刚发送的回复（防循环）")
                continue
            if len(_sent_replies) > 512:
                _sent_replies.clear()
            # 防循环：消息发送者（去重后）是机器人自己
            if self_name:
                display_variants = {self_name}
                if self_name.startswith("_"):
                    display_variants.add(self_name[1:])
                else:
                    display_variants.add("_" + self_name)
                if dedup_name in display_variants:
                    logger.debug("忽略机器人自己的消息（防循环）")
                    continue
            # 忽略其他机器人（MCC 实例或外部桥接机器人）的发言，避免互相触发
            if dedup_name and dedup_name in await _ignored_bot_names():
                logger.debug(f"忽略其他机器人的消息：{dedup_name}")
                continue
            # 去重以消息内容为准：同一玩家消息的多个转发副本（发送者名不同或为空）视为同一条
            if not adapter.listener_should_respond(dedup_key[1]):
                logger.debug("60s 内已响应过同类消息，跳过")
                continue
            logger.info(f"游戏内玩家 {dedup_key[0]} 提到机器人：{dedup_key[1][:80]}")
            # 用规范化后的真实发送者与消息内容（互通转发消息的原始 sender 可能为空）
            await _handle_mention(adapter, dedup_key[0], dedup_key[1])
