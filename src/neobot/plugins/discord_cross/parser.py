# -*- coding: utf-8 -*-
"""
跨平台消息互通插件解析器模块
"""
import os
import json
import re
from typing import Dict, List, Any
from neobot.models.message import MessageSegment
from neobot.plugin_api import ModuleLogger
from .config import config

# 创建模块专用日志记录器
logger = ModuleLogger("CrossPlatformParser")


def extract_text_only(content: str) -> str:
    """从消息内容中提取纯文本，过滤掉非文本标记"""
    if not content:
        return ""
    
    # 移除所有 [图片: xxx]、[视频: xxx]、[语音: xxx]、[文件: xxx] 等标记
    text_only = re.sub(r'\s*\[(图片|视频|语音|文件):[^\]]+\]\s*', ' ', content)
    
    # 移除连续空格
    text_only = re.sub(r'\s+', ' ', text_only).strip()
    
    return text_only

async def parse_forward_nodes(nodes: List[Dict[str, Any]]) -> tuple[str, List[dict]]:
    """解析 OneBot 合并转发消息节点"""
    content_parts = []
    attachments = []
    
    for node in nodes:
        if not isinstance(node, dict):
            continue
            
        node_data = node.get("data", {})
        node_content = node_data.get("content", "")
        
        sender_name = node_data.get("name", node_data.get("uin", "Unknown"))
        
        if isinstance(node_content, str):
            if "[object Object]" in node_content:
                content = f"[合并转发消息: {sender_name}]"
                content_parts.append(f"**{sender_name}**:\n{content}")
            elif '[CQ:' in node_content:
                content = parse_cq_code(node_content, attachments)
                content_parts.append(f"**{sender_name}**:\n{content}")
            else:
                content = node_content
                content_parts.append(f"**{sender_name}**:\n{content}")
        elif isinstance(node_content, list):
            content = parse_message_segments(node_content, attachments)
            content_parts.append(f"**{sender_name}**:\n{content}")
    
    full_content = "\n\n".join(content_parts) if content_parts else ""
    return full_content, attachments

def parse_cq_code(cq_code: str, attachments: List[dict]) -> str:
    """解析 CQ 码字符串"""
    import re
    
    cq_pattern = r'\[CQ:([^,]+)(?:,([^\]]+))?\]'
    matches = list(re.finditer(cq_pattern, cq_code))
    
    if not matches:
        return cq_code
    
    result = []
    last_end = 0
    
    for match in matches:
        if match.start() > last_end:
            result.append(cq_code[last_end:match.start()])
        
        cq_type = match.group(1)
        cq_params_str = match.group(2) or ""
        
        params = {}
        if cq_params_str:
            for param in cq_params_str.split(','):
                if '=' in param:
                    k, v = param.split('=', 1)
                    params[k] = v
        
        if cq_type == "text":
            result.append(params.get("text", ""))
        elif cq_type == "image":
            file_url = params.get("url") or params.get("file")
            if file_url:
                file_name = params.get("file", "")
                if not file_name:
                    file_name = os.path.basename(str(file_url).split('?')[0]) or "image"
                attachments.append({"type": "image", "url": str(file_url), "filename": file_name})
                result.append(f"\n[图片: {file_name}]\n")
        elif cq_type == "video":
            file_url = params.get("url") or params.get("file")
            if file_url:
                file_name = params.get("file", "")
                if not file_name:
                    file_name = os.path.basename(str(file_url).split('?')[0]) or "video"
                attachments.append({"type": "video", "url": str(file_url), "filename": file_name})
                result.append(f"\n[视频: {file_name}]\n")
        elif cq_type == "record":
            file_url = params.get("url") or params.get("file")
            if file_url:
                file_name = params.get("file", "")
                if not file_name:
                    file_name = os.path.basename(str(file_url).split('?')[0]) or "record"
                attachments.append({"type": "record", "url": str(file_url), "filename": file_name})
                result.append(f"\n[语音: {file_name}]\n")
        elif cq_type == "at":
            qq_id = params.get("qq")
            if qq_id == "all":
                result.append("@所有人 ")
            else:
                result.append(f"@{qq_id} ")
        elif cq_type == "face":
            face_id = params.get("id", "")
            result.append(f"[表情:{face_id}] ")
        elif cq_type == "reply":
            reply_id = params.get("id", "")
            result.append(f"[回复:{reply_id}] ")
        elif cq_type == "file":
            file_url = params.get("file", "")
            if file_url:
                file_name = os.path.basename(str(file_url).split('?')[0]) or "file"
                attachments.append({"type": "file", "url": str(file_url), "filename": file_name})
                result.append(f"\n[文件: {file_name}]\n")
        
        last_end = match.end()
    
    if last_end < len(cq_code):
        result.append(cq_code[last_end:])
    
    return "".join(result)

