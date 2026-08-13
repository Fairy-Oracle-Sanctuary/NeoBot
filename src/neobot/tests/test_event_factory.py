import pytest
from neobot.models.events.factory import EventFactory
from neobot.models.events.base import EventType
from neobot.models.events.message import GroupMessageEvent, PrivateMessageEvent
from neobot.models.events.notice import (
    FriendAddNoticeEvent, FriendRecallNoticeEvent, GroupRecallNoticeEvent,
    GroupIncreaseNoticeEvent, GroupDecreaseNoticeEvent, GroupAdminNoticeEvent,
    GroupBanNoticeEvent, GroupUploadNoticeEvent, PokeNotifyEvent,
    LuckyKingNotifyEvent, HonorNotifyEvent, GroupCardNoticeEvent,
    OfflineFileNoticeEvent, ClientStatusNoticeEvent, EssenceNoticeEvent,
    NotifyNoticeEvent
)
from neobot.models.events.request import FriendRequestEvent, GroupRequestEvent
from neobot.models.events.meta import HeartbeatEvent, LifeCycleEvent


class TestEventFactory:
    def test_create_private_message_event(self):
        """测试创建私聊消息事件。"""
        data = {
            "post_type": EventType.MESSAGE,
            "message_type": "private",
            "time": 1234567890,
            "self_id": 10000,
            "message_id": 123,
            "user_id": 20000,
            "message": [{"type": "text", "data": {"text": "Hello"}}],
            "raw_message": "Hello",
            "font": 12,
            "sender": {"user_id": 20000, "nickname": "TestUser"}
        }
        event = EventFactory.create_event(data)
        assert isinstance(event, PrivateMessageEvent)
        assert event.message_type == "private"
        assert event.user_id == 20000
        assert len(event.message) == 1
        assert event.message[0].type == "text"
        assert event.message[0].data["text"] == "Hello"

    def test_create_group_message_event(self):
        """测试创建群消息事件。"""
        data = {
            "post_type": EventType.MESSAGE,
            "message_type": "group",
            "time": 1234567890,
            "self_id": 10000,
            "message_id": 123,
            "user_id": 20000,
            "group_id": 30000,
            "message": [{"type": "text", "data": {"text": "Hello"}}],
            "raw_message": "Hello",
            "font": 12,
            "sender": {"user_id": 20000, "nickname": "TestUser", "role": "member"}
        }
        event = EventFactory.create_event(data)
        assert isinstance(event, GroupMessageEvent)
        assert event.message_type == "group"
        assert event.group_id == 30000
        assert event.user_id == 20000

    def test_create_group_message_with_anonymous(self):
        """测试创建匿名群消息事件。"""
        data = {
            "post_type": EventType.MESSAGE,
            "message_type": "group",
            "time": 1234567890,
            "self_id": 10000,
            "message_id": 123,
            "user_id": 20000,
            "group_id": 30000,
            "anonymous": {"id": 12345, "name": "Anonymous", "flag": "flag123"},
            "message": [{"type": "text", "data": {"text": "Hello"}}],
            "raw_message": "Hello",
            "font": 12,
            "sender": {"user_id": 20000, "nickname": "TestUser", "role": "member"}
        }
        event = EventFactory.create_event(data)
        assert isinstance(event, GroupMessageEvent)
        assert event.anonymous is not None
        assert event.anonymous.id == 12345
        assert event.anonymous.name == "Anonymous"
        assert event.anonymous.flag == "flag123"

    def test_create_friend_add_notice(self):
        """测试创建好友添加通知事件。"""
        data = {
            "post_type": EventType.NOTICE,
            "notice_type": "friend_add",
            "time": 1234567890,
            "self_id": 10000,
            "user_id": 20000
        }
        event = EventFactory.create_event(data)
        assert isinstance(event, FriendAddNoticeEvent)
        assert event.notice_type == "friend_add"
        assert event.user_id == 20000

    def test_create_friend_recall_notice(self):
        """测试创建好友消息撤回通知事件。"""
        data = {
            "post_type": EventType.NOTICE,
            "notice_type": "friend_recall",
            "time": 1234567890,
            "self_id": 10000,
            "user_id": 20000,
            "message_id": 123
        }
        event = EventFactory.create_event(data)
        assert isinstance(event, FriendRecallNoticeEvent)
        assert event.notice_type == "friend_recall"
        assert event.message_id == 123

    def test_create_group_recall_notice(self):
        """测试创建群消息撤回通知事件。"""
        data = {
            "post_type": EventType.NOTICE,
            "notice_type": "group_recall",
            "time": 1234567890,
            "self_id": 10000,
            "group_id": 30000,
            "user_id": 20000,
            "operator_id": 40000,
            "message_id": 123
        }
        event = EventFactory.create_event(data)
        assert isinstance(event, GroupRecallNoticeEvent)
        assert event.notice_type == "group_recall"
        assert event.group_id == 30000
        assert event.operator_id == 40000

    def test_create_group_increase_notice(self):
        """测试创建群成员增加通知事件。"""
        data = {
            "post_type": EventType.NOTICE,
            "notice_type": "group_increase",
            "time": 1234567890,
            "self_id": 10000,
            "group_id": 30000,
            "user_id": 20000,
            "operator_id": 40000,
            "sub_type": "approve"
        }
        event = EventFactory.create_event(data)
        assert isinstance(event, GroupIncreaseNoticeEvent)
        assert event.notice_type == "group_increase"
        assert event.sub_type == "approve"

    def test_create_group_decrease_notice(self):
        """测试创建群成员减少通知事件。"""
        data = {
            "post_type": EventType.NOTICE,
            "notice_type": "group_decrease",
            "time": 1234567890,
            "self_id": 10000,
            "group_id": 30000,
            "user_id": 20000,
            "operator_id": 40000,
            "sub_type": "kick"
        }
        event = EventFactory.create_event(data)
        assert isinstance(event, GroupDecreaseNoticeEvent)
        assert event.notice_type == "group_decrease"
        assert event.sub_type == "kick"

    def test_create_group_admin_notice(self):
        """测试创建群管理员变更通知事件。"""
        data = {
            "post_type": EventType.NOTICE,
            "notice_type": "group_admin",
            "time": 1234567890,
            "self_id": 10000,
            "group_id": 30000,
            "user_id": 20000,
            "sub_type": "set"
        }
        event = EventFactory.create_event(data)
        assert isinstance(event, GroupAdminNoticeEvent)
        assert event.notice_type == "group_admin"
        assert event.sub_type == "set"

    def test_create_group_ban_notice(self):
        """测试创建群成员禁言通知事件。"""
        data = {
            "post_type": EventType.NOTICE,
            "notice_type": "group_ban",
            "time": 1234567890,
            "self_id": 10000,
            "group_id": 30000,
            "user_id": 20000,
            "operator_id": 40000,
            "duration": 3600,
            "sub_type": "ban"
        }
        event = EventFactory.create_event(data)
        assert isinstance(event, GroupBanNoticeEvent)
        assert event.notice_type == "group_ban"
        assert event.duration == 3600

    def test_create_group_upload_notice(self):
        """测试创建群文件上传通知事件。"""
        data = {
            "post_type": EventType.NOTICE,
            "notice_type": "group_upload",
            "time": 1234567890,
            "self_id": 10000,
            "group_id": 30000,
            "user_id": 20000,
            "file": {"id": "file123", "name": "test.txt", "size": 1024, "busid": 1}
        }
        event = EventFactory.create_event(data)
        assert isinstance(event, GroupUploadNoticeEvent)
        assert event.notice_type == "group_upload"
        assert event.file.name == "test.txt"
        assert event.file.size == 1024

    def test_create_poke_notify_event(self):
        """测试创建戳一戳通知事件。"""
        data = {
            "post_type": EventType.NOTICE,
            "notice_type": "notify",
            "sub_type": "poke",
            "time": 1234567890,
            "self_id": 10000,
            "group_id": 30000,
            "user_id": 20000,
            "target_id": 40000
        }
        event = EventFactory.create_event(data)
        assert isinstance(event, PokeNotifyEvent)
        assert event.notice_type == "notify"
        assert event.sub_type == "poke"

    def test_create_lucky_king_notify_event(self):
        """测试创建运气王通知事件。"""
        data = {
            "post_type": EventType.NOTICE,
            "notice_type": "notify",
            "sub_type": "lucky_king",
            "time": 1234567890,
            "self_id": 10000,
            "group_id": 30000,
            "user_id": 20000,
            "target_id": 40000
        }
        event = EventFactory.create_event(data)
        assert isinstance(event, LuckyKingNotifyEvent)
        assert event.sub_type == "lucky_king"

    def test_create_honor_notify_event(self):
        """测试创建荣誉变更通知事件。"""
        data = {
            "post_type": EventType.NOTICE,
            "notice_type": "notify",
            "sub_type": "honor",
            "time": 1234567890,
            "self_id": 10000,
            "group_id": 30000,
            "user_id": 20000,
            "honor_type": "talkative"
        }
        event = EventFactory.create_event(data)
        assert isinstance(event, HonorNotifyEvent)
        assert event.sub_type == "honor"
        assert event.honor_type == "talkative"

    def test_create_unknown_notify_event(self):
        """测试创建未知类型的通知事件。"""
        data = {
            "post_type": EventType.NOTICE,
            "notice_type": "notify",
            "sub_type": "unknown",
            "time": 1234567890,
            "self_id": 10000,
            "user_id": 20000
        }
        event = EventFactory.create_event(data)
        assert isinstance(event, NotifyNoticeEvent)
        assert event.notice_type == "notify"
        assert event.sub_type == "unknown"

    def test_create_group_card_notice(self):
        """测试创建群名片变更通知事件。"""
        data = {
            "post_type": EventType.NOTICE,
            "notice_type": "group_card",
            "time": 1234567890,
            "self_id": 10000,
            "group_id": 30000,
            "user_id": 20000,
            "card_new": "NewCard",
            "card_old": "OldCard"
        }
        event = EventFactory.create_event(data)
        assert isinstance(event, GroupCardNoticeEvent)
        assert event.notice_type == "group_card"
        assert event.card_new == "NewCard"
        assert event.card_old == "OldCard"

    def test_create_offline_file_notice(self):
        """测试创建离线文件通知事件。"""
        data = {
            "post_type": EventType.NOTICE,
            "notice_type": "offline_file",
            "time": 1234567890,
            "self_id": 10000,
            "user_id": 20000,
            "file": {"name": "test.txt", "size": 1024, "url": "http://example.com/test.txt"}
        }
        event = EventFactory.create_event(data)
        assert isinstance(event, OfflineFileNoticeEvent)
        assert event.notice_type == "offline_file"
        assert event.file.name == "test.txt"

    def test_create_client_status_notice(self):
        """测试创建客户端状态通知事件。"""
        data = {
            "post_type": EventType.NOTICE,
            "notice_type": "client_status",
            "time": 1234567890,
            "self_id": 10000,
            "client": {"online": True, "status": "normal"}
        }
        event = EventFactory.create_event(data)
        assert isinstance(event, ClientStatusNoticeEvent)
        assert event.notice_type == "client_status"
        assert event.client.online is True

    def test_create_essence_notice(self):
        """测试创建精华消息通知事件。"""
        data = {
            "post_type": EventType.NOTICE,
            "notice_type": "essence",
            "time": 1234567890,
            "self_id": 10000,
            "group_id": 30000,
            "sender_id": 20000,
            "operator_id": 40000,
            "message_id": 123,
            "sub_type": "add"
        }
        event = EventFactory.create_event(data)
        assert isinstance(event, EssenceNoticeEvent)
        assert event.notice_type == "essence"
        assert event.sub_type == "add"

    def test_create_friend_request_event(self):
        """测试创建好友请求事件。"""
        data = {
            "post_type": EventType.REQUEST,
            "request_type": "friend",
            "time": 1234567890,
            "self_id": 10000,
            "user_id": 20000,
            "comment": "Hello",
            "flag": "flag123"
        }
        event = EventFactory.create_event(data)
        assert isinstance(event, FriendRequestEvent)
        assert event.request_type == "friend"
        assert event.comment == "Hello"

    def test_create_group_request_event(self):
        """测试创建群请求事件。"""
        data = {
            "post_type": EventType.REQUEST,
            "request_type": "group",
            "sub_type": "add",
            "time": 1234567890,
            "self_id": 10000,
            "group_id": 30000,
            "user_id": 20000,
            "comment": "Hello",
            "flag": "flag123"
        }
        event = EventFactory.create_event(data)
        assert isinstance(event, GroupRequestEvent)
        assert event.request_type == "group"
        assert event.sub_type == "add"

    def test_create_heartbeat_event(self):
        """测试创建心跳元事件。"""
        data = {
            "post_type": EventType.META,
            "meta_event_type": "heartbeat",
            "time": 1234567890,
            "self_id": 10000,
            "status": {"online": True, "good": True},
            "interval": 1000
        }
        event = EventFactory.create_event(data)
        assert isinstance(event, HeartbeatEvent)
        assert event.meta_event_type == "heartbeat"
        assert event.status.online is True
        assert event.interval == 1000

    def test_create_lifecycle_event(self):
        """测试创建生命周期元事件。"""
        data = {
            "post_type": EventType.META,
            "meta_event_type": "lifecycle",
            "time": 1234567890,
            "self_id": 10000,
            "sub_type": "enable"
        }
        event = EventFactory.create_event(data)
        assert isinstance(event, LifeCycleEvent)
        assert event.meta_event_type == "lifecycle"
        assert event.sub_type == "enable"

    def test_create_unknown_event_type(self):
        """测试创建未知类型事件时抛出异常。"""
        data = {
            "post_type": "unknown",
            "time": 1234567890,
            "self_id": 10000
        }
        with pytest.raises(ValueError, match="Unknown event type: unknown"):
            EventFactory.create_event(data)

    def test_create_unknown_message_type(self):
        """测试创建未知消息类型时抛出异常。"""
        data = {
            "post_type": EventType.MESSAGE,
            "message_type": "unknown",
            "time": 1234567890,
            "self_id": 10000,
            "message": "Hello"
        }
        with pytest.raises(ValueError, match="Unknown message type: unknown"):
            EventFactory.create_event(data)
