# -*- coding: utf-8 -*-
"""
NeoBot CLI 调试入口

使用命令行交互模式运行机器人，无需 WebSocket 连接。
所有 Bot 输出将打印到终端。
"""
import asyncio
import os
import sys

# ── 路径初始化（必须在 neobot 模块导入之前） ──
ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
SRC_DIR = os.path.join(ROOT_DIR, "src")
sys.path.insert(0, SRC_DIR)

# 初始化日志系统
from neobot.core.utils.logger import logger

# 插件管理器（加载插件时会触发 matcher 注册命令/消息处理器）
from neobot.core.managers import plugin_manager
from neobot.adapters.cli_adapter import CLIDebugger


@logger.catch
async def main():
    """主函数：加载插件 → 启动 CLI 交互循环。"""
    # 加载所有插件（注册命令和消息处理器）
    plugin_manager.load_all_plugins()

    # 启动 CLI 调试器
    debugger = CLIDebugger()
    await debugger.run()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
