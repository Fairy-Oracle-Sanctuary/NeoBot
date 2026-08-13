import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from neobot.core.ws import WS
from neobot.core.bot import Bot


class TestWS:
    @pytest.mark.asyncio
    async def test_ws_initialization(self):
        """测试 WS 类初始化。"""
        # 模拟全局配置
        with patch('neobot.core.ws.global_config') as mock_config:
            mock_config.napcat_ws.uri = "ws://localhost:8080"
            mock_config.napcat_ws.token = "test_token"
            mock_config.napcat_ws.reconnect_interval = 5
            
            ws = WS()
            assert ws.url == "ws://localhost:8080"
            assert ws.token == "test_token"
            assert ws.reconnect_interval == 5
            assert ws.ws is None
            assert ws.bot is None
            assert ws.self_id is None
            assert ws.code_executor is None

    @pytest.mark.asyncio
    async def test_call_api(self):
        """测试调用 API 方法。"""
        with patch('neobot.core.ws.global_config') as mock_config:
            mock_config.napcat_ws.uri = "ws://localhost:8080"
            mock_config.napcat_ws.token = "test_token"
            mock_config.napcat_ws.reconnect_interval = 5
            
            ws = WS()
            
            # 测试 WebSocket 未初始化的情况
            result = await ws.call_api("send_group_msg", {"group_id": 123456, "message": "test"})
            assert result["code"] == 2002  # WS_DISCONNECTED
            assert not result["success"]
            assert "WebSocket未初始化" in result["message"]
            
            # 测试 WebSocket 已初始化但未连接的情况
            mock_ws = MagicMock()
            mock_ws.state = None
            ws.ws = mock_ws
            result = await ws.call_api("send_group_msg", {"group_id": 123456, "message": "test"})
            assert result["code"] == 2002  # WS_DISCONNECTED
            assert not result["success"]
            assert "WebSocket连接未打开" in result["message"]

    @pytest.mark.asyncio
    async def test_on_event_bot_initialization(self):
        """测试事件处理中的 Bot 初始化。"""
        with patch('neobot.core.ws.global_config') as mock_config:
            mock_config.napcat_ws.uri = "ws://localhost:8080"
            mock_config.napcat_ws.token = "test_token"
            mock_config.napcat_ws.reconnect_interval = 5
            
            ws = WS()
            
            # 模拟包含 self_id 的事件
            event_data = {
                "post_type": "message",
                "message_type": "private",
                "self_id": 123456,
                "user_id": 789012,
                "message": "test",
                "raw_message": "test"
            }
            
            # 模拟事件工厂
            with patch('neobot.core.ws.EventFactory') as mock_factory:
                mock_event = MagicMock()
                mock_event.post_type = "message"
                mock_event.self_id = 123456
                mock_event.sender = None
                mock_event.message_type = "private"
                mock_event.user_id = 789012
                mock_event.raw_message = "test"
                mock_factory.create_event.return_value = mock_event
                
                # 模拟命令管理器
                with patch('neobot.core.managers.command_manager.matcher') as mock_matcher:
                    mock_matcher.handle_event = AsyncMock()
                    
                    await ws.on_event(event_data)
                    
                    # 验证 Bot 已初始化
                    assert ws.bot is not None
                    assert isinstance(ws.bot, Bot)
                    assert ws.self_id == 123456
                    
                    # 验证事件处理
                    mock_factory.create_event.assert_called_once_with(event_data)
                    mock_matcher.handle_event.assert_called_once()

    @pytest.mark.asyncio
    async def test_on_event_no_bot(self):
        """测试 Bot 未初始化时的事件处理。"""
        with patch('neobot.core.ws.global_config') as mock_config:
            mock_config.napcat_ws.uri = "ws://localhost:8080"
            mock_config.napcat_ws.token = "test_token"
            mock_config.napcat_ws.reconnect_interval = 5
            
            ws = WS()
            
            # 模拟不包含 self_id 的事件
            event_data = {
                "post_type": "message",
                "message_type": "private",
                "user_id": 789012,
                "message": "test",
                "raw_message": "test"
            }
            
            # 模拟事件工厂
            with patch('neobot.core.ws.EventFactory') as mock_factory:
                mock_event = MagicMock()
                mock_event.post_type = "message"
                # 确保事件没有 self_id 属性
                del mock_event.self_id
                mock_event.sender = None
                mock_event.message_type = "private"
                mock_event.user_id = 789012
                mock_event.raw_message = "test"
                mock_factory.create_event.return_value = mock_event
                
                # 模拟命令管理器
                with patch('neobot.core.managers.command_manager.matcher') as mock_matcher:
                    mock_matcher.handle_event = AsyncMock()
                    
                    await ws.on_event(event_data)
                    
                    # 验证 Bot 未初始化
                    assert ws.bot is None
                    assert ws.self_id is None
                    
                    # 验证事件处理未被调用
                    mock_matcher.handle_event.assert_not_called()

    @pytest.mark.asyncio
    async def test_call_api_with_code_executor(self):
        """测试带代码执行器的 WS 初始化。"""
        with patch('neobot.core.ws.global_config') as mock_config:
            mock_config.napcat_ws.uri = "ws://localhost:8080"
            mock_config.napcat_ws.token = "test_token"
            mock_config.napcat_ws.reconnect_interval = 5
            
            mock_executor = MagicMock()
            ws = WS(code_executor=mock_executor)
            
            # 模拟包含 self_id 的事件
            event_data = {
                "post_type": "message",
                "message_type": "private",
                "self_id": 123456,
                "user_id": 789012,
                "message": "test",
                "raw_message": "test"
            }
            
            # 模拟事件工厂
            with patch('neobot.core.ws.EventFactory') as mock_factory:
                mock_event = MagicMock()
                mock_event.post_type = "message"
                mock_event.self_id = 123456
                mock_event.sender = None
                mock_event.message_type = "private"
                mock_event.user_id = 789012
                mock_event.raw_message = "test"
                mock_factory.create_event.return_value = mock_event
                
                # 模拟命令管理器
                with patch('neobot.core.managers.command_manager.matcher') as mock_matcher:
                    mock_matcher.handle_event = AsyncMock()
                    
                    await ws.on_event(event_data)
                    
                    # 验证代码执行器已注入
                    assert ws.bot.code_executor is mock_executor
                    assert mock_executor.bot is ws.bot
