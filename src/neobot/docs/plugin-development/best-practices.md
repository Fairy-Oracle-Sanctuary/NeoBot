# 插件开发最佳实践

写插件很简单，但写出**高性能、不炸裂**的插件需要遵守规矩。

## 1. 绝对不要阻塞事件循环。。。

这是底线。NEO Bot 是单线程异步架构，如果你在主线程里 `time.sleep(5)`，整个机器人就会卡死 5 秒

*   **错误**: `time.sleep(1)`, `requests.get(...)`, 大量 CPU 计算。
*   **正确**: `await asyncio.sleep(1)`, `await session.get(...)`。

如果你必须运行同步代码（比如图像处理、复杂计算）：
```python
from neobot.plugin_api import run_in_thread_pool

# 扔到线程池里去跑，别占着主线程
result = await run_in_thread_pool(heavy_function, arg1, arg2)
```

## 2. 复用资源

别每次都创建新的连接。

*   **HTTP 请求**: 在模块级复用一个 `aiohttp.ClientSession`，不要每次请求都新建。
    ```python
    import aiohttp

    # 模块级单例，整个插件生命周期复用
    _session = aiohttp.ClientSession()

    async def fetch(url: str):
        async with _session.get(url) as resp:
            return await resp.text()
    ```
*   **浏览器**: 必须使用 `browser_manager.get_page()`，严禁自己 `playwright.chromium.launch()`。

## 3. 善用缓存

如果你的插件需要查外部 API（比如查天气、查 B 站），记得加缓存。
Redis 就在那里，不用白不用。

```python
from neobot.plugin_api import redis_manager

# 存（带过期时间）
await redis_manager.set("weather:beijing", "sunny", ex=3600)
# 取
weather = await redis_manager.get("weather:beijing")
```

## 4. 类型提示 (Type Hinting)

我开启了 Mypyc 编译，这意味着你的代码最好有规范的类型提示。
这不仅是为了编译，也是为了让你自己少写 Bug

```python
# 好的写法
async def handle(event: MessageEvent, args: list[str]) -> None:
    ...

# 不好写法
async def handle(event, args):
    ...
```

## 5. 异常处理

别让你的插件因为一个报错就崩溃机器人
虽然框架层有捕获机制，但你自己处理好异常是最好的。。。

```python
try:
    await do_something()
except Exception as e:
    logger.error(f"插件炸了: {e}")
    await event.reply("出错了，请稍后再试。")
```
