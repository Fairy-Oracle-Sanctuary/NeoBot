# -*- coding: utf-8 -*-
"""
跨平台消息互通插件发送器模块
"""
import json
from typing import List
from neobot.core.utils.logger import ModuleLogger
from neobot.core.managers.redis_manager import redis_manager
from .config import config
from .translator import translate_with_deepseek, save_forward_pair
from .parser import format_discord_to_qq_content, format_qq_to_discord_content, extract_text_only

# 创建模块专用日志记录器
logger = ModuleLogger("CrossPlatformSender")

async def send_to_discord(channel_id: int, content: str, attachments: List[dict] = None, embed: dict = None):
    """发送消息到 Discord 频道"""
    try:
        logger.debug(f"[CrossPlatform:TRACE] send_to_discord: channel={channel_id}, content='{content[:80] if content else ''}...', attachments={len(attachments or [])}")
        publish_data = {
            "type": "send_message",
            "channel_id": channel_id,
            "content": content,
            "attachments": attachments or [],
            "embed": embed
        }
        # 附加 HMAC 签名，防止伪造发送消息
        publish_data["_sig"] = redis_manager.sign_pubsub(publish_data)
        await redis_manager.redis.publish("neobot_discord_send", json.dumps(publish_data))
        logger.info(f"[CrossPlatform] 消息已发布到 Redis 供 Discord 适配器发送: {channel_id}")
        
    except Exception as e:
        logger.error(f"[CrossPlatform] 发送消息到 Discord 失败: {e}")

async def send_to_qq(group_id: int, content: str, attachments: List[dict] = None):
    """发送消息到 QQ 群"""
    try:
        logger.debug(f"[CrossPlatform:TRACE] send_to_qq: group={group_id}, content='{content[:80] if content else ''}...', attachments={len(attachments or [])}")
        from neobot.core.managers.bot_manager import bot_manager
        from neobot.models.message import MessageSegment
        
        all_bots = bot_manager.get_all_bots()
        
        if not all_bots:
            logger.error(f"[CrossPlatform] 没有可用的 QQ 机器人实例")
            return
            
        logger.debug(f"[CrossPlatform:TRACE] send_to_qq: 找到 {len(all_bots)} 个 QQ 机器人实例")
        
        for bot in all_bots:
            try:
                message = content
                
                if attachments:
                    full_message = []
                    if content:
                        full_message.append(MessageSegment.text(content))
                    for attachment in attachments:
                        if isinstance(attachment, dict):
                            att_type = attachment.get("type", "image")
                            attachment_url = attachment.get("url", "")
                            
                            if att_type == "image":
                                full_message.append(MessageSegment.image(attachment_url, cache=True, proxy=True, timeout=30))
                            elif att_type == "record":
                                full_message.append(MessageSegment.record(attachment_url, cache=True, proxy=True, timeout=30))
                            elif att_type == "video":
                                full_message.append(MessageSegment.video(attachment_url))
                            elif att_type == "file":
                                full_message.append(MessageSegment.file(attachment_url))
                                logger.success(f"[CrossPlatform] 已添加文件到 QQ 消息: {attachment_url}")
                        else:
                            attachment_url = str(attachment)
                            if attachment_url.lower().endswith(('.mp4', '.avi', '.mkv', '.mov', '.flv', '.wmv')):
                                full_message.append(MessageSegment.video(attachment_url))
                            elif attachment_url.lower().endswith(('.amr', '.silk', '.mp3', '.wav', '.ogg', '.m4a')):
                                full_message.append(MessageSegment.record(attachment_url, cache=True, proxy=True, timeout=30))
                            elif attachment_url.lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.webp')):
                                image_type = "flash" if attachment_url.lower().endswith('.gif') else None
                                full_message.append(MessageSegment.image(attachment_url, cache=True, proxy=True, timeout=30, image_type=image_type))
                            else:
                                full_message.append(MessageSegment.file(attachment_url))
                                logger.success(f"[CrossPlatform] 已添加文件到 QQ 消息 (通过扩展名识别): {attachment_url}")
                    
                    logger.debug(f"[CrossPlatform] 准备发送消息到 QQ 群 {group_id}: {full_message}")
                    await bot.send_group_msg(group_id, full_message, no_mirror=True)
                    logger.success(f"[CrossPlatform:TRACE] send_to_qq: 发送成功 → QQ群{group_id}")
                else:
                    logger.debug(f"[CrossPlatform] 准备发送纯文本消息到 QQ 群 {group_id}: {message}")
                    logger.debug(f"[CrossPlatform:TRACE] send_to_qq: 使用 bot self_id={bot.self_id} 发送到 QQ群{group_id}")
                    await bot.send_group_msg(group_id, message, no_mirror=True)
                    logger.success(f"[CrossPlatform:TRACE] send_to_qq: 发送成功 → QQ群{group_id}")
                break
            except Exception as e:
                logger.error(f"[CrossPlatform] 发送消息到 QQ 群 {group_id} 失败: {e}")
                
    except Exception as e:
        logger.error(f"[CrossPlatform] 发送消息到 QQ 失败: {e}")

