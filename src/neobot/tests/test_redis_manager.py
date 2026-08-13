import pytest
from unittest.mock import patch, AsyncMock
from neobot.core.managers.redis_manager import RedisManager


@pytest.fixture(autouse=True)
def reset_redis_manager():
    """每个用例前后重置 RedisManager 单例（Singleton 使用模块级存储）。"""
    from neobot.core.utils.singleton import _instance_store

    _instance_store.pop(RedisManager, None)
    RedisManager._redis = None
    yield
    _instance_store.pop(RedisManager, None)
    RedisManager._redis = None


class TestRedisManager:
    def test_singleton_pattern(self):
        """测试单例模式。"""
        instance1 = RedisManager()
        instance2 = RedisManager()
        assert instance1 is instance2

    @pytest.mark.asyncio
    async def test_initialize_success(self):
        """测试 Redis 初始化成功。"""
        with patch("neobot.core.managers.redis_manager.config") as mock_config:
            mock_config.redis.host = "localhost"
            mock_config.redis.port = 6379
            mock_config.redis.db = 0
            mock_config.redis.password = "test_password"

            with patch("neobot.core.managers.redis_manager.redis.Redis") as mock_redis_class:
                mock_redis = AsyncMock()
                mock_redis.ping.return_value = True
                mock_redis_class.return_value = mock_redis

                manager = RedisManager()
                await manager.initialize()

                mock_redis_class.assert_called_once_with(
                    host="localhost",
                    port=6379,
                    db=0,
                    password="test_password",
                    decode_responses=True,
                    ssl=False,
                )
                mock_redis.ping.assert_called_once()
                assert manager._redis is mock_redis

    @pytest.mark.asyncio
    async def test_initialize_connection_error(self):
        """测试 Redis 连接失败时重置状态。"""
        with patch("neobot.core.managers.redis_manager.config") as mock_config:
            mock_config.redis.host = "localhost"
            mock_config.redis.port = 6379
            mock_config.redis.db = 0
            mock_config.redis.password = "test_password"

            with patch("neobot.core.managers.redis_manager.redis.Redis") as mock_redis_class:
                mock_redis_class.side_effect = Exception("Connection refused")

                manager = RedisManager()
                await manager.initialize()

                assert manager._redis is None

    @pytest.mark.asyncio
    async def test_initialize_ping_failure_resets_client(self):
        """测试 PING 失败时连接被关闭并置空，便于下次重试。"""
        with patch("neobot.core.managers.redis_manager.config") as mock_config:
            mock_config.redis.host = "localhost"
            mock_config.redis.port = 6379
            mock_config.redis.db = 0
            mock_config.redis.password = "test_password"

            with patch("neobot.core.managers.redis_manager.redis.Redis") as mock_redis_class:
                mock_redis = AsyncMock()
                mock_redis.ping.return_value = False
                mock_redis_class.return_value = mock_redis

                manager = RedisManager()
                await manager.initialize()

                mock_redis.aclose.assert_awaited_once()
                assert manager._redis is None

    def test_redis_property_uninitialized(self):
        """测试 Redis 属性在未初始化时抛出异常。"""
        manager = RedisManager()
        with pytest.raises(ConnectionError, match="Redis 未初始化或连接失败，请先调用 initialize()"):
            _ = manager.redis

    @pytest.mark.asyncio
    async def test_get_method(self):
        """测试 get 方法。"""
        manager = RedisManager()
        mock_redis = AsyncMock()
        mock_redis.get.return_value = "test_value"
        manager._redis = mock_redis

        result = await manager.get("test_key")
        assert result == "test_value"
        mock_redis.get.assert_called_once_with("test_key")

    @pytest.mark.asyncio
    async def test_set_method(self):
        """测试 set 方法。"""
        manager = RedisManager()
        mock_redis = AsyncMock()
        mock_redis.set.return_value = True
        manager._redis = mock_redis

        result = await manager.set("test_key", "test_value", ex=3600)
        assert result is True
        mock_redis.set.assert_called_once_with("test_key", "test_value", ex=3600)
