"""
WebSocket 连接池测试模块

该模块包含对 WebSocket 连接池的单元测试和集成测试。
"""
import pytest
import asyncio
from unittest.mock import Mock, patch

# ws_pool 模块已被移除，旧测试文件整体跳过，待模块恢复后再启用
WSConnection, WSConnectionPool = pytest.importorskip(
    "neobot.core.ws_pool",
    reason="ws_pool 模块已不存在，该测试文件为旧模块遗留",
)
from neobot.core.utils.exceptions import WebSocketError


class TestWSConnection:
    """
    WebSocket 连接包装类测试
    """
    def test_connection_initialization(self):
        """测试连接初始化"""
        mock_conn = Mock()
        conn_id = "test-connection-id"
        
        conn = WSConnection(mock_conn, conn_id)
        
        assert conn.conn == mock_conn
        assert conn.conn_id == conn_id
        assert conn.is_active
        assert conn._pending_requests == {}
        assert isinstance(conn.last_used, float)
    
    @pytest.mark.asyncio
    async def test_send_data(self):
        """测试发送数据"""
        mock_conn = Mock()
        mock_conn.send = Mock(return_value=asyncio.coroutine(lambda x: None)())
        
        conn = WSConnection(mock_conn, "test-id")
        data = {"action": "test", "params": {}}
        
        await conn.send(data)
        mock_conn.send.assert_called_once()
        assert conn.last_used > 0
    
    @pytest.mark.asyncio
    async def test_send_data_inactive_connection(self):
        """测试向已关闭的连接发送数据"""
        mock_conn = Mock()
        conn = WSConnection(mock_conn, "test-id")
        conn.is_active = False
        
        with pytest.raises(WebSocketError):
            await conn.send({"action": "test"})
    
    @pytest.mark.asyncio
    async def test_recv_data(self):
        """测试接收数据"""
        mock_conn = Mock()
        mock_conn.recv = Mock(return_value=asyncio.coroutine(lambda: "test-data")())
        
        conn = WSConnection(mock_conn, "test-id")
        result = await conn.recv()
        
        assert result == "test-data"
        mock_conn.recv.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_close_connection(self):
        """测试关闭连接"""
        mock_conn = Mock()
        mock_conn.close = Mock(return_value=asyncio.coroutine(lambda: None)())
        
        conn = WSConnection(mock_conn, "test-id")
        await conn.close()
        
        assert not conn.is_active
        mock_conn.close.assert_called_once()


class TestWSConnectionPool:
    """
    WebSocket 连接池测试
    """
    @pytest.mark.asyncio
    async def test_pool_initialization(self):
        """测试连接池初始化"""
        pool = WSConnectionPool(pool_size=2, max_idle_time=300)
        assert pool.pool_size == 2
        assert pool.max_idle_time == 300
        assert not pool._closed
        assert pool.pool is not None
    
    @pytest.mark.asyncio
    @patch('websockets.connect')
    async def test_create_connection(self, mock_connect):
        """测试创建新连接"""
        mock_websocket = Mock()
        mock_connect.return_value = asyncio.coroutine(lambda: mock_websocket)()
        
        pool = WSConnectionPool(pool_size=1)
        conn = await pool._create_connection()
        
        assert isinstance(conn, WSConnection)
        assert conn.is_active
        mock_connect.assert_called_once()
    
    @pytest.mark.asyncio
    @patch('websockets.connect')
    async def test_pool_initialize(self, mock_connect):
        """测试连接池初始化"""
        mock_websocket = Mock()
        mock_connect.return_value = asyncio.coroutine(lambda: mock_websocket)()
        
        pool = WSConnectionPool(pool_size=2)
        await pool.initialize()
        
        assert pool.pool.qsize() == 2
        mock_connect.assert_called()
    
    @pytest.mark.asyncio
    @patch('websockets.connect')
    async def test_get_connection(self, mock_connect):
        """测试从连接池获取连接"""
        mock_websocket = Mock()
        mock_connect.return_value = asyncio.coroutine(lambda: mock_websocket)()
        
        pool = WSConnectionPool(pool_size=1)
        await pool.initialize()
        
        conn = await pool.get_connection()
        assert isinstance(conn, WSConnection)
        assert conn.is_active
        assert pool.pool.qsize() == 0
    
    @pytest.mark.asyncio
    @patch('websockets.connect')
    async def test_release_connection(self, mock_connect):
        """测试释放连接回连接池"""
        mock_websocket = Mock()
        mock_connect.return_value = asyncio.coroutine(lambda: mock_websocket)()
        
        pool = WSConnectionPool(pool_size=1)
        await pool.initialize()
        
        conn = await pool.get_connection()
        await pool.release_connection(conn)
        
        assert pool.pool.qsize() == 1
    
    @pytest.mark.asyncio
    @patch('websockets.connect')
    async def test_release_inactive_connection(self, mock_connect):
        """测试释放已关闭的连接"""
        mock_websocket = Mock()
        mock_connect.return_value = asyncio.coroutine(lambda: mock_websocket)()
        
        pool = WSConnectionPool(pool_size=1)
        await pool.initialize()
        
        conn = await pool.get_connection()
        conn.is_active = False
        
        await pool.release_connection(conn)
        assert pool.pool.qsize() == 0
    
    @pytest.mark.asyncio
    @patch('websockets.connect')
    async def test_cleanup_idle_connections(self, mock_connect):
        """测试清理空闲连接"""
        mock_websocket = Mock()
        mock_connect.return_value = asyncio.coroutine(lambda: mock_websocket)()
        
        pool = WSConnectionPool(pool_size=2, max_idle_time=0.1)
        await pool.initialize()
        
        # 等待清理任务执行
        await asyncio.sleep(0.2)
        
        # 检查连接池是否为空
        assert pool.pool.qsize() == 0
    
    @pytest.mark.asyncio
    @patch('websockets.connect')
    async def test_pool_close(self, mock_connect):
        """测试关闭连接池"""
        mock_websocket = Mock()
        mock_websocket.close = Mock(return_value=asyncio.coroutine(lambda: None)())
        mock_connect.return_value = asyncio.coroutine(lambda: mock_websocket)()
        
        pool = WSConnectionPool(pool_size=2)
        await pool.initialize()
        
        await pool.close()
        
        assert pool._closed
        assert pool.pool.qsize() == 0
        mock_websocket.close.assert_called()
    
    @pytest.mark.asyncio
    async def test_get_connection_from_closed_pool(self):
        """测试从已关闭的连接池获取连接"""
        pool = WSConnectionPool(pool_size=1)
        pool._closed = True
        
        with pytest.raises(WebSocketError):
            await pool.get_connection()
    
    @pytest.mark.asyncio
    @patch('websockets.connect')
    async def test_pool_with_max_size(self, mock_connect):
        """测试连接池大小限制"""
        mock_websocket = Mock()
        mock_connect.return_value = asyncio.coroutine(lambda: mock_websocket)()
        
        pool = WSConnectionPool(pool_size=2)
        await pool.initialize()
        
        # 获取两个连接
        conn1 = await pool.get_connection()
        conn2 = await pool.get_connection()
        
        # 第三个连接会创建临时连接
        conn3 = await pool.get_connection()
        
        # 释放所有连接
        await pool.release_connection(conn1)
        await pool.release_connection(conn2)
        await pool.release_connection(conn3)
        
        # 连接池应保持最大大小
        assert pool.pool.qsize() == 2


if __name__ == "__main__":
    pytest.main([__file__])