async def forward_discord_to_qq(
    discord_username: str,
    discord_discriminator: str,
    content: str,
    channel_id: int,
    attachments: List[dict] = None,
    translate: bool = True,
):
    """将 Discord 消息转发到所有映射的 QQ 群"""
    logger.debug(f"[CrossPlatform] forward_discord_to_qq: channel_id={channel_id}, attachments={attachments}")
    if channel_id not in config.CROSS_PLATFORM_MAP:
        logger.warning(f"[CrossPlatform] 未找到 Discord 频道 {channel_id} 的映射配置")
        return
        
    group_info = config.CROSS_PLATFORM_MAP[channel_id]
    target_qq_group = group_info["qq_group_id"]
    
    formatted_content, image_list = await format_discord_to_qq_content(
        discord_username,
        discord_discriminator,
        content,
        channel_id,
        attachments
    )
    
    logger.debug(f"[CrossPlatform] 格式化后的内容: '{formatted_content}', 图片列表: {image_list}")
    
    if formatted_content and translate:
        # 只提取文本进行翻译，过滤掉非文本内容
        text_only = extract_text_only(formatted_content)
        if text_only:
            translated_content = await translate_with_deepseek(text_only, "zh-CN", channel_id, "en2zh")
            if translated_content != text_only:
                # 同时包含原文和翻译内容
                formatted_content = f"{formatted_content}\n\n[翻译]\n{translated_content}"
    
    # 保存转发消息配对到向量数据库
    save_forward_pair(
        channel_id=channel_id,
        source_platform="discord",
        original_content=content,
        formatted_content=formatted_content,
        username=f"{discord_username}#{discord_discriminator}"
    )
    
    await send_to_qq(target_qq_group, formatted_content, image_list)
    logger.success(f"[CrossPlatform] Discord 频道 {channel_id} -> QQ 群 {target_qq_group}")
    logger.debug(f"[CrossPlatform] send_to_qq 已调用: group_id={target_qq_group}, formatted_content='{formatted_content}', image_list={image_list}")

async def forward_qq_to_discord(
    qq_nickname: str,
    qq_user_id: int,
    group_name: str,
    group_id: int,
    content: str,
    attachments: List[dict] = None
):
    """将 QQ 消息转发到所有映射的 Discord 频道"""
    target_channels = []
    for discord_channel_id, info in config.CROSS_PLATFORM_MAP.items():
        if info["qq_group_id"] == group_id:
            target_channels.append(discord_channel_id)
            
    if not target_channels:
        logger.warning(f"[CrossPlatform] 未找到 QQ 群 {group_id} 的映射配置")
        return
        
    formatted_content, image_list, embed = await format_qq_to_discord_content(
        qq_nickname,
        qq_user_id,
        group_name,
        group_id,
        content,
        attachments
    )
    
    if embed and embed.get("description"):
        original_text = embed["description"]
        # 只提取文本进行翻译
        text_only = extract_text_only(original_text)
        if text_only:
            translated_text = await translate_with_deepseek(text_only, "en", group_id, "zh2en")
            if translated_text != text_only:
                # 同时包含原文和翻译内容
                embed["description"] = f"{original_text}\n\n[Translation]\n{translated_text}"
    
    # 保存转发消息配对到向量数据库
    for channel_id in target_channels:
        save_forward_pair(
            channel_id=channel_id,
            source_platform="qq",
            original_content=content,
            formatted_content=formatted_content,
            username=f"{qq_nickname}({qq_user_id})"
        )
    
    for channel_id in target_channels:
        await send_to_discord(channel_id, formatted_content, image_list, embed)
        
    logger.success(f"[CrossPlatform] QQ 群 {group_id} -> Discord 频道 {target_channels}")

async def publish_to_redis(platform: str, data: dict):
    """通过 Redis 发布跨平台消息"""
    try:
        if redis_manager.redis:
            publish_data = {
                "platform": platform,
                "data": data,
                "timestamp": int(__import__('time').time())
            }
            # 附加 HMAC 签名，防止伪造跨平台消息
            publish_data["_sig"] = redis_manager.sign_pubsub(publish_data)
            await redis_manager.redis.publish(config.CROSS_PLATFORM_CHANNEL, json.dumps(publish_data))
            logger.debug(f"[CrossPlatform] 已通过 Redis 发布消息: platform={platform}")
    except Exception as e:
        logger.error(f"[CrossPlatform] Redis 发布失败: {e}")
