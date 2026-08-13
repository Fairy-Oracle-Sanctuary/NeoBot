# -*- coding: utf-8 -*-

from neobot.core.managers.command_manager import matcher
from neobot.models import MessageEvent
from .parsers.bili import BiliParser
from .parsers.douyin import DouyinParser
from .parsers.github import GitHubParser

# 插件元信息
__plugin_meta__ = {
    "name": "web_parser",
    "description": "自动解析各种Web链接，包括B站、抖音和GitHub仓库",
    "usage": "（自动触发）当检测到支持的链接时，自动进行解析"
}

# 初始化解析器实例
bili_parser = BiliParser()
douyin_parser = DouyinParser()
github_parser = GitHubParser()


@matcher.platform_message(["qq", "discord"], block=False)
async def handle_web_links(event: MessageEvent):
    """
    处理消息，检测并解析各种Web链接
    
    Args:
        event (MessageEvent): 消息事件对象
    """
    # 按顺序尝试各个解析器
    # 1. 尝试B站解析器
    await bili_parser.handle_message(event)
    
    # 2. 尝试抖音解析器
    await douyin_parser.handle_message(event)
    
    # 3. 尝试GitHub解析器
    await github_parser.handle_message(event)


# 注册GitHub仓库查询命令
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
        
        # 构建仓库URL
        repo_url = f"https://github.com/{owner}/{repo}"
        # 使用GitHub解析器处理
        await github_parser.process_url(event, repo_url)
    else:
        await event.reply("参数格式错误，请输入：/查仓库 作者/仓库名")
