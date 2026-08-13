# -*- coding: utf-8 -*-
"""
事件路由与转换器 (Event Router & Converter)

此模块负责在不同平台（如 Discord）和 OneBot 业务逻辑之间进行数据转换。
核心目标是：**让现有的 OneBot 插件（如 bili.py）在不修改任何代码的情况下，能够处理 Discord 消息。**

实现原理：
1. 接收 Discord 消息 (`discord.Message`)。
2. 将其"伪装"成 OneBot 的 `GroupMessageEvent` 或 `PrivateMessageEvent`。
3. 拦截插件调用的 `event.reply()` 方法。
4. 将插件返回的 OneBot `MessageSegment` 转换为 Discord 格式并发送。
5. 将机器人回复的消息转发到跨平台映射的另一端
"""
import asyncio
import base64
import io
import re
import traceback
from typing import Union, List, Any, Optional, Dict

try:
    import discord
    DISCORD_AVAILABLE = True
except ImportError:
    DISCORD_AVAILABLE = False

from neobot.models.events.message import GroupMessageEvent, PrivateMessageEvent
from neobot.models.message import MessageSegment as OneBotMessageSegment
from neobot.core.utils.logger import ModuleLogger

logger = ModuleLogger("EventRouter")

# CQ 码正则：[CQ:type,key=val,key=val]
_CQ_PATTERN = re.compile(r'\[CQ:([^,]+)(?:,([^\]]+))?\]')


def _parse_cq_params(params_str: str) -> Dict[str, str]:
    """解析 CQ 码参数字符串为字典。"""
    params: Dict[str, str] = {}
    if not params_str:
        return params
    for param in params_str.split(','):
        if '=' in param:
            k, v = param.split('=', 1)
            params[k] = v
    return params


def _resolve_file_to_discord_file(file_url: Any, seg_type: str) -> Optional['discord.File']:
    """
    将 OneBot 文件 URL/路径/base64 解析为 discord.File。

    Args:
        file_url: 文件标识（http(s) URL / base64:// / data:... / 本地路径 / bytes）
        seg_type: 消息段类型（image / video / record）

    Returns:
        discord.File 实例；当输入为 http URL 或解析失败时返回 None（由调用方决定如何处理 URL）
    """
    if file_url is None:
        return None

    # bytes 直接构造
    if isinstance(file_url, bytes):
        try:
            filename = "file.png" if seg_type == "image" else ("file.mp4" if seg_type == "video" else "file.ogg")
            return discord.File(fp=io.BytesIO(file_url), filename=filename)
        except Exception as e:
            logger.error(f"解析 bytes 文件失败: {e}")
            return None

    url_str = str(file_url)

    # http URL 交由调用方作为链接文本处理
    if url_str.startswith("http"):
        return None

    # base64:// 或 data:... 协议
    if url_str.startswith("base64://") or url_str.startswith("data:image") or url_str.startswith("data:audio") or url_str.startswith("data:video"):
        b64_data = url_str
        if b64_data.startswith("base64://"):
            b64_data = b64_data[9:]
        if b64_data.startswith("data:image") or b64_data.startswith("data:audio") or b64_data.startswith("data:video"):
            b64_data = b64_data.split(",", 1)[1]
        try:
            file_bytes = base64.b64decode(b64_data)
            filename = "file.png" if seg_type == "image" else ("file.mp4" if seg_type == "video" else "file.ogg")
            return discord.File(fp=io.BytesIO(file_bytes), filename=filename)
        except Exception as e:
            logger.error(f"解析 Base64 文件失败: {e}")
            return None

    # 本地文件路径
    try:
        return discord.File(url_str)
    except Exception as e:
        logger.error(f"无法读取本地文件 {url_str}: {e}")
        return None


