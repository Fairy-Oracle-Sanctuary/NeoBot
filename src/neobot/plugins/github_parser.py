# -*- coding: utf-8 -*-
import re
import json
import aiohttp
from typing import Optional, Dict, Any, Union
from cachetools import TTLCache

from neobot.core.utils.logger import logger
from neobot.core.managers.command_manager import matcher
from neobot.core.managers.image_manager import image_manager
from neobot.models import MessageEvent, MessageSegment

# 插件元数据
__plugin_meta__ = {
    "name": "github_parser",
    "description": "自动解析GitHub仓库链接，或通过命令查询仓库信息。",
    "usage": "（自动触发）当检测到GitHub仓库链接时，自动发送仓库信息。\n（命令触发）/查仓库 作者/仓库名",
}

# 常量定义
GITHUB_NICKNAME = "GitHub仓库信息"

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
}

# 全局共享的 ClientSession
_session: Optional[aiohttp.ClientSession] = None

# 缓存GitHub API响应，避免频繁请求
api_cache = TTLCache(maxsize=100, ttl=3600)  # 100个缓存项，1小时过期


def get_session() -> aiohttp.ClientSession:
    """
    获取或创建全局的aiohttp ClientSession
    
    Returns:
        aiohttp.ClientSession: 客户端会话对象
    """
    global _session
    if _session is None or _session.closed:
        _session = aiohttp.ClientSession(headers=HEADERS)
    return _session


async def get_github_repo_info(owner: str, repo: str) -> Optional[Dict[str, Any]]:
    """
    通过GitHub API获取仓库信息
    
    Args:
        owner (str): 仓库所有者用户名
        repo (str): 仓库名称
        
    Returns:
        Optional[Dict[str, Any]]: 仓库信息字典，如果失败则返回None
    """
    cache_key = f"{owner}/{repo}"
    if cache_key in api_cache:
        logger.info(f"[github_parser] 使用缓存的仓库信息: {cache_key}")
        return api_cache[cache_key]
    
    api_url = f"https://api.github.com/repos/{owner}/{repo}"
    try:
        session = get_session()
        async with session.get(api_url, timeout=10) as response:
            response.raise_for_status()
            repo_data = await response.json()
            
            # 将数据存入缓存
            api_cache[cache_key] = repo_data
            logger.info(f"[github_parser] 成功获取仓库信息并缓存: {cache_key}")
            return repo_data
            
    except aiohttp.ClientError as e:
        logger.error(f"[github_parser] GitHub API请求失败: {e}")
    except json.JSONDecodeError as e:
        logger.error(f"[github_parser] 解析GitHub API响应失败: {e}")
    except Exception as e:
        logger.error(f"[github_parser] 获取仓库信息时发生未知错误: {e}")
    
    return None


async def generate_repo_image(repo_data: Dict[str, Any]) -> Optional[str]:
    """
    使用Jinja2模板渲染仓库信息为图片
    
    Args:
        repo_data (Dict[str, Any]): 仓库信息字典
        
    Returns:
        Optional[str]: 生成的图片Base64编码，如果失败则返回None
    """
    try:
        # 准备模板数据
        template_data = {
            "full_name": repo_data.get("full_name", ""),
            "description": repo_data.get("description", "暂无描述"),
            "owner_avatar": repo_data.get("owner", {}).get("avatar_url", ""),
            "stargazers_count": repo_data.get("stargazers_count", 0),
            "forks_count": repo_data.get("forks_count", 0),
            "open_issues_count": repo_data.get("open_issues_count", 0),
            "watchers_count": repo_data.get("watchers_count", 0),
        }
        
        # 渲染模板为图片，使用高质量设置
        base64_image = await image_manager.render_template_to_base64(
            template_name="github_repo.html",
            data=template_data,
            output_name=f"github_{repo_data.get('name', 'repo')}.png",
            quality=100,  # 使用最高质量
            image_type="png"  # PNG格式为无损压缩
        )
        
        return base64_image
        
    except Exception as e:
        logger.error(f"[github_parser] 生成仓库信息图片失败: {e}")
        return None


async def process_github_repo(event: MessageEvent, owner: str, repo: str):
    """
    处理GitHub仓库信息查询，获取信息并回复
    
    Args:
        event (MessageEvent): 消息事件对象
        owner (str): 仓库所有者用户名
        repo (str): 仓库名称
    """
    try:
        # 获取仓库信息
        repo_data = await get_github_repo_info(owner, repo)
        if not repo_data:
            logger.error(f"[github_parser] 无法获取仓库信息: {owner}/{repo}")
            await event.reply("无法获取仓库信息，可能是仓库不存在或网络问题。")
            return
        
        # 生成图片
        image_base64 = await generate_repo_image(repo_data)
        if image_base64:
            # 发送图片
            await event.reply(MessageSegment.image(image_base64))
        else:
            # 如果图片生成失败，发送文本信息
            text_message = (
                f"GitHub 仓库信息\n"
                f"--------------------\n"
                f"仓库: {repo_data.get('full_name', '')}\n"
                f"描述: {repo_data.get('description', '暂无描述')}\n"
                f"--------------------\n"
                f"数据:\n"
                f"   星标: {repo_data.get('stargazers_count', 0)}\n"
                f"   Fork: {repo_data.get('forks_count', 0)}\n"
                f"   Issues: {repo_data.get('open_issues_count', 0)}\n"
                f"   关注: {repo_data.get('watchers_count', 0)}\n"
            )
            await event.reply(text_message)
            
    except Exception as e:
        logger.error(f"[github_parser] 处理仓库信息时发生错误: {e}")
        await event.reply("处理仓库信息时发生错误，请稍后再试。")


# GitHub仓库链接正则表达式
GITHUB_URL_PATTERN = re.compile(r"https?://(?:www\.)?github\.com/([\w\-]+)/([\w\-\.]+)(?:/[^\s]*)?")


# 注册命令处理器
@matcher.platform_command(["qq", "discord"], "查仓库", "github", "github_repo")
async def handle_github_command(bot, event: MessageEvent):
    """
    处理命令调用：/查仓库 作者/仓库名
    
    Args:
        bot: 机器人对象
        event (MessageEvent): 消息事件对象
    """
    # 提取命令参数
    command_text = event.raw_message
    # 移除命令前缀和命令名
    prefix = command_text.split()[0] if command_text.split() else ""
    params = command_text[len(prefix):].strip()
    
    if not params:
        await event.reply("请输入仓库地址，格式：/查仓库 作者/仓库名")
        return
    
    # 解析参数格式
    if "/" in params:
        owner, repo = params.split("/", 1)
        # 移除可能的.git后缀
        repo = repo.replace(".git", "")
        await process_github_repo(event, owner, repo)
    else:
        await event.reply("参数格式错误，请输入：/查仓库 作者/仓库名")
