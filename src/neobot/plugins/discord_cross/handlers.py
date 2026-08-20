# -*- coding: utf-8 -*-
"""
跨平台消息互通插件事件处理器模块
"""
import os
import html
from typing import List
from neobot.plugin_api import platform_command, platform_message, Permission, ModuleLogger, message_bus, PlatformMessage, PlatformSegment, bot_manager
from neobot.models.events.message import GroupMessageEvent, MessageEvent
from neobot.models.message import MessageSegment
from .config import config
from .parser import parse_forward_nodes

# 创建模块专用日志记录器
logger = ModuleLogger("CrossPlatform")

async def handle_discord_message(
    username: str,
    discriminator: str,
    content: str,
    channel_id: int,
    attachments: List[dict] = None,
    embed: dict = None
):
    """处理 Discord 消息并转发"""
    if not config.ENABLE_CROSS_PLATFORM:
        return
        
    logger.info(f"[CrossPlatform] 收到 Discord 消息: {username}#{discriminator} in {channel_id}")
    logger.debug(f"[CrossPlatform] 消息内容: '{content}', 附件: {attachments}")
    # 阶段 2/3：发布到消息总线，由转发器订阅处理
    segments = []
    if content:
        segments.append(PlatformSegment.text(content))
    for att in attachments or []:
        seg_type = att.get("type", "image") if isinstance(att, dict) else "image"
        seg_url = att.get("url", "") if isinstance(att, dict) else str(att)
        if seg_url:
            segments.append(PlatformSegment(seg_type, url=seg_url, filename=att.get("filename", "")))
    await message_bus.publish_incoming(
        PlatformMessage(
            platform="discord",
            channel_id=channel_id,
            channel_type="group",
            message_id=None,
            author_id=None,
            author_name=username or "Discord",
            content=content or "",
            segments=segments,
        )
    )

async def handle_qq_message(
    nickname: str,
    user_id: int,
    group_name: str,
    group_id: int,
    content: str,
    attachments: List[dict] = None
):
    """处理 QQ 消息并转发"""
    if not config.ENABLE_CROSS_PLATFORM:
        return
        
    logger.info(f"[CrossPlatform] 收到 QQ 消息: {nickname} ({user_id}) in {group_name}({group_id})")
    # 阶段 2/3：发布到消息总线，由转发器订阅处理
    segments = []
    if content:
        segments.append(PlatformSegment.text(content))
    for att in attachments or []:
        if isinstance(att, dict) and att.get("url"):
            segments.append(PlatformSegment(att.get("type", "image"), url=att["url"], filename=att.get("filename", "")))
    await message_bus.publish_incoming(
        PlatformMessage(
            platform="qq",
            channel_id=group_id,
            channel_type="group",
            message_id=None,
            author_id=user_id,
            author_name=nickname or "玩家",
            content=content or "",
            segments=segments,
        )
    )

