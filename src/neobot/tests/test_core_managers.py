
import json
import os
import tempfile
import pytest
from unittest.mock import MagicMock, patch, AsyncMock

from neobot.core.managers.permission_manager import PermissionManager
# admin_manager 模块已被移除，旧测试文件整体跳过，待模块恢复后再启用
AdminManager = pytest.importorskip(
    "neobot.core.managers.admin_manager",
    reason="admin_manager 模块已不存在，该测试文件为旧模块遗留",
)
from neobot.core.permission import Permission

# --- Fixtures ---

@pytest.fixture
def mock_redis():
    """Mock RedisManager to avoid real Redis connection"""
    with patch("core.managers.redis_manager.redis_manager") as mock:
        mock.redis = AsyncMock()
        # Mock sismember to return False by default
        mock.redis.sismember.return_value = False
        yield mock

@pytest.fixture
def temp_data_dir():
    """Create a temporary directory for data files"""
    with tempfile.TemporaryDirectory() as tmpdirname:
        yield tmpdirname

@pytest.fixture
def admin_manager(temp_data_dir, mock_redis):
    """Create an AdminManager instance with temporary data file"""
    # Reset singleton instance if it exists
    if hasattr(AdminManager, "_instance"):
        del AdminManager._instance
    
    # Patch the data file path
    with patch("core.managers.admin_manager.AdminManager.__init__", return_value=None) as mock_init:
        manager = AdminManager()
        # Manually initialize necessary attributes since we mocked __init__
        manager.data_file = os.path.join(temp_data_dir, "admin.json")
        manager._admins = set()
        # Call the real __init__ logic we want to test (partially) or just setup state
        # Actually, it's better to let __init__ run but patch the path inside it.
        # But AdminManager is a Singleton, which makes it tricky.
        pass

    # Let's try a different approach: Patch the class attribute or use a fresh instance logic
    # Since Singleton logic might prevent re-init, we force it.
    
    # Re-create properly
    if hasattr(AdminManager, "_instance"):
        del AdminManager._instance
        
    with patch("core.managers.admin_manager.os.path.dirname") as mock_dirname:
        # We want os.path.join(..., "data", "admin.json") to resolve to our temp file
        # But the path construction is hardcoded.
        # Instead, we can patch the `data_file` attribute after init if we can.
        
        # Easiest way: Subclass or modify the instance after creation, 
        # but __init__ runs immediately.
        
        # Let's patch `os.path.abspath` to redirect the base path? 
        # No, let's just patch the `data_file` attribute on the instance.
        
        manager = AdminManager()
        manager.data_file = os.path.join(temp_data_dir, "admin.json")
        manager._admins = set() # Reset in-memory state
        
        return manager

@pytest.fixture
def permission_manager(temp_data_dir, admin_manager):
    """Create a PermissionManager instance with temporary data file"""
    if hasattr(PermissionManager, "_instance"):
        del PermissionManager._instance
        
    manager = PermissionManager()
    manager.data_file = os.path.join(temp_data_dir, "permissions.json")
    manager._data = {"users": {}} # Reset in-memory state
    
    # Ensure admin_manager is linked correctly if needed (it's imported globally in permission_manager)
    # We need to patch the global admin_manager used in permission_manager
    with patch("core.managers.permission_manager.admin_manager", admin_manager):
        yield manager


# --- AdminManager Tests ---

@pytest.mark.asyncio
async def test_admin_manager_load_save(admin_manager):
    """Test loading and saving admins to file"""
    # Test adding and saving
    await admin_manager.add_admin(123456)
    assert 123456 in admin_manager._admins
    
    # Verify file content
    with open(admin_manager.data_file, "r", encoding="utf-8") as f:
        data = json.load(f)
        assert "123456" in data["admins"]
        
    # Test loading
    # Clear memory
    admin_manager._admins.clear()
    await admin_manager._load_from_file()
    assert 123456 in admin_manager._admins

@pytest.mark.asyncio
async def test_admin_manager_operations(admin_manager, mock_redis):
    """Test add, remove, and is_admin operations"""
    user_id = 1001
    
    # Initially not admin
    assert not await admin_manager.is_admin(user_id)
    
    # Add admin
    success = await admin_manager.add_admin(user_id)
    assert success
    assert await admin_manager.is_admin(user_id)
    mock_redis.redis.sadd.assert_called()
    
    # Add duplicate
    success = await admin_manager.add_admin(user_id)
    assert not success
    
    # Remove admin
    success = await admin_manager.remove_admin(user_id)
    assert success
    assert not await admin_manager.is_admin(user_id)
    mock_redis.redis.srem.assert_called()
    
    # Remove non-existent
    success = await admin_manager.remove_admin(user_id)
    assert not success

@pytest.mark.asyncio
async def test_admin_manager_sync_redis(admin_manager, mock_redis):
    """Test syncing to Redis"""
    admin_manager._admins = {111, 222}
    await admin_manager._sync_to_redis()
    
    mock_redis.redis.delete.assert_called_with(admin_manager._REDIS_KEY)
    
    # Check sadd call args manually because set order is not guaranteed
    args, _ = mock_redis.redis.sadd.call_args
    assert args[0] == admin_manager._REDIS_KEY
    assert set(args[1:]) == {111, 222}


