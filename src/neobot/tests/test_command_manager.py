import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from neobot.core.managers.command_manager import CommandManager
from neobot.models.events.message import GroupMessageEvent
from neobot.models.message import MessageSegment

@pytest.fixture
def mock_bot():
    bot = AsyncMock()
    bot.self_id = 123456
    return bot

@pytest.fixture
def command_manager():
    # 创建一个新的 CommandManager 实例用于测试，避免单例状态污染
    return CommandManager(prefixes=("/",))

@pytest.mark.asyncio
async def test_command_registration_and_execution(command_manager, mock_bot):
    """测试命令注册和执行"""
    
    # 定义一个命令处理函数
    handler_mock = AsyncMock()
    
    # 注册命令
    @command_manager.command("test")
    async def test_command(bot, event):
        await handler_mock(bot, event)
        
    # 构造触发命令的事件
    event = MagicMock(spec=GroupMessageEvent)
    event.post_type = "message"
    event.message_type = "group"
    event.raw_message = "/test"
    event.message = [MessageSegment.text("/test")]
    event.user_id = 111
    event.group_id = 222
    
    # 处理事件
    await command_manager.handle_event(mock_bot, event)
    
    # 验证处理函数被调用
    handler_mock.assert_called_once_with(mock_bot, event)

@pytest.mark.asyncio
async def test_command_prefix_match(command_manager, mock_bot):
    """测试命令前缀匹配"""
    handler_mock = AsyncMock()
    
    @command_manager.command("hello")
    async def hello_command(bot, event):
        await handler_mock(bot, event)
        
    # 1. 正确的前缀
    event1 = MagicMock(spec=GroupMessageEvent)
    event1.post_type = "message"
    event1.raw_message = "/hello"
    event1.message = [MessageSegment.text("/hello")]
    await command_manager.handle_event(mock_bot, event1)
    handler_mock.assert_called_once()
    handler_mock.reset_mock()
    
    # 2. 错误的前缀 (应该忽略)
    event2 = MagicMock(spec=GroupMessageEvent)
    event2.post_type = "message"
    event2.raw_message = ".hello" # 假设前缀是 /
    event2.message = [MessageSegment.text(".hello")]
    await command_manager.handle_event(mock_bot, event2)
    handler_mock.assert_not_called()

@pytest.mark.asyncio
async def test_ignore_self_message(command_manager, mock_bot):
    """测试忽略自身消息"""
    # 模拟配置
    with patch("neobot.core.managers.command_manager.global_config") as mock_config:
        mock_config.bot.ignore_self_message = True
        
        event = MagicMock(spec=GroupMessageEvent)
        event.post_type = "message"
        event.user_id = 123456 # 与 bot.self_id 相同
        event.self_id = 123456
        
        # Mock handle 方法来检测是否被调用
        command_manager.message_handler.handle = AsyncMock()
        
        await command_manager.handle_event(mock_bot, event)
        
        # 应该直接返回，不调用 handler
        command_manager.message_handler.handle.assert_not_called()

@pytest.mark.asyncio
async def test_help_command(command_manager, mock_bot):
    """测试内置 help 命令"""
    # 注册一个测试插件信息
    command_manager.plugins["test_plugin"] = {
        "name": "测试插件",
        "description": "这是一个测试",
        "usage": "/test"
    }
    
    event = MagicMock(spec=GroupMessageEvent)
    event.post_type = "message"
    event.raw_message = "/help"
    event.message = [MessageSegment.text("/help")]
    
    await command_manager.handle_event(mock_bot, event)
    
    # 验证 bot.send 被调用，且内容包含插件信息
    mock_bot.send.assert_called_once()
    args, _ = mock_bot.send.call_args
    sent_msg = args[1]
    assert "测试插件" in sent_msg
    assert "这是一个测试" in sent_msg