def parse_message_segments(segments: List[Any], attachments: List[dict]) -> str:
    """解析 MessageSegment 列表"""
    result = []
    
    for seg in segments:
        if isinstance(seg, str):
            result.append(seg)
        elif isinstance(seg, MessageSegment):
            seg_type = seg.type
            seg_data = seg.data
            
            if seg_type == "text":
                result.append(seg_data.get("text", ""))
            elif seg_type == "image":
                file_url = seg_data.get("url") or seg_data.get("file")
                if file_url:
                    file_name = seg_data.get("filename")
                    if not file_name:
                        file_name = os.path.basename(str(file_url).split('?')[0]) or "image"
                    attachments.append({"type": "image", "url": str(file_url), "filename": file_name})
                    result.append(f"\n[图片: {file_name}]\n")
            elif seg_type == "video":
                file_url = seg_data.get("url") or seg_data.get("file")
                if file_url:
                    file_name = seg_data.get("filename")
                    if not file_name:
                        file_name = os.path.basename(str(file_url).split('?')[0]) or "video"
                    attachments.append({"type": "video", "url": str(file_url), "filename": file_name})
                    result.append(f"\n[视频: {file_name}]\n")
            elif seg_type == "record":
                file_url = seg_data.get("url") or seg_data.get("file")
                if file_url:
                    file_name = seg_data.get("filename")
                    if not file_name:
                        file_name = os.path.basename(str(file_url).split('?')[0]) or "record"
                    attachments.append({"type": "record", "url": str(file_url), "filename": file_name})
                    result.append(f"\n[语音: {file_name}]\n")
            elif seg_type == "at":
                qq_id = seg_data.get("qq")
                if qq_id == "all":
                    result.append("@所有人 ")
                else:
                    result.append(f"@{qq_id} ")
            elif seg_type == "face":
                face_id = seg_data.get("id", "")
                result.append(f"[表情:{face_id}] ")
            elif seg_type == "reply":
                reply_id = seg_data.get("id", "")
                result.append(f"[回复:{reply_id}] ")
            elif seg_type == "file":
                file_url = seg_data.get("file", "")
                if file_url:
                    file_name = os.path.basename(str(file_url).split('?')[0]) or "file"
                    attachments.append({"type": "file", "url": str(file_url), "filename": file_name})
                    result.append(f"\n[文件: {file_name}]\n")
            elif seg_type == "json":
                json_data = seg_data.get("data", "")
                try:
                    parsed = json.loads(json_data)
                    if isinstance(parsed, dict):
                        result.append(f"\n[JSON数据: {json_data[:100]}...]\n")
                except Exception:
                    result.append("\n[JSON数据]\n")
            elif seg_type == "xml":
                result.append("\n[XML数据]\n")
        elif isinstance(seg, dict):
            seg_type = seg.get("type")
            seg_data = seg.get("data", {})
            
            if seg_type == "text":
                result.append(seg_data.get("text", ""))
            elif seg_type == "image":
                file_url = seg_data.get("url") or seg_data.get("file")
                if file_url:
                    file_name = seg_data.get("filename")
                    if not file_name:
                        file_name = os.path.basename(str(file_url).split('?')[0]) or "image"
                    attachments.append({"type": "image", "url": str(file_url), "filename": file_name})
                    result.append(f"\n[图片: {file_name}]\n")
            elif seg_type == "video":
                file_url = seg_data.get("url") or seg_data.get("file")
                if file_url:
                    file_name = seg_data.get("filename")
                    if not file_name:
                        file_name = os.path.basename(str(file_url).split('?')[0]) or "video"
                    attachments.append({"type": "video", "url": str(file_url), "filename": file_name})
                    result.append(f"\n[视频: {file_name}]\n")
            elif seg_type == "record":
                file_url = seg_data.get("url") or seg_data.get("file")
                if file_url:
                    file_name = seg_data.get("filename")
                    if not file_name:
                        file_name = os.path.basename(str(file_url).split('?')[0]) or "record"
                    attachments.append({"type": "record", "url": str(file_url), "filename": file_name})
                    result.append(f"\n[语音: {file_name}]\n")
            elif seg_type == "at":
                qq_id = seg_data.get("qq")
                if qq_id == "all":
                    result.append("@所有人 ")
                else:
                    result.append(f"@{qq_id} ")
    
    return "".join(result)