def _append_text_with_file(content: str, file_url: Any, seg_type: str, files: list) -> str:
    """处理一段文件 URL：能转成 discord.File 就追加到 files，否则作为链接追加到 content。"""
    disc_file = _resolve_file_to_discord_file(file_url, seg_type)
    if disc_file is not None:
        files.append(disc_file)
        return content
    # 解析返回 None 且是 http URL：作为链接文本追加
    if isinstance(file_url, str) and file_url.startswith("http"):
        return content + f"\n{file_url}"
    if file_url is not None and not isinstance(file_url, bytes):
        url_str = str(file_url)
        if url_str.startswith("http"):
            return content + f"\n{url_str}"
    return content


def _render_cq_text_to_content(text: str, files: list) -> str:
    """将含 CQ 码的纯文本转换为 Discord content（图片/视频/音频转为 files）。"""
    matches = list(_CQ_PATTERN.finditer(text))
    if not matches:
        return text

    content = ""
    last_end = 0
    for match in matches:
        if match.start() > last_end:
            content += text[last_end:match.start()]

        cq_type = match.group(1)
        params = _parse_cq_params(match.group(2) or "")

        if cq_type in ("image", "video", "record"):
            file_url = params.get("url") or params.get("file")
            if file_url:
                content = _append_text_with_file(content, file_url, cq_type, files)
        elif cq_type == "face":
            content += f"[表情:{params.get('id')}]"
        elif cq_type == "at":
            qq_id = params.get("qq")
            content += "@everyone " if qq_id == "all" else f"<@{qq_id}> "

        last_end = match.end()

    if last_end < len(text):
        content += text[last_end:]
    return content


def _render_segment_to_content(
    segment: OneBotMessageSegment,
    content: str,
    files: list,
) -> str:
    """将单个 OneBotMessageSegment 追加到 content / files。"""
    seg_type = segment.type
    seg_data = segment.data

    if seg_type == "text":
        return content + seg_data.get("text", "")
    if seg_type in ("image", "video", "record"):
        file_url = seg_data.get("url") or seg_data.get("file")
        if file_url:
            return _append_text_with_file(content, file_url, seg_type, files)
        return content
    if seg_type == "face":
        return content + f"[表情:{seg_data.get('id')}]"
    if seg_type == "at":
        qq_id = seg_data.get("qq")
        return content + ("@everyone " if qq_id == "all" else f"<@{qq_id}> ")
    if seg_type == "reply":
        return content
    return content

