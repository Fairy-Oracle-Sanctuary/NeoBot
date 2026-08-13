#!/usr/bin/env python3
"""
性能分析工具测试

测试各种性能分析功能的正确性和可用性。
"""

import asyncio
import time
import pytest

# 导入性能分析工具
from neobot.core.utils.performance import (
    timeit,
    profile,
    aprofile,
    memory_profile,
    memory_profile_decorator,
    performance_monitor,
    PerformanceStats,
    performance_stats
)


# 重置全局性能统计
def setup_module():
    performance_stats.reset()


def teardown_module():
    performance_stats.reset()


class TestTimeitDecorator:
    """测试 timeit 装饰器"""
    
    @timeit(log_level=20)  # 使用 INFO 级别
    def _test_sync_function(self):
        """测试同步函数的时间测量"""
        time.sleep(0.1)
        return "done"
    
    @timeit(log_level=20)
    async def _test_async_function(self):
        """测试异步函数的时间测量"""
        await asyncio.sleep(0.1)
        return "done"
    
    def test_sync_function_works(self):
        """验证同步函数能正常执行"""
        result = self._test_sync_function()
        assert result == "done"
    
    @pytest.mark.asyncio
    async def test_async_function_works(self):
        """验证异步函数能正常执行"""
        result = await self._test_async_function()
        assert result == "done"


class TestProfileContextManager:
    """测试 profile 上下文管理器"""
    
    def test_profile_sync_code(self):
        """测试同步代码的性能分析"""
        # 捕获标准输出
        import io
        from contextlib import redirect_stdout
        
        f = io.StringIO()
        with redirect_stdout(f):
            with profile(enabled=False):  # 禁用实际分析以提高测试速度
                time.sleep(0.01)
        
        output = f.getvalue()
        # 应该没有输出（因为 enabled=False）
        assert "性能分析" not in output
    
    @pytest.mark.asyncio
    async def test_aprofile_async_function(self):
        """测试异步函数的性能分析"""
        async def async_test():
            await asyncio.sleep(0.01)
            return "test"
        
        result = await aprofile(async_test)
        assert result == "test"


class TestPerformanceMonitor:
    """测试 performance_monitor 装饰器"""
    
    @performance_monitor(threshold=0.05)
    def _test_slow_sync_function(self):
        """测试慢速同步函数的监控"""
        time.sleep(0.1)  # 超过阈值
        return "slow"
    
    @performance_monitor(threshold=0.05)
    def _test_fast_sync_function(self):
        """测试快速同步函数的监控"""
        time.sleep(0.01)  # 低于阈值
        return "fast"
    
    @performance_monitor(threshold=0.05)
    async def _test_slow_async_function(self):
        """测试慢速异步函数的监控"""
        await asyncio.sleep(0.1)
        return "slow_async"
    
    def test_slow_function_triggers_warning(self):
        """验证慢速函数会触发警告"""
        result = self._test_slow_sync_function()
        assert result == "slow"
    
    def test_fast_function_no_warning(self):
        """验证快速函数不会触发警告"""
        result = self._test_fast_sync_function()
        assert result == "fast"
    
    @pytest.mark.asyncio
    async def test_slow_async_function_triggers_warning(self):
        """验证慢速异步函数会触发警告"""
        result = await self._test_slow_async_function()
        assert result == "slow_async"


class TestMemoryAnalysis:
    """测试内存分析功能"""
    
    def test_memory_profile_context_manager(self):
        """测试内存分析上下文管理器"""
        # 禁用内存分析以提高测试速度
        with memory_profile(enabled=False):
            data = [i for i in range(1000)]
            sum(data)
    
    @memory_profile_decorator
    def test_memory_intensive_function(self):
        """测试内存密集型函数"""
        # 小数据集，避免测试耗时过长
        data = [i for i in range(1000)]
        _ = sum(data)
    
    def test_memory_function_works(self):
        """验证内存分析函数能正常执行"""
        self.test_memory_intensive_function()


class TestPerformanceStats:
    """测试性能统计功能"""
    
    def test_stats_initialization(self):
        """测试性能统计对象初始化"""
        stats = PerformanceStats()
        assert isinstance(stats, PerformanceStats)
        assert stats.stats == {}
    
    def test_stats_record(self):
        """测试记录性能数据"""
        stats = PerformanceStats()
        stats.record("test_func", 0.1)
        
        assert "test_func" in stats.stats
        assert stats.stats["test_func"]["count"] == 1
        assert stats.stats["test_func"]["total_time"] == 0.1
        assert stats.stats["test_func"]["avg_time"] == 0.1
    
    def test_stats_report(self):
        """测试生成性能报告"""
        stats = PerformanceStats()
        stats.record("func1", 0.1)
        stats.record("func2", 0.2)
        
        report = stats.report()
        assert isinstance(report, str)
        assert "func1" in report
        assert "func2" in report
    
    def test_stats_reset(self):
        """测试重置性能统计"""
        stats = PerformanceStats()
        stats.record("test_func", 0.1)
        stats.reset()
        
        assert stats.stats == {}
        
    def test_global_stats_recording(self):
        """测试全局性能统计记录"""
        # 先重置全局统计
        performance_stats.reset()
        
        @timeit(collect_stats=True)
        def test_func():
            time.sleep(0.01)
        
        test_func()
        
        # 验证是否记录了性能数据（使用 qualname）
        key = next((k for k in performance_stats.stats if k.endswith("test_func")), None)
        assert key is not None
        assert performance_stats.stats[key]["count"] == 1


class TestIntegration:
    """综合测试"""
    
    @pytest.mark.asyncio
    async def test_combined_features(self):
        """测试多种性能分析功能的组合使用"""
        # 重置全局统计
        performance_stats.reset()
        
        @timeit(collect_stats=True)
        @performance_monitor(threshold=0.05)
        async def test_async_func():
            await asyncio.sleep(0.06)  # 超过阈值
            return "combined"
        
        result = await test_async_func()
        assert result == "combined"
        
        # 验证性能统计（键名包含测试函数所在作用域的 qualname）
        key = next((k for k in performance_stats.stats if k.endswith("test_async_func")), None)
        assert key is not None, f"期望 'test_async_func' 在统计中，但得到: {list(performance_stats.stats.keys())}"
        assert performance_stats.stats[key]["count"] == 1


if __name__ == "__main__":
    # 运行基本测试
    print("开始性能分析功能测试...")
    
    # 测试同步函数
    @timeit
    def test_sync():
        time.sleep(0.1)
        return "sync"
    
    # 测试异步函数
    @timeit
    async def test_async():
        await asyncio.sleep(0.1)
        return "async"
    
    # 测试性能监控
    @performance_monitor(threshold=0.05)
    def slow_func():
        time.sleep(0.1)
        return "slow"
    
    # 运行测试
    sync_result = test_sync()
    async_result = asyncio.run(test_async())
    slow_result = slow_func()
    
    print("\n测试结果:")
    print(f"sync_result: {sync_result}")
    print(f"async_result: {async_result}")
    print(f"slow_result: {slow_result}")
    
    # 输出性能统计报告
    print("\n性能统计报告:")
    print(performance_stats.report())
    
    print("\n性能分析功能测试完成！")
