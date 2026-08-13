import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import json

# Import all API classes
from neobot.core.api.base import BaseAPI
from neobot.core.api.account import AccountAPI
from neobot.core.api.friend import FriendAPI
from neobot.core.api.group import GroupAPI
from neobot.core.api.media import MediaAPI
from neobot.core.api.message import MessageAPI
from neobot.models.objects import (
    LoginInfo, VersionInfo, Status
)
from neobot.models.message import MessageSegment


# Fixture for a mock websocket client
@pytest.fixture
def mock_ws():
    """模拟一个 WebSocket 客户端。"""
    return AsyncMock()

# Fixture for a comprehensive API client instance
@pytest.fixture
def api_client(mock_ws):
    """
    创建一个包含所有 API Mixin 的测试客户端实例。
    
    Args:
        mock_ws: 模拟的 WebSocket 客户端。
    
    Returns:
        一个功能完备的 API 客户端实例。
    """
    # Combine all mixins into one class for testing
    class FullAPI(AccountAPI, FriendAPI, GroupAPI, MediaAPI, MessageAPI):
        def __init__(self, ws_client, self_id):
            super().__init__(ws_client, self_id)

    return FullAPI(mock_ws, 12345)


# --- Test BaseAPI ---
@pytest.mark.asyncio
async def test_base_api_call_success(mock_ws):
    """测试 BaseAPI 成功调用。"""
    base_api = BaseAPI(mock_ws, 12345)
    mock_ws.call_api.return_value = {"status": "ok", "data": {"key": "value"}}
    
    result = await base_api.call_api("test_action", {"param": 1})
    
    mock_ws.call_api.assert_called_once_with("test_action", {"param": 1})
    assert result == {"key": "value"}

@pytest.mark.asyncio
async def test_base_api_call_failed_status(mock_ws):
    """测试 BaseAPI 调用返回失败状态。"""
    base_api = BaseAPI(mock_ws, 12345)
    mock_ws.call_api.return_value = {"status": "failed", "data": None}
    
    result = await base_api.call_api("test_action")
    
    assert result is None

@pytest.mark.asyncio
async def test_base_api_call_exception(mock_ws):
    """测试 BaseAPI 调用时发生异常。"""
    base_api = BaseAPI(mock_ws, 12345)
    mock_ws.call_api.side_effect = Exception("Network error")
    
    with pytest.raises(Exception, match="Network error"):
        await base_api.call_api("test_action")


# --- Test AccountAPI ---
@pytest.mark.asyncio
async def test_get_login_info_no_cache(api_client):
    """测试 get_login_info 在无缓存时能正确调用 API 并设置缓存。"""
    api_client.call_api = AsyncMock(return_value={"user_id": 123, "nickname": "test"})
    with patch("neobot.core.managers.redis_manager.redis_manager.get", new_callable=AsyncMock) as mock_redis_get, \
         patch("neobot.core.managers.redis_manager.redis_manager.set", new_callable=AsyncMock) as mock_redis_set:
        mock_redis_get.return_value = None
        
        info = await api_client.get_login_info()
        
        api_client.call_api.assert_called_once_with("get_login_info")
        mock_redis_set.assert_called_once()
        assert isinstance(info, LoginInfo)
        assert info.user_id == 123

@pytest.mark.asyncio
async def test_get_login_info_with_cache(api_client):
    """测试 get_login_info 在有缓存时直接返回缓存数据。"""
    cached_data = json.dumps({"user_id": 123, "nickname": "test"})
    api_client.call_api = AsyncMock()
    with patch("neobot.core.managers.redis_manager.redis_manager.get", new_callable=AsyncMock) as mock_redis_get:
        mock_redis_get.return_value = cached_data
        
        info = await api_client.get_login_info()
        
        api_client.call_api.assert_not_called()
        assert isinstance(info, LoginInfo)
        assert info.user_id == 123

@pytest.mark.asyncio
async def test_get_version_info(api_client):
    """测试 get_version_info 能正确解析 API 返回。"""
    api_client.call_api = AsyncMock(return_value={"app_name": "test_app", "app_version": "1.0", "protocol_version": "v11"})
    info = await api_client.get_version_info()
    assert isinstance(info, VersionInfo)
    assert info.app_name == "test_app"

@pytest.mark.asyncio
async def test_get_status(api_client):
    """测试 get_status 能正确解析 API 返回。"""
    api_client.call_api = AsyncMock(return_value={"online": True, "good": True})
    status = await api_client.get_status()
    assert isinstance(status, Status)
    assert status.online is True

# --- Test FriendAPI ---
@pytest.mark.asyncio
async def test_send_like(api_client):
    """测试 send_like 方法能正确调用 API。"""
    api_client.call_api = AsyncMock()
    await api_client.send_like(54321, 5)
    api_client.call_api.assert_called_once_with("send_like", {"user_id": 54321, "times": 5})

@pytest.mark.asyncio
async def test_set_friend_add_request(api_client):
    """测试 set_friend_add_request 方法能正确调用 API。"""
    api_client.call_api = AsyncMock()
    await api_client.set_friend_add_request("flag_test", approve=False)
    api_client.call_api.assert_called_once_with("set_friend_add_request", {"flag": "flag_test", "approve": False, "remark": ""})

