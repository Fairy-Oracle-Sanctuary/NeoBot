# -*- coding: utf-8 -*-
"""
CLI 调试适配器

提供命令行交互界面用于无头调试机器人插件。
模拟消息事件并将 Bot 的所有发送操作打印到终端。
"""
import asyncio
import time
import json
from typing import Optional, List, Dict, Any, Union

from neobot.core.bot import Bot
from neobot.models.events.message import GroupMessageEvent, PrivateMessageEvent
from neobot.models.message import MessageSegment
from neobot.models.sender import Sender
from neobot.core.utils.logger import logger

# ── ANSI 颜色 ──────────────────────────────────────────────
C_RESET = "\033[0m"
C_BOLD = "\033[1m"
C_DIM = "\033[2m"
C_RED = "\033[31m"
C_GREEN = "\033[32m"
C_YELLOW = "\033[33m"
C_BLUE = "\033[34m"
C_MAGENTA = "\033[35m"
C_CYAN = "\033[36m"
C_WHITE = "\033[37m"


def _c(text: str, color: str) -> str:
    """包裹 ANSI 颜色，不存在终端时会自动去掉。"""
    return f"{color}{text}{C_RESET}"


# ── 工具函数 ──────────────────────────────────────────────

def _truncate(text: str, max_len: int = 100) -> str:
    if len(text) <= max_len:
        return text
    return text[:max_len] + "..."


def _format_message_content(content: Any, indent: str = "  ") -> str:
    """将 Bot 内部的 message 格式渲染为可读字符串。"""
    if isinstance(content, str):
        return f"{indent}{content}"
    if isinstance(content, dict):
        mtype = content.get("type", "?")
        mdata = content.get("data", {})
        if mtype == "text":
            return f"{indent}{mdata.get('text', '')}"
        elif mtype == "image":
            url = mdata.get("file", "")
            return f"{indent}{_c('[图片]', C_MAGENTA)} {_truncate(url, 80)}"
        elif mtype == "video":
            url = mdata.get("file", "")
            return f"{indent}{_c('[视频]', C_MAGENTA)} {_truncate(url, 80)}"
        elif mtype == "record":
            url = mdata.get("file", "")
            return f"{indent}{_c('[语音]', C_MAGENTA)} {_truncate(url, 80)}"
        elif mtype == "at":
            return f"{indent}{_c('[@]', C_YELLOW)} {mdata.get('qq', '?')}"
        elif mtype == "reply":
            return f"{indent}{_c('[回复]', C_DIM)} msg_id={mdata.get('id', '?')}"
        elif mtype == "face":
            return f"{indent}{_c('[表情]', C_YELLOW)} id={mdata.get('id', '?')}"
        elif mtype == "json":
            return f"{indent}{_c('[JSON卡片]', C_CYAN)}"
        else:
            return f"{indent}{_c(f'[{mtype}]', C_DIM)} {json.dumps(mdata, ensure_ascii=False)[:120]}"
    if isinstance(content, list):
        lines = []
        for item in content:
            lines.append(_format_message_content(item, indent))
        return "\n".join(lines)
    return f"{indent}{str(content)[:200]}"


# ── Mock Bot ───────────────────────────────────────────────

class _DummyWS:
    """提供给 MockBot 构造函数的占位 WebSocket 客户端。"""
    def __init__(self):
        self.self_id = 999999


class MockBot(Bot):
    """Mock Bot，继承真实 Bot 的所有方法，但将 API 调用打印到终端。"""

    def __init__(self):
        super().__init__(_DummyWS())  # type: ignore[arg-type]
        self.nickname = "CLI-Bot"
        self._msg_id_counter = 1

    def _next_msg_id(self) -> int:
        mid = self._msg_id_counter
        self._msg_id_counter += 1
        return mid

    # ── 重写核心方法 ──────────────────────────────────

    async def call_api(self, action: str, params: Optional[Dict[str, Any]] = None) -> Any:
        """拦截所有 API 调用，格式化输出到终端。"""
        params = params or {}
        await self._display(action, params)
        return {"message_id": self._next_msg_id()}

    def _process_message(
        self,
        message: Union[str, "MessageSegment", List["MessageSegment"], Dict, List[Dict]],
    ) -> Union[str, List[Dict]]:
        """复用 BaseAPI 的原始实现（绕过 override 冲突）。"""
        from neobot.models.message import MessageSegment as _MS

        if message is None:
            return ""
        if isinstance(message, str):
            return message
        if isinstance(message, dict):
            return message
        if isinstance(message, _MS):
            return {"type": message.type, "data": message.data}
        if isinstance(message, list):
            result = []
            for item in message:
                if isinstance(item, _MS):
                    result.append({"type": item.type, "data": item.data})
                elif isinstance(item, dict):
                    result.append(item)
                elif isinstance(item, str):
                    if item:
                        result.append({"type": "text", "data": {"text": item}})
                elif item is not None:
                    result.append(str(item))
            return result
        return str(message)

    async def _display(self, action: str, params: Dict[str, Any]) -> None:
        """格式化打印单次 API 调用。"""
        print()
        print(_c("─" * 60, C_DIM))

        label_map = {
            "send_group_msg": "群消息",
            "send_private_msg": "私聊消息",
            "send_group_forward_msg": "群合并转发",
            "send_private_forward_msg": "私聊合并转发",
            "delete_msg": "撤回消息",
        }
        label = label_map.get(action, action)

        if action in ("send_group_msg", "send_private_msg"):
            target = params.get("group_id") or params.get("user_id")
            tag = "群" if params.get("group_id") else "用户"
            print(_c(f"  [Bot → {tag}:{target}] {label}", C_GREEN))
            msg = params.get("message", "")
            print(_format_message_content(msg))

        elif action in ("send_group_forward_msg", "send_private_forward_msg"):
            target = params.get("group_id") or params.get("user_id")
            messages = params.get("messages", [])
            print(_c(f"  [Bot → 合并转发:{target}] {label}  |  共 {len(messages)} 个节点", C_CYAN))
            for i, node in enumerate(messages, 1):
                data = node.get("data", {})
                name = data.get("name", "unknown")
                content = data.get("content", "")
                print(_c(f"  ┌─ 节点 {i}: {name}", C_BLUE))
                print(_format_message_content(content, indent="  │ "))
                print(_c("  └" + "─" * 40, C_DIM))

        elif action == "delete_msg":
            print(_c(f"  [Bot] 撤回消息  msg_id={params.get('message_id')}", C_YELLOW))

        else:
            print(_c(f"  [Bot] {action}  params={json.dumps(params, ensure_ascii=False)[:200]}", C_DIM))

        print(_c("─" * 60, C_DIM))
        print()


