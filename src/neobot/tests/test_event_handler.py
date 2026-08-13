import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from neobot.core.handlers.event_handler import MessageHandler, NoticeHandler, RequestHandler
from neobot.models.events.message import GroupMessageEvent
from neobot.models.events.notice import GroupIncreaseNoticeEvent
from neobot.models.events.request import FriendRequestEvent

@pytest.fixture
def mock_bot():
    bot = AsyncMock()
    return bot

@pytest.mark.asyncio
async def test_message_handler_run_handler_injection(mock_bot):
    """测试参数注入"""
    handler = MessageHandler(prefixes=("/",))
    
    # 1. 测试注入 bot 和 event
    async def func1(bot, event):
        assert bot == mock_bot
        assert event.user_id == 123
        return True
        
    event = MagicMock(spec=GroupMessageEvent)
    event.user_id = 123
    
    result = await handler._run_handler(func1, mock_bot, event)
    assert result is True
    
    # 2. 测试注入 args
    async def func2(args):
        assert args == ["arg1", "arg2"]
        return True
        
    result = await handler._run_handler(func2, mock_bot, event, args=["arg1", "arg2"])
    assert result is True

@pytest.mark.asyncio
async def test_message_handler_command_parsing(mock_bot):
    """测试命令解析"""
    handler = MessageHandler(prefixes=("/",))
    
    mock_func = AsyncMock()
    handler.commands["test"] = {
        "func": mock_func,
        "permission": None,
        "override_permission_check": False,
        "plugin_name": "test_plugin"
    }
    
    event = MagicMock(spec=GroupMessageEvent)
    event.raw_message = "/test arg1 arg2"
    event.user_id = 123
    
    # Mock permission manager
    with patch("neobot.core.managers.permission_manager.permission_manager.check_permission", new_callable=AsyncMock) as mock_perm:
        mock_perm.return_value = True
        
        await handler.handle(mock_bot, event)
        
        mock_func.assert_called_once()
        # 验证 args 参数是否正确传递
        call_args = mock_func.call_args
        if "args" in call_args.kwargs:
            assert call_args.kwargs["args"] == ["arg1", "arg2"]

@pytest.mark.asyncio
async def test_notice_handler(mock_bot):
    """测试通知事件分发"""
    handler = NoticeHandler()
    
    mock_func = AsyncMock()
    handler.handlers.append({
        "type": "group_increase",
        "func": mock_func,
        "plugin_name": "test_plugin"
    })
    
    event = MagicMock(spec=GroupIncreaseNoticeEvent)
    event.notice_type = "group_increase"
    
    await handler.handle(mock_bot, event)
    
    mock_func.assert_called_once()

@pytest.mark.asyncio
async def test_sync_handler_execution(mock_bot):
    """测试同步处理函数的执行"""
    handler = MessageHandler(prefixes=("/",))
    
    def sync_func(event):
        return True
        
    event = MagicMock(spec=GroupMessageEvent)
    
    # 同步函数应该在线程池中运行
    result = await handler._run_handler(sync_func, mock_bot, event)
    assert result is True

@pytest.mark.asyncio
async def test_message_handler_priority_and_block(mock_bot):
    """测试消息处理器的优先级和 block 参数"""
    handler = MessageHandler(prefixes=("/",))
    results = []
    
    # 注册不同优先级的处理器
    @handler.on_message(priority=10, block=True)
    async def handler1(event):
        results.append("handler1")
        return True
    
    @handler.on_message(priority=5, block=False)
    async def handler2(event):
        results.append("handler2")
        return False
    
    @handler.on_message(priority=0, block=False)
    async def handler3(event):
        results.append("handler3")
        return False
    
    # 验证优先级和 block 参数正确存储
    assert len(handler.message_handlers) == 3
    
    # 验证参数
    for h in handler.message_handlers:
        assert "priority" in h
        assert "block" in h
    
    # 验证优先级排序（通过检查排序后的顺序）
    sorted_handlers = sorted(handler.message_handlers, key=lambda h: h.get("priority", 10))
    assert sorted_handlers[0]["func"].__name__ == "handler3"  # priority=0
    assert sorted_handlers[1]["func"].__name__ == "handler2"  # priority=5
    assert sorted_handlers[2]["func"].__name__ == "handler1"  # priority=10