def get_platform_info(platform: str, identifier: Any) -> str:
    """获取平台信息字符串"""
    if platform == "discord":
        channel_id = int(identifier)
        if channel_id in config.CROSS_PLATFORM_MAP:
            group_info = config.CROSS_PLATFORM_MAP[channel_id]
            group_name = group_info.get("name", f"群组 {group_info['qq_group_id']}")
            return f"[Discord {group_name}]"
        return "[Discord]"
    elif platform == "qq":
        return "[PAW qq]"
    return ""

async def format_discord_to_qq_content(
    discord_username: str,
    discord_discriminator: str,
    content: str,
    channel_id: int,
    attachments: List[dict] = None
) -> tuple[str, List[dict]]:
    """将 Discord 消息格式化为 QQ 消息格式"""
    logger.debug(f"[CrossPlatform] format_discord_to_qq_content: username={discord_username}, content='{content}', attachments={attachments}")
    
    message_header = f"{discord_username}:"
    message_body = content.strip() if content else ""
    
    if message_body:
        full_message = f"{message_header}\n{message_body}"
    else:
        full_message = message_header
    
    processed_attachments = []
    if attachments:
        logger.debug(f"[CrossPlatform] 处理附件: {attachments}")
        for att in attachments:
            if isinstance(att, dict):
                url = att.get("url", "")
                filename = att.get("filename", "").lower()
                att_type = att.get("type", "")
                
                if att_type == "image" or filename.endswith(('.png', '.jpg', '.jpeg', '.gif', '.webp')):
                    processed_attachments.append({"type": "image", "url": url})
                elif att_type == "record" or filename.endswith(('.amr', '.silk', '.mp3', '.wav', '.ogg', '.m4a')):
                    processed_attachments.append({"type": "record", "url": url})
                elif att_type == "video" or filename.endswith(('.mp4', '.avi', '.mkv', '.mov', '.flv', '.wmv')):
                    processed_attachments.append({"type": "video", "url": url})
                else:
                    processed_attachments.append({"type": "file", "url": url, "filename": filename})
                    logger.debug(f"[CrossPlatform] Discord 消息格式化: 识别为文件 {filename}")
            else:
                url = str(att)
                logger.debug(f"[CrossPlatform] 处理非字典附件: {url}")
                if url.lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.webp')):
                    processed_attachments.append({"type": "image", "url": url})
                elif url.lower().endswith(('.amr', '.silk', '.mp3', '.wav', '.ogg', '.m4a')):
                    processed_attachments.append({"type": "record", "url": url})
                elif url.lower().endswith(('.mp4', '.avi', '.mkv', '.mov', '.flv', '.wmv')):
                    processed_attachments.append({"type": "video", "url": url})
                else:
                    filename = os.path.basename(url.split('?')[0]) or "file"
                    processed_attachments.append({"type": "file", "url": url, "filename": filename})
                    logger.debug(f"[CrossPlatform] Discord 消息格式化: 通过扩展名识别为文件 {filename}")
    
    logger.debug(f"[CrossPlatform] format_discord_to_qq_content 完成: full_message='{full_message}', processed_attachments={processed_attachments}")
    return full_message, processed_attachments

