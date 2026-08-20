"""
线程管理器模块

该模块提供了多线程支持，用于处理来自多个实现端的并发事件。
每个 WebSocket 连接在独立的线程中运行，避免阻塞主事件循环。
"""
import asyncio
import inspect
import threading
from typing import Dict, Optional, Callable, Any
from concurrent.futures import ThreadPoolExecutor

from ..utils.logger import ModuleLogger
from ..config_loader import global_config


class ThreadManager:
    """
    线程管理器，负责管理多线程环境下的事件处理。
    
    该管理器为每个 WebSocket 连接提供独立的线程池，
    确保多前端场景下的事件处理不会相互阻塞。
    """
    
    _instance: Optional['ThreadManager'] = None
    _lock: threading.Lock = threading.Lock()
    
    def __new__(cls) -> 'ThreadManager':
        """
        单例模式：确保全局只有一个线程管理器实例。
        """
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance
    
    def __init__(self) -> None:
        """
        初始化线程管理器。
        """
        if self._initialized:
            return
            
        self.logger = ModuleLogger("ThreadManager")
        
        # 线程池配置
        self._max_workers: int = global_config.threading.max_workers
        self._thread_name_prefix: str = global_config.threading.thread_name_prefix
        
        # 线程池
        self._executor: Optional[ThreadPoolExecutor] = None
        
        # 每个客户端的线程池（用于反向 WebSocket）
        self._client_executors: Dict[str, ThreadPoolExecutor] = {}
        self._client_executor_locks: Dict[str, threading.Lock] = {}
        # 实例级锁：保护 _client_executors 的创建（双重检查锁定）
        self._client_executors_lock = threading.Lock()
        
        # 线程安全的事件循环（用于跨线程调用）
        self._event_loops: Dict[str, asyncio.AbstractEventLoop] = {}
        self._event_loops_lock = threading.Lock()
        
        # 统计信息
        self._stats: Dict[str, Any] = {
            'total_tasks': 0,
            'completed_tasks': 0,
            'failed_tasks': 0,
            'active_threads': 0,
            'client_tasks': {}
        }
        self._stats_lock = threading.Lock()
        
        self._initialized = True
        self.logger.success("线程管理器初始化完成")
    
    def start(self) -> None:
        """
        启动线程管理器，创建主线程池。
        """
        if self._executor is None:
            self._executor = ThreadPoolExecutor(
                max_workers=self._max_workers,
                thread_name_prefix=self._thread_name_prefix
            )
            self.logger.success(f"主 ThreadPool 已启动: max_workers={self._max_workers}")
    
    def shutdown(self) -> None:
        """
        关闭线程管理器，释放所有资源。
        """
        self.logger.info("正在关闭线程管理器...")
        
        # 关闭所有客户端线程池
        for client_id, executor in list(self._client_executors.items()):
            self._shutdown_client_executor(client_id)
        
        # 停止所有 per-client 事件循环线程
        with self._event_loops_lock:
            loops = self._event_loops
            self._event_loops = {}
        for loop in loops.values():
            try:
                loop.call_soon_threadsafe(loop.stop)
            except Exception:
                pass
        
        # 关闭主执行器
        if self._executor is not None:
            self._executor.shutdown(wait=True)
            self._executor = None
        
        self.logger.success("线程管理器已关闭")
    
    def _shutdown_client_executor(self, client_id: str) -> None:
        """
        关闭特定客户端的线程池。
        
        Args:
            client_id: 客户端 ID
        """
        if client_id in self._client_executors:
            try:
                self._client_executors[client_id].shutdown(wait=True)
                del self._client_executors[client_id]
                self.logger.info(f"客户端 {client_id} 的线程池已关闭")
            except Exception as e:
                self.logger.error(f"关闭客户端 {client_id} 线程池失败: {e}")

    def remove_client(self, client_id: str) -> None:
        """
        释放特定客户端的全部资源（线程池 + 事件循环线程）。

        客户端断开（如反向 WebSocket 连接关闭）时应调用此方法，
        否则每次连接都会新建线程池/事件循环线程，导致资源无限累积。
        """
        # 停止并清理 per-client 事件循环线程
        with self._event_loops_lock:
            loop = self._event_loops.pop(client_id, None)
        if loop is not None:
            try:
                loop.call_soon_threadsafe(loop.stop)
            except Exception as e:
                self.logger.error(f"停止客户端 {client_id} 事件循环失败: {e}")
        # 关闭 per-client 线程池
        with self._client_executors_lock:
            self._shutdown_client_executor(client_id)
            self._client_executor_locks.pop(client_id, None)
        self.logger.info(f"客户端 {client_id} 的线程资源已清理")
    
    def get_main_executor(self) -> ThreadPoolExecutor:
        """
        获取主线程池。
        
        Returns:
            ThreadPoolExecutor 实例
            
        Raises:
            RuntimeError: 如果线程管理器未启动
        """
        if self._executor is None:
            raise RuntimeError("线程管理器未启动，请先调用 start()")
        return self._executor
    
    def get_client_executor(self, client_id: str) -> ThreadPoolExecutor:
        """
        获取特定客户端的线程池（为反向 WebSocket 设计）。

        Args:
            client_id: 客户端 ID

        Returns:
            ThreadPoolExecutor 实例
        """
        # 快速路径：已存在则直接返回
        if client_id in self._client_executors:
            return self._client_executors[client_id]

        # 慢速路径：使用实例级锁保证双重检查锁定的互斥性
        # 注意：之前使用 threading.Lock() 每次新建锁实例，无法实现互斥
        with self._client_executors_lock:
            if client_id not in self._client_executors:
                executor = ThreadPoolExecutor(
                    max_workers=global_config.threading.client_max_workers,
                    thread_name_prefix=f"{self._thread_name_prefix}_{client_id[:8]}"
                )
                self._client_executors[client_id] = executor
                self._client_executor_locks[client_id] = threading.Lock()
                self.logger.info(f"为客户端 {client_id} 创建线程池")

        return self._client_executors[client_id]
    
    def submit_to_main_executor(
        self,
        func: Callable,
        *args: Any,
        **kwargs: Any
    ) -> Any:
        """
        提交任务到主线程池（同步）。
        
        Args:
            func: 要执行的函数
            *args: 位置参数
            **kwargs: 关键字参数
            
        Returns:
            函数执行结果
        """
        executor = self.get_main_executor()
        future = executor.submit(func, *args, **kwargs)
        self._update_stats('total_tasks')
        try:
            result = future.result()
            self._update_stats('completed_tasks')
            return result
        except Exception as e:
            self._update_stats('failed_tasks')
            self.logger.error(f"主线程池任务执行失败: {e}")
            raise
    
    async def submit_to_main_executor_async(
        self,
        func: Callable,
        *args: Any,
        **kwargs: Any
    ) -> Any:
        """
        提交任务到主线程池（异步）。
        
        Args:
            func: 要执行的函数
            *args: 位置参数
            **kwargs: 关键字参数
            
        Returns:
            函数执行结果
        """
        self._update_stats('total_tasks')
        try:
            if inspect.iscoroutinefunction(func):
                # 协程函数不能提交到线程池执行，直接在当前事件循环中 await
                result = await func(*args, **kwargs)
            else:
                loop = asyncio.get_running_loop()
                executor = self.get_main_executor()
                future = loop.run_in_executor(executor, lambda: func(*args, **kwargs))
                result = await future
            self._update_stats('completed_tasks')
            return result
        except Exception as e:
            self._update_stats('failed_tasks')
            self.logger.error(f"异步主线程池任务执行失败: {e}")
            raise
    
    def submit_to_client_executor(
        self,
        client_id: str,
        func: Callable,
        *args: Any,
        **kwargs: Any
    ) -> Any:
        """
        提交任务到特定客户端的线程池。
        
        Args:
            client_id: 客户端 ID
            func: 要执行的函数
            *args: 位置参数
            **kwargs: 关键字参数
            
        Returns:
            函数执行结果
        """
        executor = self.get_client_executor(client_id)
        future = executor.submit(func, *args, **kwargs)
        self._update_client_stats(client_id, 'total_tasks')
        try:
            result = future.result()
            self._update_client_stats(client_id, 'completed_tasks')
            return result
        except Exception as e:
            self._update_client_stats(client_id, 'failed_tasks')
            self.logger.error(f"客户端 {client_id} 线程池任务执行失败: {e}")
            raise
    
    async def submit_to_client_executor_async(
        self,
        client_id: str,
        func: Callable,
        *args: Any,
        **kwargs: Any
    ) -> Any:
        """
        提交任务到特定客户端的线程池（异步）。
        
        Args:
            client_id: 客户端 ID
            func: 要执行的函数
            *args: 位置参数
            **kwargs: 关键字参数
            
        Returns:
            函数执行结果
        """
        loop = asyncio.get_running_loop()
        executor = self.get_client_executor(client_id)
        future = loop.run_in_executor(executor, lambda: func(*args, **kwargs))
        self._update_client_stats(client_id, 'total_tasks')
        try:
            result = await future
            self._update_client_stats(client_id, 'completed_tasks')
            return result
        except Exception as e:
            self._update_client_stats(client_id, 'failed_tasks')
            self.logger.error(f"客户端 {client_id} 异步线程池任务执行失败: {e}")
            raise
    
    def run_coroutine_threadsafe(
        self,
        coro,
        client_id: Optional[str] = None
    ) -> Any:
        """
        在指定客户端的事件循环中运行协程（线程安全）。
        
        Args:
            coro: 协程对象
            client_id: 客户端 ID，如果为 None 则使用主事件循环
            
        Returns:
            协程执行结果
        """
        if client_id is None:
            loop = asyncio.get_running_loop()
        else:
            with self._event_loops_lock:
                if client_id not in self._event_loops:
                    self._event_loops[client_id] = asyncio.new_event_loop()
                    threading.Thread(
                        target=self._event_loop_thread,
                        args=(client_id,),
                        daemon=True
                    ).start()
                loop = self._event_loops[client_id]
        
        future = asyncio.run_coroutine_threadsafe(coro, loop)
        return future.result()
    
    def _event_loop_thread(self, client_id: str) -> None:
        """
        事件循环线程（用于反向 WebSocket 客户端）。
        
        Args:
            client_id: 客户端 ID
        """
        asyncio.set_event_loop(self._event_loops[client_id])
        self.logger.info(f"事件循环线程启动: client_id={client_id}")
        try:
            self._event_loops[client_id].run_forever()
        finally:
            self._event_loops[client_id].close()
            self.logger.info(f"事件循环线程停止: client_id={client_id}")
    
    def _update_stats(self, key: str) -> None:
        """
        更新全局统计信息。
        
        Args:
            key: 统计项键名
        """
        with self._stats_lock:
            self._stats[key] = self._stats.get(key, 0) + 1
    
    def _update_client_stats(self, client_id: str, key: str) -> None:
        """
        更新客户端统计信息。
        
        Args:
            client_id: 客户端 ID
            key: 统计项键名
        """
        with self._stats_lock:
            if client_id not in self._stats['client_tasks']:
                self._stats['client_tasks'][client_id] = {
                    'total_tasks': 0,
                    'completed_tasks': 0,
                    'failed_tasks': 0
                }
            self._stats['client_tasks'][client_id][key] += 1
    
    def get_stats(self) -> Dict[str, Any]:
        """
        获取统计信息。
        
        Returns:
            统计信息字典
        """
        with self._stats_lock:
            stats = self._stats.copy()
            stats['client_tasks'] = stats.get('client_tasks', {}).copy()
            return stats
    
    def get_active_threads_count(self) -> int:
        """
        获取活动线程数量。
        
        Returns:
            活动线程数量
        """
        import threading
        return sum(
            1 for t in threading.enumerate()
            if t.name.startswith(self._thread_name_prefix)
        )


# 全局线程管理器实例
thread_manager = ThreadManager()