# ── CLI 交互器 ─────────────────────────────────────────────

CLI_HELP = f"""
{C_BOLD}NeoBot CLI 调试器{C_RESET}
{C_DIM}═══════════════════════════════{C_RESET}
  直接粘贴链接或输入命令即可调试插件。
  例如:
    https://v.douyin.com/xxxxx/     → 模拟抖音链接解析
    /查仓库 owner/repo               → 模拟 GitHub 命令

  {C_BOLD}内置命令:{C_RESET}
    /help      显示此帮助
    /group     切换到群聊模式 (默认)
    /private   切换到私聊模式
    /gid N     修改群号为 N (默认 10000)
    /uid N     修改用户 QQ 为 N (默认 10001)
    /exit, /q  退出
"""


class CLIDebugger:
    """CLI 交互调试器。"""

    def __init__(self) -> None:
        self.bot = MockBot()
        self.mode: str = "group"         # "group" | "private"
        self.group_id: int = 10000
        self.user_id: int = 10001
        self._msg_id_counter: int = 20000

    def _next_msg_id(self) -> int:
        mid = self._msg_id_counter
        self._msg_id_counter += 1
        return mid

    def _make_event(self, text: str) -> Union[GroupMessageEvent, PrivateMessageEvent]:
        """根据当前模式构造一个 MessageEvent。"""
        now = int(time.time())
        sender = Sender(user_id=self.user_id, nickname="CLI-Tester")

        if self.mode == "group":
            event = GroupMessageEvent(
                time=now,
                self_id=self.bot.self_id,
                message_type="group",
                sub_type="normal",
                message_id=self._next_msg_id(),
                user_id=self.user_id,
                group_id=self.group_id,
                message=[MessageSegment.text(text)],
                raw_message=text,
                font=0,
                sender=sender,
            )
        else:
            event = PrivateMessageEvent(
                time=now,
                self_id=self.bot.self_id,
                message_type="private",
                sub_type="friend",
                message_id=self._next_msg_id(),
                user_id=self.user_id,
                message=[MessageSegment.text(text)],
                raw_message=text,
                font=0,
                sender=sender,
            )

        # 注入 bot 引用（让 event.reply() / event.bot.xxx 可用）
        event.bot = self.bot
        return event

    async def _handle_input(self, text: str) -> bool:
        """处理一行用户输入，返回 False 表示应退出。"""
        text = text.strip()
        if not text:
            return True

        # ── 内置 CLI 命令 ──
        if text in ("/exit", "/q"):
            print(_c("再见!", C_GREEN))
            return False

        if text == "/help":
            print(CLI_HELP)
            return True

        if text == "/group":
            self.mode = "group"
            print(_c(f"已切换到群聊模式 (群号: {self.group_id})", C_GREEN))
            return True

        if text == "/private":
            self.mode = "private"
            print(_c(f"已切换到私聊模式 (用户: {self.user_id})", C_GREEN))
            return True

        if text.startswith("/gid "):
            try:
                self.group_id = int(text.split()[1])
                print(_c(f"群号已更新: {self.group_id}", C_GREEN))
            except (IndexError, ValueError):
                print(_c("用法: /gid <群号>", C_RED))
            return True

        if text.startswith("/uid "):
            try:
                self.user_id = int(text.split()[1])
                print(_c(f"用户 QQ 已更新: {self.user_id}", C_GREEN))
            except (IndexError, ValueError):
                print(_c("用法: /uid <QQ号>", C_RED))
            return True

        # ── 构造事件并分发 ──
        event = self._make_event(text)

        from neobot.core.managers.command_manager import matcher

        tag = _c("群", C_YELLOW) if self.mode == "group" else _c("私", C_CYAN)
        print(_c(f"[输入] ({tag}) {text}", C_DIM))

        try:
            await matcher.handle_event(self.bot, event)
        except Exception as e:
            logger.exception(f"[CLI] 事件处理异常: {e}")
            print(_c(f"[错误] {e}", C_RED))

        return True

    async def run(self) -> None:
        """启动 CLI 交互循环。"""
        print(CLI_HELP)
        print(_c(f"当前模式: 群聊  |  群号: {self.group_id}  |  用户: {self.user_id}", C_DIM))
        print(_c("输入内容开始调试...", C_DIM))
        print()

        loop = asyncio.get_running_loop()

        while True:
            try:
                # 异步读取 stdin，不阻塞事件循环
                line = await loop.run_in_executor(None, input, "> ")
                should_continue = await self._handle_input(line)
                if not should_continue:
                    break
            except KeyboardInterrupt:
                print()
                print(_c("再见!", C_GREEN))
                break
            except EOFError:
                print()
                break
