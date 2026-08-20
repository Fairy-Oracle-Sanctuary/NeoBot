# 性能优化指南

本文档介绍了 NeoBot 框架的性能优化最佳实践，帮助开发者编写高性能的插件和应用。

## 目录

1. [异步编程](#异步编程)
2. [内存管理](#内存管理)
3. [数据库优化](#数据库优化)
4. [缓存策略](#缓存策略)
5. [代码优化](#代码优化)
6. [监控和诊断](#监控和诊断)

## 异步编程

### 避免阻塞事件循环

NeoBot 基于异步架构，阻塞操作会导致整个应用卡顿。

#### 错误示例

```python
# ❌ 错误：同步阻塞操作
import time
import requests

def slow_operation():
    time.sleep(5)  # 阻塞5秒，整个机器人会卡住
    response = requests.get("https://api.example.com")  # 同步HTTP请求
    return response.text
```

#### 正确示例

```python
# ✅ 正确：异步非阻塞操作
import asyncio
import aiohttp

async def fast_operation():
    await asyncio.sleep(5)  # 异步等待，不会阻塞
    
    timeout = aiohttp.ClientTimeout(total=10)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.get("https://api.example.com") as response:
            return await response.text()
```

### 使用线程池执行同步代码

如果必须使用同步库，应使用线程池：

```python
import asyncio
from concurrent.futures import ThreadPoolExecutor
import some_sync_library

# 创建线程池（全局或模块级）
executor = ThreadPoolExecutor(max_workers=4)

async def async_wrapper():
    loop = asyncio.get_running_loop()

    # 在线程池中执行同步代码
    result = await loop.run_in_executor(
        executor,
        some_sync_library.slow_function,
        arg1, arg2
    )

    return result
```

> 框架内置了统一线程池封装（`neobot.core.utils.executor`），插件中优先使用：

```python
from neobot.core.utils.executor import run_in_thread_pool

async def async_wrapper():
    # 自动提交到框架线程池（大小由 [threading] max_workers 控制）
    result = await run_in_thread_pool(some_sync_library.slow_function, arg1, arg2)
    return result
```

### 批量异步操作

使用 `asyncio.gather` 并行执行多个异步操作：

```python
import asyncio

async def fetch_multiple_urls(urls):
    """并行获取多个URL"""
    tasks = [fetch_single_url(url) for url in urls]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    # 处理结果
    successful = []
    failed = []
    
    for url, result in zip(urls, results):
        if isinstance(result, Exception):
            logger.error(f"获取 {url} 失败: {result}")
            failed.append(url)
        else:
            successful.append(result)
    
    return successful, failed

async def fetch_single_url(url):
    """获取单个URL"""
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            return await response.text()
```

## 内存管理

### 及时释放资源

使用上下文管理器确保资源及时释放：

```python
# ✅ 正确：使用上下文管理器
async def process_file(file_path):
    async with aiofiles.open(file_path, 'r') as f:
        content = await f.read()
    # 文件自动关闭
    
    # 处理内容
    processed = process_content(content)
    
    # 及时释放大对象
    del content  # 如果content很大
    
    return processed
```

### 使用生成器处理大数据

```python
# ✅ 正确：使用生成器逐行处理大文件
async def process_large_file(file_path):
    async with aiofiles.open(file_path, 'r') as f:
        async for line in f:  # 逐行读取，不加载整个文件
            processed_line = process_line(line)
            yield processed_line
```

### 对象池模式

对于频繁创建销毁的对象，使用对象池：

```python
from typing import Dict, Any
import aiohttp

class HttpClientPool:
    """HTTP客户端连接池"""
    
    def __init__(self, max_clients: int = 10):
        self.max_clients = max_clients
        self._clients = []
        self._semaphore = asyncio.Semaphore(max_clients)
    
    async def get_client(self) -> aiohttp.ClientSession:
        """获取客户端（从池中获取或创建新的）"""
        async with self._semaphore:
            if self._clients:
                return self._clients.pop()
            else:
                timeout = aiohttp.ClientTimeout(total=30)
                return aiohttp.ClientSession(timeout=timeout)
    
    async def release_client(self, client: aiohttp.ClientSession):
        """释放客户端回池中"""
        if len(self._clients) < self.max_clients:
            self._clients.append(client)
        else:
            await client.close()
    
    async def cleanup(self):
        """清理所有客户端"""
        for client in self._clients:
            await client.close()
        self._clients.clear()
```

## 数据库优化

### 使用连接池

```python
import aiomysql
from typing import Optional

class DatabasePool:
    """数据库连接池"""
    
    def __init__(self):
        self.pool: Optional[aiomysql.Pool] = None
    
    async def initialize(self, **kwargs):
        """初始化连接池"""
        self.pool = await aiomysql.create_pool(
            minsize=5,      # 最小连接数
            maxsize=20,     # 最大连接数
            pool_recycle=3600,  # 连接回收时间（秒）
            **kwargs
        )
    
    async def execute_query(self, query: str, *args):
        """执行查询"""
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute(query, args)
                return await cursor.fetchall()
    
    async def close(self):
        """关闭连接池"""
        if self.pool:
            self.pool.close()
            await self.pool.wait_closed()
```

> 框架已内置基于 aiomysql 连接池的 `MySQLManager` 单例
> （`neobot.core.managers.mysql_manager`），提供 `execute` / `fetchone` /
> `fetchall` / `begin_transaction` / `commit_transaction` / `rollback_transaction`，
> 插件直接使用即可，无需自行管理连接池。

### 批量操作

```python
# ✅ 正确：批量插入
async def batch_insert_users(users_data):
    """批量插入用户数据"""
    query = "INSERT INTO users (name, email) VALUES (%s, %s)"
    
    # 准备数据
    values = [(user['name'], user['email']) for user in users_data]
    
    async with db_pool.acquire() as conn:
        async with conn.cursor() as cursor:
            await cursor.executemany(query, values)  # 批量执行
        await conn.commit()
```

### 查询优化

```python
# ❌ 错误：N+1查询问题
async def get_users_with_posts():
    users = await get_all_users()
    
    for user in users:
        # 为每个用户单独查询帖子（低效）
        user['posts'] = await get_posts_by_user(user['id'])
    
    return users

# ✅ 正确：使用JOIN或批量查询
async def get_users_with_posts_optimized():
    """一次性获取所有用户及其帖子"""
    query = """
        SELECT u.*, p.id as post_id, p.title, p.content
        FROM users u
        LEFT JOIN posts p ON u.id = p.user_id
        ORDER BY u.id
    """
    
    results = await db_pool.execute_query(query)
    
    # 在内存中分组（比多次数据库查询快）
    users_dict = {}
    for row in results:
        user_id = row['id']
        if user_id not in users_dict:
            users_dict[user_id] = {
                'id': user_id,
                'name': row['name'],
                'email': row['email'],
                'posts': []
            }
        
        if row['post_id']:
            users_dict[user_id]['posts'].append({
                'id': row['post_id'],
                'title': row['title'],
                'content': row['content']
            })
    
    return list(users_dict.values())
```

## 缓存策略

### 内存缓存

```python
from typing import Any, Optional
import asyncio
from datetime import datetime, timedelta

class MemoryCache:
    """内存缓存"""
    
    def __init__(self, default_ttl: int = 300):
        self.cache = {}
        self.default_ttl = default_ttl
        self.locks = {}
    
    async def get(self, key: str) -> Optional[Any]:
        """获取缓存值"""
        if key not in self.cache:
            return None
        
        value, expiry = self.cache[key]
        
        if datetime.now() > expiry:
            del self.cache[key]
            return None
        
        return value
    
    async def set(self, key: str, value: Any, ttl: Optional[int] = None):
        """设置缓存值"""
        if ttl is None:
            ttl = self.default_ttl
        
        expiry = datetime.now() + timedelta(seconds=ttl)
        self.cache[key] = (value, expiry)
    
    async def get_or_set(self, key: str, coroutine, ttl: Optional[int] = None):
        """获取或设置缓存值"""
        # 防止缓存击穿
        if key not in self.locks:
            self.locks[key] = asyncio.Lock()
        
        async with self.locks[key]:
            cached = await self.get(key)
            if cached is not None:
                return cached
            
            # 执行协程获取值
            value = await coroutine
            await self.set(key, value, ttl)
            return value
    
    def clear(self):
        """清空缓存"""
        self.cache.clear()
```

### Redis 缓存

```python
import redis.asyncio as aioredis
from typing import Any, Optional
import json

class RedisCache:
    """Redis缓存"""

    def __init__(self, redis_url: str = "redis://localhost"):
        self.redis_url = redis_url
        self.redis: Optional[aioredis.Redis] = None

    async def initialize(self):
        """初始化Redis连接"""
        self.redis = await aioredis.from_url(
            self.redis_url,
            encoding="utf-8",
            decode_responses=True
        )
    
    async def get(self, key: str) -> Optional[Any]:
        """获取缓存值"""
        if not self.redis:
            return None
        
        value = await self.redis.get(key)
        if value:
            return json.loads(value)
        return None
    
    async def set(self, key: str, value: Any, ttl: int = 300):
        """设置缓存值"""
        if not self.redis:
            return
        
        serialized = json.dumps(value)
        await self.redis.setex(key, ttl, serialized)
    
    async def delete(self, key: str):
        """删除缓存值"""
        if not self.redis:
            return
        
        await self.redis.delete(key)
```

> 框架内部已封装统一的 Redis 客户端（`neobot.core.managers.redis_manager`），
> 单例 `redis_manager` 提供 `get` / `set` / `setex` / `hset` / `publish` /
> `execute_lua_script` 等接口，并自动处理连接池与 pubsub 签名校验，插件无需
> 自行创建连接。原子操作（Lua 脚本）详见
> `docs/core-concepts/redis-atomic-operations.md`。

## 代码优化

### 预编译正则表达式

```python
# ❌ 错误：每次调用都编译正则表达式
def validate_email(email: str) -> bool:
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return bool(re.match(pattern, email))

# ✅ 正确：预编译正则表达式
EMAIL_PATTERN = re.compile(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$')

def validate_email_fast(email: str) -> bool:
    return bool(EMAIL_PATTERN.match(email))
```

### 使用局部变量

```python
# ✅ 正确：使用局部变量加速访问
def process_data(data):
    """处理数据"""
    # 将频繁访问的属性存储到局部变量
    process_func = self.process_func
    threshold = self.threshold
    logger = self.logger
    
    results = []
    for item in data:
        # 使用局部变量，避免每次循环都查找属性
        if process_func(item) > threshold:
            results.append(item)
            logger.debug(f"处理项目: {item}")
    
    return results
```

### 避免不必要的对象创建

```python
# ❌ 错误：在循环中创建不必要的对象
def process_items(items):
    for item in items:
        processor = ItemProcessor()  # 每次循环都创建新对象
        result = processor.process(item)
        # ...

# ✅ 正确：重用对象
def process_items_optimized(items):
    processor = ItemProcessor()  # 只创建一次
    
    for item in items:
        result = processor.process(item)
        # ...
```

### 使用生成器表达式

```python
# ✅ 正确：使用生成器表达式处理大数据
def find_matching_items(items, condition):
    """查找匹配条件的项目"""
    # 生成器表达式，惰性求值
    return (item for item in items if condition(item))

# 使用
matching = find_matching_items(large_list, lambda x: x > 100)
for item in matching:
    process(item)  # 一次处理一个，不占用大量内存
```

## 监控和诊断

### 性能监控装饰器

```python
import time
import functools
from typing import Callable, Any

def monitor_performance(threshold: float = 1.0):
    """性能监控装饰器"""
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def async_wrapper(*args, **kwargs):
            start_time = time.time()
            
            try:
                result = await func(*args, **kwargs)
                return result
            finally:
                elapsed = time.time() - start_time
                
                if elapsed > threshold:
                    logger.warning(
                        f"函数 {func.__name__} 执行时间过长: "
                        f"{elapsed:.3f}秒 (阈值: {threshold}秒)"
                    )
                else:
                    logger.debug(
                        f"函数 {func.__name__} 执行时间: "
                        f"{elapsed:.3f}秒"
                    )
        
        @functools.wraps(func)
        def sync_wrapper(*args, **kwargs):
            start_time = time.time()
            
            try:
                result = func(*args, **kwargs)
                return result
            finally:
                elapsed = time.time() - start_time
                
                if elapsed > threshold:
                    logger.warning(
                        f"函数 {func.__name__} 执行时间过长: "
                        f"{elapsed:.3f}秒 (阈值: {threshold}秒)"
                    )
        
        # 根据函数类型返回对应的包装器
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        else:
            return sync_wrapper
    
    return decorator

# 使用示例
@monitor_performance(threshold=0.5)
async def slow_operation():
    await asyncio.sleep(0.6)  # 超过阈值，会记录警告
```

### 内存使用监控

```python
import psutil
import os

def get_memory_usage():
    """获取内存使用情况"""
    process = psutil.Process(os.getpid())
    
    memory_info = process.memory_info()
    
    return {
        'rss': memory_info.rss / 1024 / 1024,  # 常驻内存 (MB)
        'vms': memory_info.vms / 1024 / 1024,  # 虚拟内存 (MB)
        'percent': process.memory_percent(),   # 内存使用百分比
    }

async def monitor_memory(interval: int = 60):
    """定期监控内存使用"""
    while True:
        memory = get_memory_usage()
        
        if memory['percent'] > 80:
            logger.warning(
                f"内存使用过高: {memory['percent']:.1f}% "
                f"(RSS: {memory['rss']:.1f}MB)"
            )
        
        await asyncio.sleep(interval)
```

### 请求跟踪

```python
from contextlib import contextmanager
import uuid

class RequestTracker:
    """请求跟踪器"""
    
    def __init__(self):
        self.requests = {}
    
    @contextmanager
    def track(self, request_id: str = None):
        """跟踪请求"""
        if request_id is None:
            request_id = str(uuid.uuid4())
        
        start_time = time.time()
        self.requests[request_id] = {
            'start_time': start_time,
            'status': 'processing'
        }
        
        try:
            yield request_id
            status = 'completed'
        except Exception as e:
            status = f'failed: {e}'
            raise
        finally:
            elapsed = time.time() - start_time
            self.requests[request_id]['end_time'] = time.time()
            self.requests[request_id]['elapsed'] = elapsed
            self.requests[request_id]['status'] = status
            
            if elapsed > 5.0:  # 记录慢请求
                logger.warning(
                    f"慢请求 {request_id}: {elapsed:.3f}秒"
                )

# 使用示例
tracker = RequestTracker()

async def handle_request():
    with tracker.track() as request_id:
        # 处理请求
        result = await process_request()
        return result
```

## 总结

性能优化是一个持续的过程，需要：

1. **测量优先**：在优化前先测量性能瓶颈
2. **渐进优化**：一次优化一个瓶颈，验证效果
3. **平衡取舍**：在性能、可读性和维护性之间找到平衡
4. **持续监控**：建立监控系统，及时发现性能问题

遵循这些最佳实践，可以编写出高性能、可扩展的 NeoBot 插件和应用。