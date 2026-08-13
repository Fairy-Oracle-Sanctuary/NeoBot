"""
线程管理器测试模块

测试多线程功能的正确性，包括：
1. 线程池的创建和管理
2. 任务提交和执行
3. 线程安全的统计信息
"""
import asyncio
import time
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from neobot.core.managers.thread_manager import thread_manager, ThreadManager


class TestThreadManager:
    """线程管理器测试类"""
    
    def test_singleton(self):
        """测试单例模式"""
        manager1 = ThreadManager()
        manager2 = ThreadManager()
        assert manager1 is manager2
    
    def test_start_and_shutdown(self):
        """测试启动和关闭"""
        manager = ThreadManager()
        manager.start()
        assert manager._executor is not None
        
        # 提交一个简单任务
        result = manager.submit_to_main_executor(lambda x: x * 2, 5)
        assert result == 10
        
        manager.shutdown()
        assert manager._executor is None
    
    def test_submit_to_main_executor(self):
        """测试提交任务到主线程池"""
        manager = ThreadManager()
        manager.start()
        
        # 测试同步任务
        result = manager.submit_to_main_executor(lambda x, y: x + y, 3, 4)
        assert result == 7
        
        # 测试异步任务
        async def async_task(x):
            await asyncio.sleep(0.1)
            return x * 2
        
        async def run_async():
            return await manager.submit_to_main_executor_async(async_task, 5)
        
        result = asyncio.run(run_async())
        assert result == 10
        
        manager.shutdown()
    
    def test_thread_safety(self):
        """测试线程安全"""
        manager = ThreadManager()
        manager.start()
        
        results = []
        errors = []
        
        def worker(n):
            try:
                time.sleep(0.01)
                return n * n
            except Exception as e:
                errors.append(e)
                return None
        
        # 并发提交多个任务
        futures = []
        for i in range(10):
            future = manager._executor.submit(worker, i)
            futures.append(future)
        
        # 收集结果
        for future in futures:
            result = future.result()
            results.append(result)
        
        # 验证所有任务都成功执行
        assert len(errors) == 0
        assert len(results) == 10
        assert sorted(results) == [0, 1, 4, 9, 16, 25, 36, 49, 64, 81]
        
        manager.shutdown()
    
    def test_stats_tracking(self):
        """测试统计信息"""
        manager = ThreadManager()
        manager.start()
        
        # 执行一些任务
        for i in range(5):
            manager.submit_to_main_executor(lambda x: x, i)
        
        stats = manager.get_stats()
        assert stats['total_tasks'] >= 5
        
        manager.shutdown()


class TestReverseWSManagerThreading:
    """反向 WebSocket 管理器线程安全测试"""
    
    def test_locks_exist(self):
        """测试锁是否正确初始化"""
        from neobot.core.managers.reverse_ws_manager import ReverseWSManager
        
        manager = ReverseWSManager()
        
        # 检查所有锁是否存在
        assert hasattr(manager, '_clients_lock')
        assert hasattr(manager, '_bots_lock')
        assert hasattr(manager, '_pending_requests_lock')
        assert hasattr(manager, '_load_lock')
        assert hasattr(manager, '_health_lock')
        assert hasattr(manager, '_processed_events_lock')
        assert hasattr(manager, '_processed_messages_lock')
        assert hasattr(manager, '_processing_events_lock')
        assert hasattr(manager, '_message_locks_lock')
        assert hasattr(manager, '_message_lock_times_lock')


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