@platform_message("qq", priority=0, block=False)
async def handle_qq_group_message(event: GroupMessageEvent):
    """处理 QQ 群消息，转发到 Discord"""
    try:
        logger.debug(f"[CrossPlatform:TRACE] handle_qq_group_message 入口: msg_id={event.message_id}, raw='{event.raw_message[:80] if event.raw_message else ''}'")
        if not config.ENABLE_CROSS_PLATFORM:
            return
            
        # 忽略非群消息和 Discord 注入的消息
        if not hasattr(event, 'group_id') or hasattr(event, '_is_discord_message'):
            return

        # 忽略机器人自己的消息，避免 DC→QQ 镜像后又被转发回 DC
        try:
            all_bots = bot_manager.get_all_bots()
            if all_bots and any(getattr(b, 'self_id', None) == event.user_id for b in all_bots):
                logger.debug(f"[CrossPlatform:TRACE] 忽略机器人自己的消息: user_id={event.user_id}")
                return
        except Exception:
            pass
            
        group_id = event.group_id
        mapped_channel = None
        for discord_channel_id, info in config.CROSS_PLATFORM_MAP.items():
            if info["qq_group_id"] == group_id:
                mapped_channel = discord_channel_id
                break
                
        if mapped_channel is None:
            return

        content = ""
        attachments = []
        
        if isinstance(event.message, list):
            has_forward_node = any(isinstance(seg, MessageSegment) and seg.type == "node" for seg in event.message)
            
            if has_forward_node:
                forward_nodes = [seg for seg in event.message if isinstance(seg, MessageSegment) and seg.type == "node"]
                forward_nodes_dict = [{"type": seg.type, "data": seg.data} for seg in forward_nodes]
                content, attachments = await parse_forward_nodes(forward_nodes_dict)
            else:
                for segment in event.message:
                    if isinstance(segment, MessageSegment):
                        if segment.type == "text":
                            content += segment.data.get("text", "")
                        elif segment.type == "image":
                            file_url = segment.data.get("url") or segment.data.get("file")
                            file_name = segment.data.get("filename")
                            if file_url:
                                file_url = html.unescape(str(file_url))
                                if not file_name:
                                    file_name = os.path.basename(file_url.split('?')[0]) or f"image_{len(attachments)}.jpg"
                                attachments.append({"type": "image", "url": file_url, "filename": file_name})
                        elif segment.type == "video":
                            file_url = segment.data.get("url") or segment.data.get("file")
                            file_name = segment.data.get("filename")
                            if file_url:
                                file_url = html.unescape(str(file_url))
                                if not file_name:
                                    file_name = os.path.basename(file_url.split('?')[0]) or f"video_{len(attachments)}.mp4"
                                attachments.append({"type": "video", "url": file_url, "filename": file_name})
                        elif segment.type == "record":
                            file_url = segment.data.get("url") or segment.data.get("file")
                            file_name = segment.data.get("filename")
                            if file_url:
                                file_url = html.unescape(str(file_url))
                                if not file_name:
                                    file_name = os.path.basename(file_url.split('?')[0]) or f"record_{len(attachments)}.amr"
                                attachments.append({"type": "record", "url": file_url, "filename": file_name})
                                content += f"\n[语音: {file_name}]\n"
                        elif segment.type == "file":
                            file_url = segment.data.get("url") or segment.data.get("file")
                            file_name = segment.data.get("filename")
                            if file_url:
                                file_url = html.unescape(str(file_url))
                                if not file_name:
                                    file_name = os.path.basename(file_url.split('?')[0]) or f"file_{len(attachments)}"
                                attachments.append({"type": "file", "url": file_url, "filename": file_name})
                                content += f"\n[文件: {file_name}]\n"
                                logger.debug(f"[CrossPlatform] QQ 消息识别到文件: {file_name}, URL: {file_url}")
                        elif segment.type == "at":
                            qq_id = segment.data.get("qq")
                            if qq_id and qq_id != "all":
                                content += f"@{qq_id} "
                            elif qq_id == "all":
                                content += "@所有人 "
                    elif isinstance(segment, str):
                        content += segment
        elif isinstance(event.message, str):
            content = event.message
        
        import re
        local_file_pattern = r'(http://[\w\.-]+:\d+/download\?id=file_[a-zA-Z0-9_]+)'
        matches = re.finditer(local_file_pattern, content)
        for match in matches:
            file_url = match.group(1)
            file_name = f"video_{len(attachments)}.mp4"
            attachments.append({"type": "video", "url": file_url, "filename": file_name})
        
        content = content.strip()
        
        group_name = ""
        try:
            group_info = await event.bot.get_group_info(event.group_id)
            group_name = group_info.get("group_name", "")
        except (AttributeError, KeyError, ValueError):
            group_name = f"群{group_id}"
        
        logger.debug(f"[CrossPlatform:TRACE] 准备转发 QQ→Discord: group_id={group_id}, content='{content[:80]}'")
        await handle_qq_message(
            nickname=event.sender.card or event.sender.nickname or str(event.user_id),
            user_id=event.user_id,
            group_name=group_name,
            group_id=group_id,
            content=content,
            attachments=attachments
        )
        logger.debug("[CrossPlatform:TRACE] 转发 QQ→Discord 完成")
    except (AttributeError, KeyError, ValueError) as e:
        logger.error(f"[CrossPlatform] 处理 QQ 群消息失败: {e}")
        import traceback
        logger.error(f"[CrossPlatform] 异常堆栈: {traceback.format_exc()}")

@platform_command(["qq", "discord"], "cross_config", "跨平台配置", permission=Permission.ADMIN)
async def cross_config_command(event: MessageEvent):
    """查看跨平台配置"""
    if not config.ENABLE_CROSS_PLATFORM:
        await event.reply("跨平台功能已禁用")
        return
        
    config_lines = ["=== 跨平台映射配置 ==="]
    
    if not config.CROSS_PLATFORM_MAP:
        config_lines.append("当前没有配置任何映射")
    else:
        for discord_id, info in config.CROSS_PLATFORM_MAP.items():
            discord_channel = f"Discord: {discord_id}"
            qq_group = f"QQ: {info['qq_group_id']}"
            name = info.get("name", "")
            if name:
                config_lines.append(f"• {discord_channel} ↔ {qq_group} ({name})")
            else:
                config_lines.append(f"• {discord_channel} ↔ {qq_group}")
                
    await event.reply("\n".join(config_lines))

@platform_command(["qq", "discord"], "cross_reload", "跨平台重载", permission=Permission.ADMIN)
async def cross_reload_command(event: MessageEvent):
    """重新加载跨平台配置"""
    await config.reload()
    await event.reply("跨平台配置已重载")
