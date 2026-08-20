"""
neobot.plugin_api —— 插件 API 契约 (plugin-api-v1)
====================================================

这是插件与框架之间**唯一**的公开契约命名空间。

规则
----
1. 插件只允许 import 本命名空间(``neobot.plugin_api``)内的公开接口,
   以及 ``neobot.models``(纯数据模型)与同级插件(``neobot.plugins``)。
2. 禁止直接 import ``neobot.core.*`` / ``neobot.adapters.*`` —— 它们是内部实现,
   不保证 API 稳定。加载器会对源码做边界检查,违规的**新式契约插件**将被拒绝加载。
3. 声明 ``plugin_manifest = define_plugin(...)``(见 :mod:`neobot.plugin_api.manifest`)
   即视为新式契约插件;只写旧式 ``__plugin_meta__`` 的插件保持兼容,但建议迁移。
4. 契约版本见 :data:`API_VERSION`。框架升级时保证向后兼容,不兼容变更会提升
   契约大版本并提供迁移工具。

快速开始::

    from neobot.plugin_api import (
        define_plugin, command, MessageEvent, Bot, ModuleLogger,
    )

    plugin_manifest = define_plugin(
        name="my_plugin",
        description="示例插件",
        usage="/hello - 打招呼",
        version="0.1.0",
        author="镀铬酸钾",
    )

    logger = ModuleLogger("MyPlugin")

    @command("hello")
    async def handle_hello(bot: Bot, event: MessageEvent, args: list[str]):
        await event.reply("你好！")

版本
----
- :data:`__version__`:契约实现版本(随框架发布,遵循 semver)。
- :data:`API_VERSION`:契约级别(如 "1"),插件 manifest 中声明。
"""
from __future__ import annotations

from neobot.plugin_api.bot import Bot
from neobot.plugin_api.config import global_config
from neobot.plugin_api.decorators import (
    command,
    on_message,
    on_notice,
    on_request,
    platform_command,
    platform_message,
)
from neobot.plugin_api.events import (
    Anonymous,
    ClientStatus,
    ClientStatusNoticeEvent,
    CurrentTalkative,
    EssenceMessage,
    EssenceNoticeEvent,
    EventType,
    FriendAddNoticeEvent,
    FriendInfo,
    FriendRecallNoticeEvent,
    FriendRequestEvent,
    GroupAdminNoticeEvent,
    GroupBanNoticeEvent,
    GroupCardNoticeEvent,
    GroupDecreaseNoticeEvent,
    GroupHonorInfo,
    GroupIncreaseNoticeEvent,
    GroupInfo,
    GroupMemberInfo,
    GroupNoticeEvent,
    GroupRecallNoticeEvent,
    GroupRequestEvent,
    GroupUploadFile,
    GroupUploadNoticeEvent,
    HeartbeatEvent,
    HeartbeatStatus,
    HonorInfo,
    HonorNotifyEvent,
    LifeCycleEvent,
    LifeCycleSubType,
    LoginInfo,
    LuckyKingNotifyEvent,
    MessageEvent,
    MetaEvent,
    NoticeEvent,
    NotifyNoticeEvent,
    OfflineFile,
    OfflineFileNoticeEvent,
    OneBotEvent,
    PokeNotifyEvent,
    PrivateMessageEvent,
    RequestEvent,
    Sender,
    Status,
    StrangerInfo,
    VersionInfo,
    GroupMessageEvent,
)
from neobot.plugin_api.logger import ModuleLogger, logger
from neobot.plugin_api.manifest import (
    API_VERSION,
    PluginManifest,
    PluginManifestError,
    define_plugin,
    resolve_manifest,
)
from neobot.plugin_api.mcc import (
    McpAdapter,
    McpAdapterDisabledError,
    McpAdapterManager,
    McpAuthError,
    McpError,
    McpTimeoutError,
    McpToolError,
    McpUnreachableError,
    MccServiceClient,
    mcc,
    mcc_manager,
)
from neobot.plugin_api.message import MessageSegment, PlatformMessage, PlatformSegment
from neobot.plugin_api.permission import Permission
from neobot.plugin_api.plugin import Plugin, SimplePlugin
from neobot.plugin_api.services import (
    bot_manager,
    download_to_local,
    get_local_file_server,
    image_manager,
    message_bus,
    permission_manager,
    redis_manager,
    require_admin,
    run_in_thread_pool,
)
from neobot.plugin_api.validator import InputValidator, input_validator

#: 契约实现版本(随框架发布,遵循 semver)。
__version__ = "1.0.0"

__all__ = [
    # 版本
    "API_VERSION",
    "__version__",
    # manifest
    "PluginManifest",
    "PluginManifestError",
    "define_plugin",
    "resolve_manifest",
    # 注册装饰器
    "command",
    "platform_command",
    "on_message",
    "platform_message",
    "on_notice",
    "on_request",
    # 模型与消息
    "MessageSegment",
    "PlatformMessage",
    "PlatformSegment",
    "Bot",
    "Permission",
    "Sender",
    # 基类
    "Plugin",
    "SimplePlugin",
    # MCC 适配
    "mcc",
    "mcc_manager",
    "McpAdapter",
    "McpAdapterManager",
    "MccServiceClient",
    "McpAdapterDisabledError",
    "McpError",
    "McpAuthError",
    "McpTimeoutError",
    "McpToolError",
    "McpUnreachableError",
    # 服务
    "redis_manager",
    "image_manager",
    "bot_manager",
    "permission_manager",
    "require_admin",
    "message_bus",
    "download_to_local",
    "get_local_file_server",
    "run_in_thread_pool",
    "input_validator",
    "InputValidator",
    # 配置 / 日志
    "global_config",
    "logger",
    "ModuleLogger",
    # 事件模型(与 neobot.plugin_api.events 保持一致)
    "EventType",
    "OneBotEvent",
    "MessageEvent",
    "PrivateMessageEvent",
    "GroupMessageEvent",
    "MetaEvent",
    "HeartbeatEvent",
    "HeartbeatStatus",
    "LifeCycleEvent",
    "LifeCycleSubType",
    "NoticeEvent",
    "FriendAddNoticeEvent",
    "FriendRecallNoticeEvent",
    "GroupNoticeEvent",
    "GroupRecallNoticeEvent",
    "GroupIncreaseNoticeEvent",
    "GroupDecreaseNoticeEvent",
    "GroupAdminNoticeEvent",
    "GroupBanNoticeEvent",
    "GroupUploadFile",
    "GroupUploadNoticeEvent",
    "NotifyNoticeEvent",
    "PokeNotifyEvent",
    "LuckyKingNotifyEvent",
    "HonorNotifyEvent",
    "GroupCardNoticeEvent",
    "OfflineFile",
    "OfflineFileNoticeEvent",
    "ClientStatus",
    "ClientStatusNoticeEvent",
    "EssenceNoticeEvent",
    "RequestEvent",
    "FriendRequestEvent",
    "GroupRequestEvent",
    "GroupInfo",
    "GroupMemberInfo",
    "FriendInfo",
    "StrangerInfo",
    "LoginInfo",
    "VersionInfo",
    "Status",
    "EssenceMessage",
    "CurrentTalkative",
    "HonorInfo",
    "GroupHonorInfo",
    "Anonymous",
]