# --- Test GroupAPI ---
@pytest.mark.asyncio
async def test_set_group_kick(api_client):
    """测试 set_group_kick 方法能正确调用 API。"""
    api_client.call_api = AsyncMock()
    await api_client.set_group_kick(111, 222, True)
    api_client.call_api.assert_called_once_with("set_group_kick", {"group_id": 111, "user_id": 222, "reject_add_request": True})

@pytest.mark.asyncio
async def test_set_group_anonymous_ban(api_client):
    """测试 set_group_anonymous_ban 方法能正确调用 API。"""
    api_client.call_api = AsyncMock()
    await api_client.set_group_anonymous_ban(111, flag="anon_flag")
    api_client.call_api.assert_called_once_with("set_group_anonymous_ban", {"group_id": 111, "duration": 1800, "flag": "anon_flag"})

# --- Test MediaAPI ---
@pytest.mark.asyncio
async def test_can_send_image(api_client):
    """测试 can_send_image 方法能正确调用 API。"""
    api_client.call_api = AsyncMock()
    await api_client.can_send_image()
    api_client.call_api.assert_called_once_with(action="can_send_image")

@pytest.mark.asyncio
async def test_get_image(api_client):
    """测试 get_image 方法能正确调用 API。"""
    api_client.call_api = AsyncMock()
    await api_client.get_image("file.jpg")
    api_client.call_api.assert_called_once_with(action="get_image", params={"file": "file.jpg"})

# --- Test MessageAPI ---
@pytest.mark.asyncio
async def test_send_group_msg_str(api_client):
    """测试 send_group_msg 发送字符串消息。"""
    api_client.call_api = AsyncMock()
    await api_client.send_group_msg(111, "hello")
    api_client.call_api.assert_called_once_with("send_group_msg", {"group_id": 111, "message": "hello", "auto_escape": False})

@pytest.mark.asyncio
async def test_send_group_msg_segment(api_client):
    """测试 send_group_msg 发送单个消息段。"""
    api_client.call_api = AsyncMock()
    segment = MessageSegment.text("hello")
    await api_client.send_group_msg(111, segment)
    api_client.call_api.assert_called_once_with("send_group_msg", {"group_id": 111, "message": [{"type": "text", "data": {"text": "hello"}}], "auto_escape": False})

@pytest.mark.asyncio
async def test_send_group_msg_list_segments(api_client):
    """测试 send_group_msg 发送消息段列表。"""
    api_client.call_api = AsyncMock()
    segments = [MessageSegment.text("hello"), MessageSegment.image("file.jpg")]
    await api_client.send_group_msg(111, segments)
    api_client.call_api.assert_called_once_with("send_group_msg", {"group_id": 111, "message": [
        {"type": "text", "data": {"text": "hello"}},
        {"type": "image", "data": {"file": "file.jpg", "cache": "1", "proxy": "1"}}
    ], "auto_escape": False})

@pytest.mark.asyncio
async def test_send_reply(api_client):
    """测试 send 方法在事件有 reply 方法时优先调用 reply。"""
    mock_event = MagicMock()
    mock_event.reply = AsyncMock()
    # 确保没有 user_id 和 group_id，以验证 reply 路径被优先选择
    delattr(mock_event, "user_id")
    delattr(mock_event, "group_id")
    
    await api_client.send(mock_event, "hello reply")
    mock_event.reply.assert_called_once_with("hello reply", False)

@pytest.mark.asyncio
async def test_send_auto_private(api_client):
    """测试 send 方法能根据事件自动判断并发送私聊消息。"""
    mock_event = MagicMock()
    mock_event.user_id = 123
    delattr(mock_event, "group_id") # 确保没有 group_id
    delattr(mock_event, "reply")    # 确保没有 reply 方法
    
    api_client.send_private_msg = AsyncMock()
    await api_client.send(mock_event, "hello private")
    api_client.send_private_msg.assert_called_once_with(123, "hello private", False)

@pytest.mark.asyncio
async def test_send_auto_group(api_client):
    """测试 send 方法能根据事件自动判断并发送群聊消息。"""
    mock_event = MagicMock()
    mock_event.user_id = 123
    mock_event.group_id = 456
    delattr(mock_event, "reply")
    
    api_client.send_group_msg = AsyncMock()
    await api_client.send(mock_event, "hello group")
    api_client.send_group_msg.assert_called_once_with(456, "hello group", False)

@pytest.mark.asyncio
async def test_get_forward_msg_valid(api_client):
    """测试 get_forward_msg 能正确解析有效的合并转发消息。"""
    api_client.call_api = AsyncMock(return_value={"data": [{"content": "node1"}]})
    nodes = await api_client.get_forward_msg("forward_id")
    assert nodes == [{"content": "node1"}]

@pytest.mark.asyncio
async def test_get_forward_msg_nested(api_client):
    """测试 get_forward_msg 能正确解析嵌套在 'messages' 键下的消息。"""
    api_client.call_api = AsyncMock(return_value={"data": {"messages": [{"content": "node2"}]}})
    nodes = await api_client.get_forward_msg("forward_id_nested")
    assert nodes == [{"content": "node2"}]

@pytest.mark.asyncio
async def test_get_forward_msg_invalid(api_client):
    """测试 get_forward_msg 在无效数据结构下抛出异常。"""
    api_client.call_api = AsyncMock(return_value={"data": "not a list or dict"})
    with pytest.raises(ValueError):
        await api_client.get_forward_msg("forward_id_invalid")