async def format_qq_to_discord_content(
    qq_nickname: str,
    qq_user_id: int,
    group_name: str,
    group_id: int,
    content: str,
    attachments: List[dict] = None
) -> tuple[str, List[dict], dict]:
    """将 QQ 消息格式化为 Discord 消息格式（Embed 卡片）"""
    
    embed = {
        "type": "rich",
        "color": 0x5865F2,
        "author": {
            "name": f"{qq_nickname}",
            "icon_url": f"https://q1.qlogo.cn/g?b=qq&nk={qq_user_id}&s=640"
        },
        "footer": {
            "text": "来自 QQ"
        }
    }
    
    if content:
        embed["description"] = content
    
    if attachments:
        image_urls = []
        voice_urls = []
        video_urls = []
        other_urls = []
        
        filtered_attachments = []
        
        for att in attachments:
            url = att.get("url", "")
            filename = att.get("filename", "").lower()
            att_type = att.get("type", "")
            
            if att_type == "image" or filename.endswith(('.png', '.jpg', '.jpeg', '.gif', '.webp')):
                image_urls.append(url)
                if len(image_urls) > 1:
                    filtered_attachments.append(att)
            elif att_type == "record" or filename.endswith(('.amr', '.silk', '.mp3', '.wav', '.ogg', '.m4a')):
                voice_urls.append(url)
                other_urls.append(url)
                filtered_attachments.append(att)
            elif att_type == "video" or filename.endswith(('.mp4', '.avi', '.mkv', '.mov', '.flv', '.wmv')):
                video_urls.append(url)
                other_urls.append(url)
                filtered_attachments.append(att)
            else:
                other_urls.append(url)
                filtered_attachments.append(att)
        
        attachments = filtered_attachments
        if content:
            embed["description"] = content
        elif "description" not in embed:
            embed["description"] = ""
        
        if image_urls:
            embed["image"] = {"url": image_urls[0]}
        
        if voice_urls:
            voice_filenames = [att.get("filename", "voice") for att in attachments if att.get("url") in voice_urls]
            voice_list = "\n".join([f"🎤 {fname}" for fname in voice_filenames[:5]])
            embed["description"] += f"\n\n**语音消息:**\n{voice_list}"
            if len(voice_urls) > 5:
                embed["description"] += f"\n...还有 {len(voice_urls) - 5} 条语音"
                
        if video_urls:
            video_filenames = [att.get("filename", "video") for att in attachments if att.get("url") in video_urls]
            video_list = "\n".join([f"🎬 {fname}" for fname in video_filenames[:5]])
            embed["description"] += f"\n\n**视频文件:**\n{video_list}"
            if len(video_urls) > 5:
                embed["description"] += f"\n...还有 {len(video_urls) - 5} 个视频"
        
        non_media_other_urls = [u for u in other_urls if u not in voice_urls and u not in video_urls]
        if non_media_other_urls:
            file_filenames = [att.get("filename", "file") for att in attachments if att.get("url") in non_media_other_urls]
            file_list = "\n".join([f"📄 {fname}" for fname in file_filenames[:5]])
            embed["description"] += f"\n\n**附加文件:**\n{file_list}"
            if len(non_media_other_urls) > 5:
                embed["description"] += f"\n...还有 {len(non_media_other_urls) - 5} 个文件"
    
    return "", attachments or [], embed