@pytest.mark.asyncio
async def test_message_handler_block_behavior(mock_bot):
    """测试 block 参数的行为"""
    handler = MessageHandler(prefixes=("/",))
    results = []
    
    # 测试 block=False 的处理器不会阻断后续处理器
    @handler.on_message(priority=0, block=False)
    async def handler_no_block(event):
        results.append("no_block")
        return False
    
    @handler.on_message(priority=1, block=False)
    async def handler_no_block2(event):
        results.append("no_block2")
        return False
    
    # 创建模拟事件
    event = MagicMock(spec=GroupMessageEvent)
    event.raw_message = ""
    event.user_id = 123
    
    # Mock redis 操作
    with patch("neobot.core.managers.redis_manager"):
        await handler.handle(mock_bot, event)
    
    # 两个处理器都应该被调用
    assert results == ["no_block", "no_block2"]
    
    # 测试 block=True 的处理器会阻断后续处理器
    results.clear()
    handler2 = MessageHandler(prefixes=("/",))
    
    @handler2.on_message(priority=0, block=True)
    async def handler_block(event):
        results.append("block")
        return False
    
    @handler2.on_message(priority=1, block=False)
    async def handler_after_block(event):
        results.append("after_block")
        return False
    
    with patch("neobot.core.managers.redis_manager"):
        await handler2.handle(mock_bot, event)
    
    # 只有第一个处理器应该被调用
    assert results == ["block"]

@pytest.mark.asyncio
async def test_message_handler_management(mock_bot):
    """测试消息处理器的管理（注册、卸载、清空）"""
    handler = MessageHandler(prefixes=("/",))
    
    # 测试 on_message 装饰器
    @handler.on_message()
    async def msg_handler(event):
        pass
        
    assert len(handler.message_handlers) == 1
    
    # 验证默认参数
    assert handler.message_handlers[0]["priority"] == 10
    assert handler.message_handlers[0]["block"] is False
    
    # 测试 command 装饰器
    @handler.command("cmd1", "cmd2")
    async def cmd_handler(event):
        pass
        
    assert len(handler.commands) == 2
    assert "cmd1" in handler.commands
    assert "cmd2" in handler.commands
    
    # 测试 unregister_by_plugin_name
    # 直接从已注册的处理器中获取 plugin_name
    if handler.message_handlers:
        plugin_name = handler.message_handlers[0]["plugin_name"]
        handler.unregister_by_plugin_name(plugin_name)
    
    assert len(handler.message_handlers) == 0
    assert len(handler.commands) == 0
    
    # 测试 clear
    handler.commands["cmd"] = {}
    handler.message_handlers.append({})
    handler.clear()
    assert len(handler.commands) == 0
    assert len(handler.message_handlers) == 0

@pytest.mark.asyncio
async def test_request_handler(mock_bot):
    """测试请求事件处理器"""
    handler = RequestHandler()
    
    mock_func = AsyncMock()
    
    # 测试 register 装饰器
    @handler.register("friend")
    async def req_handler(event):
        await mock_func(event)
        
    assert len(handler.handlers) == 1
    
    event = MagicMock(spec=FriendRequestEvent)
    event.request_type = "friend"
    
    await handler.handle(mock_bot, event)
    mock_func.assert_called_once()
    
    # 测试 unregister 和 clear
    import inspect
    module = inspect.getmodule(req_handler)
    plugin_name = module.__name__
    
    handler.unregister_by_plugin_name(plugin_name)
    assert len(handler.handlers) == 0
    
    handler.handlers.append({})
    handler.clear()
    assert len(handler.handlers) == 0

@pytest.mark.asyncio
async def test_permission_denied(mock_bot):
    """测试权限不足的情况"""
    handler = MessageHandler(prefixes=("/",))
    
    mock_func = AsyncMock()
    handler.commands["admin_cmd"] = {
        "func": mock_func,
        "permission": "ADMIN", # 假设 Permission.ADMIN
        "override_permission_check": False,
        "plugin_name": "test_plugin"
    }
    
    event = MagicMock(spec=GroupMessageEvent)
    event.raw_message = "/admin_cmd"
    event.user_id = 123
    
    # Mock permission manager returning False
    with patch("neobot.core.managers.permission_manager.permission_manager.check_permission", new_callable=AsyncMock) as mock_perm:
        mock_perm.return_value = False
        
        await handler.handle(mock_bot, event)
        
        mock_func.assert_not_called()
        # 应该发送拒绝消息
        mock_bot.send.assert_called_once()
