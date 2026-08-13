# -*- coding: utf-8 -*-
import re
import aiohttp
from typing import Optional, Dict, Any, List
from cachetools import TTLCache

from neobot.core.utils.logger import logger
from neobot.core.managers.image_manager import image_manager
from neobot.models import MessageEvent, MessageSegment
from ..base import BaseParser


class GitHubParser(BaseParser):
    """
    GitHub仓库解析器
    """

    # GitHub 解析不需要表情回应反馈
    react_ok_on_handle = False
    
    def __init__(self):
        super().__init__()
        self.name = "GitHub解析器"
        self.url_pattern = re.compile(r"https?://(?:www\.)?github\.com/([\w\-]+)/([\w\-\.]+)(?:/[^\s]*)?")
        self.nickname = "GitHub仓库信息"
        # 消息去重缓存
        self.processed_messages: TTLCache[int, bool] = TTLCache(maxsize=100, ttl=10)
        # 缓存GitHub API响应，避免频繁请求
        self.api_cache = TTLCache(maxsize=100, ttl=3600)  # 100个缓存项，1小时过期
    
    async def parse(self, url: str) -> Optional[Dict[str, Any]]:
        """
        解析GitHub仓库信息
        
        Args:
            url (str): GitHub仓库URL
            
        Returns:
            Optional[Dict[str, Any]]: 仓库信息字典，如果失败则返回None
        """
        # 从URL中提取owner和repo
        match = self.url_pattern.search(url)
        if not match:
            return None
        
        owner = match.group(1)
        repo = match.group(2)
        # 移除可能的.git后缀
        repo = repo.replace(".git", "")
        
        return await self.get_github_repo_info(owner, repo)
    
    async def get_real_url(self, short_url: str) -> Optional[str]:
        """
        获取短链接的真实URL
        
        Args:
            short_url (str): 短链接
            
        Returns:
            Optional[str]: 真实URL，如果失败则返回None
        """
        try:
            session = self.get_session()
            async with session.head(short_url, headers=self.HEADERS, allow_redirects=False, timeout=aiohttp.ClientTimeout(total=5)) as response:
                if response.status == 302:
                    return response.headers.get('Location')
        except Exception as e:
            logger.error(f"[{self.name}] 获取真实URL失败: {e}")
        return None
    
    async def get_github_repo_info(self, owner: str, repo: str) -> Optional[Dict[str, Any]]:
        """
        通过GitHub API获取仓库信息
        
        Args:
            owner (str): 仓库所有者用户名
            repo (str): 仓库名称
            
        Returns:
            Optional[Dict[str, Any]]: 仓库信息字典，如果失败则返回None
        """
        cache_key = f"{owner}/{repo}"
        if cache_key in self.api_cache:
            logger.info(f"[{self.name}] 使用缓存的仓库信息: {cache_key}")
            return self.api_cache[cache_key]
        
        api_url = f"https://api.github.com/repos/{owner}/{repo}"
        try:
            session = self.get_session()
            async with session.get(api_url, timeout=aiohttp.ClientTimeout(total=10)) as response:
                response.raise_for_status()
                repo_data = await response.json()
                
                # 将数据存入缓存
                self.api_cache[cache_key] = repo_data
                logger.info(f"[{self.name}] 成功获取仓库信息并缓存: {cache_key}")
                return repo_data
                
        except aiohttp.ClientError as e:
            logger.error(f"[{self.name}] GitHub API请求失败: {e}")
        except ValueError as e:
            logger.error(f"[{self.name}] 解析GitHub API响应失败: {e}")
        except Exception as e:
            logger.error(f"[{self.name}] 获取仓库信息时发生未知错误: {e}")
        
        return None
    
    async def generate_repo_image(self, repo_data: Dict[str, Any]) -> Optional[str]:
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
                quality=100,
                image_type="png"
            )
            
            return base64_image
            
        except Exception as e:
            logger.error(f"[{self.name}] 生成仓库信息图片失败: {e}")
            return None
    
    async def format_response(self, event: MessageEvent, data: Dict[str, Any]) -> List[Any]:
        """
        格式化GitHub仓库响应消息
        
        Args:
            event (MessageEvent): 消息事件对象
            data (Dict[str, Any]): 仓库信息
            
        Returns:
            List[Any]: 消息段列表
        """
        nodes = []
        
        # 生成图片
        image_base64 = await self.generate_repo_image(data)
        if image_base64:
            # 发送图片
            image_node = event.bot.build_forward_node(
                user_id=event.self_id, 
                nickname=self.nickname, 
                message=MessageSegment.image(image_base64)
            )
            nodes.append(image_node)
        else:
            # 如果图片生成失败，发送文本信息
            text_message = (
                f"GitHub 仓库信息\n"
                f"--------------------\n"
                f"仓库: {data.get('full_name', '')}\n"
                f"描述: {data.get('description', '暂无描述')}\n"
                f"--------------------\n"
                f"数据:\n"
                f"   星标: {data.get('stargazers_count', 0)}\n"
                f"   Fork: {data.get('forks_count', 0)}\n"
                f"   Issues: {data.get('open_issues_count', 0)}\n"
                f"   关注: {data.get('watchers_count', 0)}\n"
            )
            text_node = event.bot.build_forward_node(
                user_id=event.self_id, 
                nickname=self.nickname, 
                message=text_message
            )
            nodes.append(text_node)
        
        return nodes
    
    def should_handle_url(self, url: str) -> bool:
        """
        判断是否应该处理该URL
        
        Args:
            url (str): URL
            
        Returns:
            bool: 是否应该处理
        """
        # 检查是否是GitHub相关域名
        return bool(self.url_pattern.search(url)) and 'github.com' in url
