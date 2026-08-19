"""
版本查询插件

提供 /ver 指令：
- 读取构建时写入的版本哈希（/app/versions）
- 查询 GitHub 仓库 main 分支的最新提交哈希、提交内容与提交人（GitHub API，5 分钟缓存）
- 对比并提示是否已是最新

/versions 和 /ver 均可使用（别名）。

"""
import os
from typing import Optional

import aiohttp

from cachetools import TTLCache

from neobot.core.managers.command_manager import matcher
from neobot.core.bot import Bot
from neobot.core.utils.logger import logger
from neobot.models.events.message import MessageEvent

__plugin_meta__ = {
    "name": "version",
    "description": "查询当前版本哈希与 GitHub 最新提交（/ver）",
    "usage": "/ver - 查看当前版本与 GitHub 最新提交\n/versions - 同 /ver",
}

# 版本文件路径（Dockerfile 构建时写入）
VERSION_FILE = "/app/versions"
# 兜底：老镜像的 commit-sha 文件
_COMMIT_SHA_FILE = "/app/commit-sha"

# GitHub 仓库与 API（公开仓库无需 token，60 次/小时限流，缓存 5 分钟）
_GITHUB_REPO = "Fairy-Oracle-Sanctuary/NeoBot"
_GITHUB_API = f"https://api.github.com/repos/{_GITHUB_REPO}/commits/main"
_remote_cache = TTLCache(maxsize=1, ttl=300)


def _read_version_file() -> str:
    """读取版本文件内容，优先 /app/versions，其次 /app/commit-sha。"""
    for path in (VERSION_FILE, _COMMIT_SHA_FILE):
        try:
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as f:
                    content = f.read().strip()
                if content:
                    return content
        except Exception:
            continue
    return ""


async def _get_remote_commit() -> dict:
    """
    查询 GitHub main 分支最新提交信息。

    Returns:
        {"sha": str, "message": str, "author": str}；查询失败返回空 dict。
    """
    cached = _remote_cache.get("commit")
    if isinstance(cached, dict) and cached:
        return cached
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(_GITHUB_API, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    sha = (data or {}).get("sha", "")
                    if sha:
                        commit = data.get("commit") or {}
                        message = ((commit.get("message") or "").strip().splitlines() or [""])[0]
                        author = (
                            (commit.get("author") or {}).get("name")
                            or (data.get("author") or {}).get("login")
                            or ""
                        )
                        info = {"sha": sha, "message": message, "author": author}
                        _remote_cache["commit"] = info
                        return info
                else:
                    logger.warning(f"[version] GitHub API 返回 {resp.status}")
    except Exception as e:
        logger.warning(f"[version] GitHub API 查询失败: {type(e).__name__}: {e}")
    return {}


def _escape_reply(text: Optional[str]) -> Optional[str]:
    """
    清洗将拼进聊天回复的文本：转义反引号，防止异常 commit 消息破坏格式。

    GitHub commit 消息内容不受本项目控制，可能包含反引号/换行等特殊字符；
    回复用 `...` 包裹 hash，消息体若有反引号会导致格式错乱。
    """
    if not text:
        return text
    return text.replace("`", "\\`").replace("\r", " ").replace("\n", " ")


@matcher.platform_command(["qq", "discord"], "ver")
async def handle_ver(bot: Bot, event: MessageEvent, args: list[str]):
    """处理 /ver 指令，返回本地版本哈希与 GitHub 最新提交。"""
    local = _read_version_file()
    remote = await _get_remote_commit()

    lines = []
    if local:
        lines.append(f"🔖 当前版本：`{local}`")
    else:
        lines.append("❌ 无法获取版本信息（镜像中未写入版本文件）")

    if remote.get("sha"):
        if not local:
            status = "（本地版本未知，无法对比）"
        elif local == remote["sha"]:
            status = "✅ 已是最新"
        else:
            status = "🔄 有新版本，等待自动部署"
        lines.append(f"🌐 GitHub 最新：`{remote['sha']}` {status}")
        if remote.get("message"):
            lines.append(f"📝 提交内容：{_escape_reply(remote['message'])}")
        if remote.get("author"):
            lines.append(f"👤 提交人：{_escape_reply(remote['author'])}")
    else:
        lines.append("🌐 GitHub 最新：查询失败（网络异常或限流，稍后再试）")

    await event.reply("\n".join(lines))


@matcher.platform_command(["qq", "discord"], "versions")
async def handle_versions(bot: Bot, event: MessageEvent, args: list[str]):
    """/versions 别名，行为与 /ver 相同。"""
    await handle_ver(bot, event, args)