class DiscordBotWrapper:
    """
    包装 DiscordAdapter，提供与 OneBot 相同的发送接口。
    """
    def __init__(self, adapter: Any):
        self.adapter = adapter
        self.self_id = adapter.user.id if adapter.user else 0

    async def send_group_msg(self, group_id: int, message: Union[str, OneBotMessageSegment, List[OneBotMessageSegment]], auto_escape: bool = False):
        channel = self.adapter.get_channel(group_id)
        if not channel:
            logger.error(f"Discord channel {group_id} not found")
            return

        await DiscordToOneBotConverter.send_discord_message(channel, message, self.adapter)

    async def send_private_msg(self, user_id: int, message: Union[str, OneBotMessageSegment, List[OneBotMessageSegment]], auto_escape: bool = False):
        user = self.adapter.get_user(user_id)
        if not user:
            logger.error(f"Discord user {user_id} not found")
            return
        if not user.dm_channel:
            await user.create_dm()
        await DiscordToOneBotConverter.send_discord_message(user.dm_channel, message, self.adapter)

    async def send(self, event, message, **kwargs):
        if isinstance(event, GroupMessageEvent):
            await self.send_group_msg(event.group_id, message)
        elif isinstance(event, PrivateMessageEvent):
            await self.send_private_msg(event.user_id, message)

    def build_forward_node(self, user_id: int, nickname: str, message: Union[str, OneBotMessageSegment, List[OneBotMessageSegment]]) -> Dict[str, Any]:
        """
        构建一个用于合并转发的消息节点 (Node)。
        """
        processed_message = message
        if isinstance(message, OneBotMessageSegment):
            processed_message = [{"type": message.type, "data": message.data}]
        elif isinstance(message, list):
            processed_message = [{"type": seg.type, "data": seg.data} if isinstance(seg, OneBotMessageSegment) else seg for seg in message]
            
        return {
            "type": "node",
            "data": {
                "uin": user_id,
                "name": nickname,
                "content": processed_message
            }
        }

    async def send_forwarded_messages(self, target, nodes):
        """
        模拟发送合并转发消息。
        Discord 不支持像 QQ 那样的合并转发，所以我们将其转换为普通消息发送。
        """
        content = ""
        files = []

        try:
            for node in nodes:
                if node.get("type") != "node":
                    continue
                node_data = node.get("data", {})
                node_content = node_data.get("content", [])

                if isinstance(node_content, str):
                    content += _render_cq_text_to_content(node_content, files)
                    content += "\n"
                elif isinstance(node_content, list):
                    for seg in node_content:
                        if isinstance(seg, dict):
                            seg_type = seg.get("type")
                            seg_data = seg.get("data", {})
                            # 复用 _render_segment_to_content 的逻辑（构造临时 MessageSegment）
                            if seg_type == "text":
                                content += seg_data.get("text", "")
                            elif seg_type in ("image", "video", "record"):
                                file_url = seg_data.get("url") or seg_data.get("file")
                                if file_url:
                                    content = _append_text_with_file(content, file_url, seg_type, files)
                            elif seg_type == "face":
                                content += f"[表情:{seg_data.get('id')}]"
                            elif seg_type == "at":
                                qq_id = seg_data.get("qq")
                                content += "@everyone " if qq_id == "all" else f"<@{qq_id}> "
                    content += "\n"

            if content or files:
                # CommandContext 等平台上下文同样带 group_id/user_id，按事件处理
                target_group_id = getattr(target, "group_id", None)
                target_user_id = getattr(target, "user_id", None)
                if target_group_id is not None:
                    channel = self.adapter.get_channel(target_group_id)
                    if channel:
                        await channel.send(content=content, files=files if files else None)
                elif target_user_id is not None:
                    user = self.adapter.get_user(target_user_id)
                    if user:
                        if not user.dm_channel:
                            await user.create_dm()
                        await user.dm_channel.send(content=content, files=files if files else None)
        except Exception as e:
            logger.error(f"发送 Discord 合并转发消息失败: {e}\n{traceback.format_exc()}")
            raise

class DiscordToOneBotConverter:
    """OneBot 消息段 → Discord 发送的转换器（已不再伪造 OneBot 事件）。"""
    
    @staticmethod
    async def send_discord_message(
        channel: 'discord.abc.Messageable', 
        message: Union[str, OneBotMessageSegment, List[OneBotMessageSegment]],
        adapter: Any
    ):
        """
        将 OneBot 的消息段转换为 Discord 格式并发送。
        
        Args:
            channel: Discord 频道对象 (TextChannel, DMChannel 等)
            message: 插件返回的 OneBot 消息内容 (字符串或 MessageSegment 列表)
            adapter: DiscordAdapter 实例
        """
        content = ""
        files = []

        try:
            if not isinstance(message, list):
                message = [message]

            for segment in message:
                if isinstance(segment, str):
                    content += _render_cq_text_to_content(segment, files)
                elif isinstance(segment, OneBotMessageSegment):
                    content = _render_segment_to_content(segment, content, files)

            if content or files:
                await channel.send(content=content, files=files if files else None)
                from neobot.plugins.discord_cross.forwarder import forwarder

                if adapter.user:
                    sender_name = getattr(adapter.user, 'global_name', None) or adapter.user.name
                else:
                    sender_name = "Bot"
                await forwarder.notify_discord_sent(channel.id, content, sender_name=sender_name)
            else:
                logger.warning("尝试发送空消息到 Discord，已拦截")
        except Exception as e:
            logger.error(f"发送 Discord 消息失败: {e}\n{traceback.format_exc()}")
            raise
