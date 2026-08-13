#!/usr/bin/env python3
"""
性能分析工具模块

提供同步和异步函数的性能分析装饰器、上下文管理器和统计工具。

主要功能：
1. 函数执行时间分析（支持同步和异步）
2. 内存使用分析
3. 性能统计和报告生成
4. 低开销的生产环境监控
"""

import time
import functools
import logging
from typing import Dict, Any, Callable, Optional
import inspect

# 尝试导入性能分析库
try:
    from pyinstrument import Profiler
    from pyinstrument.renderers import HTMLRenderer
    PYINSTRUMENT_AVAILABLE = True
except ImportError:
    PYINSTRUMENT_AVAILABLE = False

# 尝试导入内存分析库
try:
    from memory_profiler import memory_usage
    MEMORY_PROFILER_AVAILABLE = True
except ImportError:
    MEMORY_PROFILER_AVAILABLE = False

from .logger import logger


class PerformanceStats:
    """
    性能统计工具类
    用于收集和报告函数执行的性能指标
    """
    def __init__(self):
        self.stats: Dict[str, Dict[str, Any]] = {}
        
    def record(self, func_name: str, duration: float, memory_used: Optional[float] = None):
        """
        记录函数执行的性能数据
        
        Args:
            func_name: 函数名称
            duration: 执行时间（秒）
            memory_used: 使用的内存（MB），可选
        """
        if func_name not in self.stats:
            self.stats[func_name] = {
                "count": 0,
                "total_time": 0.0,
                "avg_time": 0.0,
                "min_time": float('inf'),
                "max_time": 0.0,
                "total_memory": 0.0,
                "avg_memory": 0.0
            }
        
        stat = self.stats[func_name]
        stat["count"] += 1
        stat["total_time"] += duration
        stat["avg_time"] = stat["total_time"] / stat["count"]
        stat["min_time"] = min(stat["min_time"], duration)
        stat["max_time"] = max(stat["max_time"], duration)
        
        if memory_used is not None:
            stat["total_memory"] += memory_used
            stat["avg_memory"] = stat["total_memory"] / stat["count"]
    
    def report(self) -> str:
        """
        生成性能统计报告
        
        Returns:
            格式化的性能统计报告字符串
        """
        if not self.stats:
            return "暂无性能统计数据"
        
        report = ["\n=== 性能统计报告 ===\n"]
        report.append(f"{'函数名':<40} {'调用次数':<10} {'平均时间(ms)':<15} {'最长时间(ms)':<15} {'内存(MB)':<10}")
        report.append("-" * 100)
        
        for func_name, stat in sorted(self.stats.items(), key=lambda x: x[1]["total_time"], reverse=True):
            memory_str = f"{stat['avg_memory']:.2f}" if stat['avg_memory'] > 0 else "-"
            report.append(
                f"{func_name:<40} {stat['count']:<10} {stat['avg_time']*1000:<15.2f} "
                f"{stat['max_time']*1000:<15.2f} {memory_str:<10}"
            )
        
        report.append("=" * 100)
        return "\n".join(report)
    
    def reset(self):
        """
        重置性能统计数据
        """
        self.stats.clear()


# 创建全局性能统计实例
performance_stats = PerformanceStats()


def timeit(func: Optional[Callable] = None, *, log_level: int = logging.INFO, collect_stats: bool = True):
    """
    函数执行时间分析装饰器（支持同步和异步）
    
    Args:
        func: 要装饰的函数
        log_level: 日志级别
        collect_stats: 是否收集到全局统计中
    
    Returns:
        装饰后的函数
    """
    def decorator(func: Callable) -> Callable:
        func_name = func.__qualname__
        is_coroutine = inspect.iscoroutinefunction(func)
        
        if is_coroutine:
            @functools.wraps(func)
            async def async_wrapper(*args, **kwargs):
                start_time = time.perf_counter()
                try:
                    result = await func(*args, **kwargs)
                finally:
                    end_time = time.perf_counter()
                    duration = end_time - start_time
                    
                    if collect_stats:
                        performance_stats.record(func_name, duration)
                    
                    logger.log(log_level, f"[性能] {func_name} 执行时间: {duration*1000:.2f} ms")
                
                return result
            
            return async_wrapper
        else:
            @functools.wraps(func)
            def sync_wrapper(*args, **kwargs):
                start_time = time.perf_counter()
                try:
                    result = func(*args, **kwargs)
                finally:
                    end_time = time.perf_counter()
                    duration = end_time - start_time
                    
                    if collect_stats:
                        performance_stats.record(func_name, duration)
                    
                    logger.log(log_level, f"[性能] {func_name} 执行时间: {duration*1000:.2f} ms")
                
                return result
            
            return sync_wrapper
    
    if func is None:
        return decorator
    return decorator(func)


