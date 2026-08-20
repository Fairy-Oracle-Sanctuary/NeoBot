"""
事件模型 —— 插件 API 契约 (plugin-api-v1)。

数据模型类,与 ``neobot.models`` 中定义的模型为同一对象(直接转发),
插件侧统一从契约命名空间导入,避免依赖内部模块路径。
"""
from __future__ import annotations

from neobot.models.events.base import EventType, OneBotEvent
from neobot.models.events.message import (
    Anonymous,
    GroupMessageEvent,
    MessageEvent,
    PrivateMessageEvent,
)
from neobot.models.events.meta import (
    HeartbeatEvent,
    HeartbeatStatus,
    LifeCycleEvent,
    LifeCycleSubType,
    MetaEvent,
)
from neobot.models.events.notice import (
    ClientStatus,
    ClientStatusNoticeEvent,
    EssenceNoticeEvent,
    FriendAddNoticeEvent,
    FriendRecallNoticeEvent,
    GroupAdminNoticeEvent,
    GroupBanNoticeEvent,
    GroupCardNoticeEvent,
    GroupDecreaseNoticeEvent,
    GroupIncreaseNoticeEvent,
    GroupNoticeEvent,
    GroupRecallNoticeEvent,
    GroupUploadFile,
    GroupUploadNoticeEvent,
    HonorNotifyEvent,
    LuckyKingNotifyEvent,
    NoticeEvent,
    NotifyNoticeEvent,
    OfflineFile,
    OfflineFileNoticeEvent,
    PokeNotifyEvent,
)
from neobot.models.events.request import (
    FriendRequestEvent,
    GroupRequestEvent,
    RequestEvent,
)
from neobot.models.objects import (
    CurrentTalkative,
    EssenceMessage,
    FriendInfo,
    GroupHonorInfo,
    GroupInfo,
    GroupMemberInfo,
    HonorInfo,
    LoginInfo,
    Status,
    StrangerInfo,
    VersionInfo,
)
from neobot.models.sender import Sender

__all__ = [
    # base
    "EventType",
    "OneBotEvent",
    # message
    "Anonymous",
    "MessageEvent",
    "PrivateMessageEvent",
    "GroupMessageEvent",
    # meta
    "MetaEvent",
    "HeartbeatEvent",
    "HeartbeatStatus",
    "LifeCycleEvent",
    "LifeCycleSubType",
    # notice
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
    # request
    "RequestEvent",
    "FriendRequestEvent",
    "GroupRequestEvent",
    # objects
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
    # sender
    "Sender",
]
