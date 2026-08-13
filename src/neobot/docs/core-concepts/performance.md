# 性能优化详解

NEO Bot 基于 Python asyncio 构建。为了在高频消息处理、截图渲染和网络请求等场景下保持良好的响应速度，框架在多个层面做了针对性优化。本文逐一介绍这些优化手段。

## 1. Playwright 页面池 (Page Pool)

### 痛点
之前 Bot 发图流程：
1.  用户发指令。
2.  Bot 启动浏览器。
3.  创建新页面。。
4.  渲染，截图。
5.  关闭浏览器。

这种模式下，发一张图至少要等 1 秒以上。。。

### 解决方案
`BrowserManager` 维护了一个**页面池**。
*   **启动时**: 自动预热 3 个页面（可配置），挂在后台待命。
*   **运行时**: 需要截图时，直接从池里 `get_page()`
*   **结束后**: 截图完成，页面执行 `about:blank` 洗白，然后 `release_page()` 放回池里。

### 收益
免去了每次截图都启动浏览器、创建页面和关闭浏览器的开销，发图延迟显著降低。

## 2. Jinja2 模板缓存

### 痛点
每次渲染 HTML，都要从硬盘读文件，然后解析模板语法。硬盘 IO 是慢的，解析也是慢的。

### 解决方案
`ImageManager` 引入了内存缓存 `_template_cache`。
*   第一次读取模板后，编译好的 `Template` 对象直接存入字典。
*   后续请求直接从内存拿对象渲染。

### 收益
省了硬盘IO

## 3. 全局 HTTP 连接复用

### 痛点
插件（如 B站解析）每次请求 API 都创建一个新的 `aiohttp.ClientSession`。
这意味着每次都要进行：DNS 解析 -> TCP 握手 -> SSL 握手。这在 HTTPS 下非常慢。

### 解决方案
我们在插件层提供了一个全局共享的 HTTP 会话（`plugins/web_parser/base.py` 中的 `get_session()`）。
*   全局共享一个 `aiohttp.ClientSession`。
*   复用底层的 TCP 连接 (Keep-Alive)。

### 收益
避免每次请求都重新进行 DNS 解析、TCP 握手和 TLS 握手，显著降低 HTTPS 请求的耗时。

## 4. orjson 极速序列化

### 痛点
Python 自带的 `json` 库性能好像不太好，特别是在处理 OneBot 这种大量 JSON 通信的场景下。

### 解决方案
全面替换为 `orjson`。
*   Rust 编写
*   支持直接返回 `bytes`，减少内存复制。

## 5. Python 3.14 JIT (Just-In-Time Compilation)

### 痛点
Python 解释器一边解析一边执行，遇到循环和函数调用就得反复解释。像消息处理这种高频循环，解释开销就特别明显。

### 解决方案
Python 3.14 自带了一个实验性的 JIT 编译器。启动时加上 `-X jit` 参数，它就会在运行时把热点代码编译成机器码。

**JIT 怎么工作的？**
1.  **监控**: 解释器运行时会统计哪些函数、哪些循环被调最得频繁。
2.  **编译**: 把这些“热点”代码编译成机器码。
3.  **替换**: 下次再执行到这段代码，直接跑机器码，跳过解释步骤。

**哪些代码受益最大？**
-   `plugins/` 里的业务逻辑（比如 B站解析、代码沙箱）。
-   循环密集的操作（比如遍历消息段、处理大量群消息）。
-   频繁调用的工具函数。

### 如何启用？
启动机器人时加上 `-X jit` 参数：

```bash
python -X jit main.py
```

### 收益
*   **热点代码加速**: 经常跑的代码能快 2-10 倍（看具体场景）。
*   **零配置**: 不用改代码，加个启动参数就行。
*   **与 Mypyc 互补**: JIT 负责动态、灵活的插件代码；Mypyc 负责静态、类型明确的核心模块。两者结合，全面覆盖。

## 6. Mypyc 编译 (AOT Compilation)

### 痛点
Python 作为一种解释型语言，在处理 CPU 密集型任务时性能较差。对于机器人框架的核心部分，如 WebSocket 消息解析、事件分发和插件管理，这些代码被高频调用，其性能直接影响机器人的响应速度和吞吐量。

### 解决方案
我们引入了 `Mypyc`，一个将类型注解的 Python 代码编译为高性能 C 扩展的工具。通过项目根目录下的 `scripts/compile_machine_code.py` 脚本，我们可以选择性地将核心模块编译为二进制文件（在 Windows 上是 `.pyd`，在 Linux 上是 `.so`）。

**哪些模块被编译了？**（见 `scripts/compile_machine_code.py` 中的 `MODULES` 列表）
-   `core/ws.py`: WebSocket 消息处理循环，这是整个机器人框架的 I/O 中枢。
-   `core/config_loader.py`: 配置加载模块。
-   `core/utils/executor.py`、`core/utils/exceptions.py`、`core/utils/logger.py`: 高频使用的工具模块。
-   `models/message.py`、`models/sender.py`、`models/objects.py`: 数据模型类，如消息段、发送者等。

这些高频调用的代码路径被编译为接近原生机器码的速度，极大地提升了性能。

### 如何编译？
在项目根目录下运行以下指令：
```bash
python scripts/compile_machine_code.py
```
脚本会自动清理旧的编译产物、查找并编译预设的模块列表。需要先安装 C 编译器（Windows 上为 Visual Studio Build Tools，Linux 上为 GCC）并执行 `pip install mypyc`。

### 特别注意：关于事件模型的编译
`Mypyc` 对 Python 某些动态特性和高级用法支持尚不完善。在实践中，我们发现 `dataclass` 与 `Mypyc` 存在一些兼容性问题，尤其是在使用继承和某些高级特性（如 `slots=True`）时，可能会导致编译失败或运行时错误（例如 `AttributeError: attribute '__dict__' of 'type' objects is not writable`）。

- **当前状态**：为了确保稳定性，`scripts/compile_machine_code.py` 脚本**默认不编译** `models/events/` 目录下的事件模型文件。这些文件虽然也被频繁使用，但它们的结构相对复杂，与 `Mypyc` 的兼容性问题仍在探索中。
- **未来展望**：我们会持续关注 `Mypyc` 的更新，当其对 `dataclass` 的支持得到改善后，会重新尝试将事件模型加入编译列表，以实现极致的性能。

## 7. WebSocket 断线自动重连

### 痛点
在高并发或网络不稳定的情况下，WebSocket 连接可能会因为各种原因（如超时、服务器重启、网络波动）而中断。如果框架无法自动恢复，会导致 API 调用频繁失败，甚至整个机器人无响应，需要人工重启。

### 解决方案
`core/ws.py` 中的 `WS` 类实现了**断线自动重连**机制：

- **自动重连**: 当连接断开时，会在配置的 `reconnect_interval` 秒后自动尝试重新连接，无需人工干预。
- **后台任务管理**: 通过 `_spawn_task` 统一管理后台协程任务，重连、监听循环等任务在关闭时会统一取消，避免资源泄漏。
- **事件分发**: 收到的事件通过 `on_event` 统一分发到框架的消息总线，上层处理逻辑对重连过程完全无感。

### 收益
- **高可用性**: 即使连接中断，机器人也能自动恢复服务，大大减少了因网络问题导致的停机时间。
- **无感切换**: 对于上层调用者（如插件开发者）来说，这一切都是透明的。你只需要正常调用 `bot.call_api()`，重连由底层自动处理。
- **资源安全**: 后台任务有明确的取消与清理路径，长期运行不会累积泄漏。