class profile:
    """
    性能分析上下文管理器
    使用 pyinstrument 进行详细的性能分析
    """
    def __init__(self, enabled: bool = True, output_file: Optional[str] = None):
        """
        Args:
            enabled: 是否启用分析
            output_file: 分析结果输出文件路径（HTML格式）
        """
        self.enabled = enabled
        self.output_file = output_file
        self.profiler = None
    
    def __enter__(self):
        if self.enabled and PYINSTRUMENT_AVAILABLE:
            self.profiler = Profiler()
            self.profiler.start()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.enabled and PYINSTRUMENT_AVAILABLE and self.profiler:
            self.profiler.stop()
            
            # 输出到日志
            logger.info(f"[性能分析] {self.profiler.print()}")
            
            # 如果指定了输出文件，保存为HTML
            if self.output_file:
                try:
                    html = self.profiler.render(HTMLRenderer())
                    with open(self.output_file, 'w', encoding='utf-8') as f:
                        f.write(html)
                    logger.info(f"[性能分析] 报告已保存到: {self.output_file}")
                except Exception as e:
                    logger.error(f"[性能分析] 保存报告失败: {e}")


async def aprofile(func: Callable, *args, **kwargs):
    """
    异步函数性能分析
    
    Args:
        func: 要分析的异步函数
        *args: 函数参数
        **kwargs: 函数关键字参数
    
    Returns:
        函数执行结果
    """
    if not PYINSTRUMENT_AVAILABLE:
        logger.warning("[性能分析] pyinstrument 未安装，无法进行详细分析")
        return await func(*args, **kwargs)
    
    profiler = Profiler()
    profiler.start()
    
    try:
        result = await func(*args, **kwargs)
    finally:
        profiler.stop()
        logger.info(f"[性能分析] {profiler.print()}")
    
    return result


class memory_profile:
    """
    内存分析上下文管理器
    """
    def __init__(self, interval: float = 0.1, enabled: bool = True):
        """
        Args:
            interval: 内存采样间隔（秒）
            enabled: 是否启用内存分析
        """
        self.interval = interval
        self.enabled = enabled
        self.memory_start = 0.0
        self.memory_end = 0.0
    
    def __enter__(self):
        if self.enabled and MEMORY_PROFILER_AVAILABLE:
            self.memory_start = memory_usage()[0]
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.enabled and MEMORY_PROFILER_AVAILABLE:
            self.memory_end = memory_usage()[0]
            memory_used = self.memory_end - self.memory_start
            logger.info(f"[内存分析] 使用内存: {memory_used:.2f} MB")


def memory_profile_decorator(func: Optional[Callable] = None, *, interval: float = 0.1):
    """
    内存分析装饰器（支持同步函数）
    
    Args:
        func: 要装饰的函数
        interval: 内存采样间隔
    
    Returns:
        装饰后的函数
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            if not MEMORY_PROFILER_AVAILABLE:
                return func(*args, **kwargs)
            
            mem_usage = memory_usage(
                (func, args, kwargs),
                interval=interval,
                timeout=None,
                include_children=False
            )
            
            max_memory = max(mem_usage)
            logger.info(f"[内存分析] {func.__qualname__} 最大内存使用: {max_memory:.2f} MB")
            return func(*args, **kwargs)
        
        return wrapper
    
    if func is None:
        return decorator
    return decorator(func)


def performance_monitor(func: Optional[Callable] = None, *, threshold: float = 1.0):
    """
    性能监控装饰器
    仅当函数执行时间超过阈值时记录日志
    适合生产环境使用
    
    Args:
        func: 要装饰的函数
        threshold: 时间阈值（秒）
    
    Returns:
        装饰后的函数
    """
    def decorator(func: Callable) -> Callable:
        func_name = func.__qualname__
        is_coroutine = inspect.iscoroutinefunction(func)
        
        if is_coroutine:
            @functools.wraps(func)
            async def async_wrapper(*args, **kwargs):
                start_time = time.perf_counter()
                result = await func(*args, **kwargs)
                end_time = time.perf_counter()
                duration = end_time - start_time
                
                if duration > threshold:
                    logger.warning(f"[性能监控] {func_name} 执行时间过长: {duration*1000:.2f} ms (阈值: {threshold*1000:.2f} ms)")
                
                return result
            
            return async_wrapper
        else:
            @functools.wraps(func)
            def sync_wrapper(*args, **kwargs):
                start_time = time.perf_counter()
                result = func(*args, **kwargs)
                end_time = time.perf_counter()
                duration = end_time - start_time
                
                if duration > threshold:
                    logger.warning(f"[性能监控] {func_name} 执行时间过长: {duration*1000:.2f} ms (阈值: {threshold*1000:.2f} ms)")
                
                return result
            
            return sync_wrapper
    
    if func is None:
        return decorator
    return decorator(func)


# 全局实例
global_stats = PerformanceStats()


__all__ = [
    'timeit',
    'profile',
    'aprofile',
    'memory_profile',
    'memory_profile_decorator',
    'performance_monitor',
    'PerformanceStats',
    'performance_stats',
    'global_stats'
]