# --- PermissionManager Tests ---

@pytest.mark.asyncio
async def test_permission_manager_load_save(permission_manager):
    """Test loading and saving permissions"""
    user_id = 2001
    permission_manager.set_user_permission(user_id, Permission.OP)
    
    # Verify memory
    assert permission_manager._data["users"][str(user_id)] == "op"
    
    # Verify file
    with open(permission_manager.data_file, "r", encoding="utf-8") as f:
        data = json.load(f)
        assert data["users"][str(user_id)] == "op"
        
    # Test load
    permission_manager._data["users"] = {}
    permission_manager.load()
    assert permission_manager._data["users"][str(user_id)] == "op"

@pytest.mark.asyncio
async def test_permission_check_flow(permission_manager, admin_manager):
    """Test permission checking logic including admin fallback"""
    admin_id = 8888
    op_id = 6666
    user_id = 1111
    
    # Setup admin
    await admin_manager.add_admin(admin_id)
    
    # Setup OP
    permission_manager.set_user_permission(op_id, Permission.OP)
    
    # Test Admin (should be ADMIN even if not in permissions.json)
    perm = await permission_manager.get_user_permission(admin_id)
    assert perm == Permission.ADMIN
    assert await permission_manager.check_permission(admin_id, Permission.ADMIN)
    assert await permission_manager.check_permission(admin_id, Permission.OP)
    
    # Test OP
    perm = await permission_manager.get_user_permission(op_id)
    assert perm == Permission.OP
    assert not await permission_manager.check_permission(op_id, Permission.ADMIN)
    assert await permission_manager.check_permission(op_id, Permission.OP)
    assert await permission_manager.check_permission(op_id, Permission.USER)
    
    # Test User (Default)
    perm = await permission_manager.get_user_permission(user_id)
    assert perm == Permission.USER
    assert not await permission_manager.check_permission(user_id, Permission.OP)
    assert await permission_manager.check_permission(user_id, Permission.USER)

@pytest.mark.asyncio
async def test_get_all_user_permissions(permission_manager, admin_manager):
    """Test merging of admin and permission data"""
    admin_id = 9999
    op_id = 7777
    
    await admin_manager.add_admin(admin_id)
    permission_manager.set_user_permission(op_id, Permission.OP)
    
    all_perms = await permission_manager.get_all_user_permissions()
    
    assert str(admin_id) in all_perms
    assert all_perms[str(admin_id)] == "admin"
    assert str(op_id) in all_perms
    assert all_perms[str(op_id)] == "op"

def test_remove_user(permission_manager):
    """Test removing user permission"""
    user_id = 3001
    permission_manager.set_user_permission(user_id, Permission.OP)
    assert str(user_id) in permission_manager._data["users"]
    
    permission_manager.remove_user(user_id)
    assert str(user_id) not in permission_manager._data["users"]

@pytest.mark.asyncio
async def test_permission_manager_load_error(permission_manager):
    """Test loading permissions with invalid file"""
    # Write invalid JSON
    with open(permission_manager.data_file, "w", encoding="utf-8") as f:
        f.write("{invalid_json")
        
    # Should not raise exception, but log error (we can't easily check log here without more mocking)
    # But we can check that data remains empty or default
    permission_manager._data["users"] = {}
    permission_manager.load()
    assert permission_manager._data["users"] == {}

@pytest.mark.asyncio
async def test_admin_manager_redis_error(admin_manager, mock_redis):
    """Test Redis errors are handled gracefully"""
    mock_redis.redis.sadd.side_effect = Exception("Redis error")
    
    # Should not raise exception
    success = await admin_manager.add_admin(123)
    assert not success  # Or however it handles it - let's check implementation
    # Looking at code: try...except Exception... return False
    
    mock_redis.redis.srem.side_effect = Exception("Redis error")
    success = await admin_manager.remove_admin(123)
    assert not success

def test_permission_manager_utils(permission_manager):
    """Test utility methods like get_all_users and clear_all"""
    permission_manager.set_user_permission(123, Permission.OP)
    permission_manager.set_user_permission(456, Permission.USER)
    
    users = permission_manager.get_all_users()
    assert "123" in users
    assert "456" in users
    
    permission_manager.clear_all()
    assert len(permission_manager.get_all_users()) == 0

@pytest.mark.asyncio
async def test_require_admin_decorator(permission_manager, admin_manager):
    """Test the require_admin decorator"""
    from neobot.core.managers.permission_manager import require_admin
    from neobot.models.events.message import MessageEvent
    
    # Mock event
    mock_event = MagicMock(spec=MessageEvent)
    mock_event.user_id = 12345
    mock_event.reply = AsyncMock()
    
    # Define decorated function
    @require_admin
    async def protected_func(event, *args):
        return "success"
    
    # Test without permission
    result = await protected_func(mock_event)
    assert result is None
    mock_event.reply.assert_called_with("抱歉，您没有权限执行此命令。")
    
    # Test with permission
    await admin_manager.add_admin(12345)
    result = await protected_func(mock_event)
    assert result == "success"
