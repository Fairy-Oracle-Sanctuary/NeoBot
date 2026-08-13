# -*- coding: utf-8 -*-
import re
from typing import Dict, Any, List

from neobot.models import MessageEvent


def format_duration(seconds: int) -> str:
    """
    将秒数格式化为 MM:SS 的形式
    
    Args:
        seconds (int): 秒数
        
    Returns:
        str: 格式化后的时间字符串
    """
    if not isinstance(seconds, int) or seconds < 0:
        return "00:00"
    minutes, seconds = divmod(seconds, 60)
    return f"{minutes:02d}:{seconds:02d}"


def clean_url(url: str) -> str:
    """
    清理URL，去掉不必要的查询参数
    
    Args:
        url (str): 原始URL
        
    Returns:
        str: 清理后的URL
    """
    clean_url = url.split('?')[0]
    if '#/' in clean_url:
        clean_url = clean_url.split('#/')[0]
    return clean_url


def extract_original_text(segments: List[Any], url_pattern: re.Pattern) -> str:
    """
    从消息段中提取原始文本（去除链接）
    
    Args:
        segments (List[Any]): 消息段列表
        url_pattern (re.Pattern): URL正则表达式模式
        
    Returns:
        str: 提取的原始文本
    """
    for segment in segments:
        if segment.type == "text":
            text_content = segment.data.get("text", "")
            # 移除链接
            cleaned_text = re.sub(url_pattern, '', text_content)
            # 移除常见的分享提示
            cleaned_text = re.sub(r'复制此链接.*?打开.*?搜索.*?直接观看视频！', '', cleaned_text)
            cleaned_text = cleaned_text.strip()
            if cleaned_text:
                return cleaned_text
    return ""


def build_forward_nodes(event: MessageEvent, nickname: str, messages: List[Any]) -> List[Any]:
    """
    构建转发消息节点
    
    Args:
        event (MessageEvent): 消息事件对象
        nickname (str): 发送者昵称
        messages (List[Any]): 消息内容列表
        
    Returns:
        List[Any]: 转发消息节点列表
    """
    nodes = []
    for msg in messages:
        if isinstance(msg, str):
            node = event.bot.build_forward_node(
                user_id=event.self_id,
                nickname=nickname,
                message=msg
            )
            nodes.append(node)
        elif isinstance(msg, list):
            node = event.bot.build_forward_node(
                user_id=event.self_id,
                nickname=nickname,
                message=msg
            )
            nodes.append(node)
    return nodes


def safe_get(data: Dict[str, Any], keys: List[str], default: Any = None) -> Any:
    """
    安全地从嵌套字典中获取值
    
    Args:
        data (Dict[str, Any]): 嵌套字典
        keys (List[str]): 键路径列表
        default (Any, optional): 默认值. Defaults to None.
        
    Returns:
        Any: 获取的值或默认值
    """
    result = data
    for key in keys:
        if isinstance(result, dict) and key in result:
            result = result[key]
        else:
            return default
    return result


def normalize_url(url: str) -> str:
    """
    规范化URL
    
    Args:
        url (str): 原始URL
        
    Returns:
        str: 规范化后的URL
    """
    if not url.startswith('http'):
        url = 'https://' + url
    return url


def validate_url(url: str) -> bool:
    """
    验证URL格式是否正确
    
    Args:
        url (str): URL
        
    Returns:
        bool: URL格式是否正确
    """
    url_pattern = re.compile(r'https?://[^]+')
    return bool(url_pattern.match(url))
