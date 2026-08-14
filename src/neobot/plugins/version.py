"""
版本查询插件

提供 /ver 指令：读取构建时写入的版本哈希（/app/versions）。
/versions 和 /ver 均可使用（别名）。

版本哈希由 GitHub Actions 构建时通过 COMMIT_SHA 写入 Dockerfile 生成。
"""
import os

from neobot.core.managers.command_manager import matcher
from neobot.core.bot import Bot
from neobot.models.events.message import MessageEvent

__plugin_meta__ = {
    "name": "version",
    "description": "查询当前版本哈希（/ver）",
    "usage": "/ver - 查看当前运行的版本哈希\n/versions - 同 /ver",
}

# 版本文件路径（Dockerfile 构建时写入）
VERSION_FILE = "/app/versions"
# 兜底：老镜像的 commit-sha 文件
_COMMIT_SHA_FILE = "/app/commit-sha"


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


@matcher.platform_command(["qq", "discord"], "ver")
async def handle_ver(bot: Bot, event: MessageEvent, args: list[str]):
    """处理 /ver 指令，返回版本哈希。"""
    version = _read_version_file()
    if version:
        await event.reply(f"🔖 当前版本：`{version}`")
    else:
        await event.reply("❌ 无法获取版本信息（镜像中未写入版本文件）")


@matcher.platform_command(["qq", "discord"], "versions")
async def handle_versions(bot: Bot, event: MessageEvent, args: list[str]):
    """/versions 别名，行为与 /ver 相同。"""
    await handle_ver(bot, event, args)
