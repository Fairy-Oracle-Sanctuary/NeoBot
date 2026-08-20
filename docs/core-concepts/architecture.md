# 架构设计

NEO Bot 是一个现代化的、高性能的异步 QQ 机器人框架。本文介绍其核心架构和设计理念。

## 1. 性能优化体系

### Python 3.14 JIT（Just-In-Time 编译，可选）

**原理**：Python 3.14 内置 JIT 编译器，运行时将高频调用的代码编译成机器码。

**适用场景**：
- 插件业务逻辑（循环、函数调用密集）
- 消息处理流程

**启用方法**（仅 Python 3.14+ 支持）：

```bash
python -X jit main.py
# 或同时关闭 GIL（实验性）
python -X jit -X gil=0 main.py
```

**注意**：项目基线为 Python 3.11+，JIT 为可选优化，普通部署无需开启。

预期性能提升：2-5 倍（取决于代码热点）。

### Mypyc 编译（AOT - Ahead-Of-Time，可选）

**原理**：将类型注解的 Python 代码编译为 C 扩展，生成平台相关的二进制文件（Windows 为 `.pyd`，Linux 为 `.so`）。

**编译范围**（见 `scripts/compile_machine_code.py`）：
- `core/utils/` - executor、exceptions、logger
- `core/ws.py` - WebSocket 通信
- `core/config_loader.py` - 配置加载
- `models/` - message、sender、objects 数据模型

**启用方法**：

```bash
python scripts/compile_machine_code.py
```

**注意**：编译产物平台相关，必须在目标环境编译；需要安装 C 编译器与 `pip install mypyc`。

### 异步 IO 模型

**Linux**：`uvloop`（libev 绑定，比 asyncio 快 2-4 倍）
**Windows**：IOCP（Windows 原生高性能 IO）

## 2. 连接架构

### WebSocket 连接模式

NEO Bot 支持两种 WebSocket 连接模式，可根据需求在 `config.toml` 中配置：

#### 1. 正向 WebSocket 连接 (默认)
Bot 主动连接 OneBot 实现（如 NapCatQQ）。

**流程**：

```
Bot 启动 → 连接到 NapCatQQ (ws://127.0.0.1:3001)
        ↓
    监听消息事件
        ↓
    分发到处理器
        ↓
    调用 API 回复
```

#### 2. 反向 WebSocket 连接
OneBot 客户端主动连接 Bot 提供的 WebSocket 服务。

**流程**：

```
Bot 启动反向 WS 服务 (监听 0.0.0.0:3002)
        ↓
NapCatQQ 主动连接到 Bot
        ↓
    监听消息事件
        ↓
    分发到处理器
        ↓
    调用 API 回复
```

## 3. 资源管理架构

### 单例管理器

所有全局资源通过单例管理器统一管理，避免重复创建和资源泄漏。

### Playwright 页面池

预初始化页面，无需每次都启动浏览器，大幅降低延迟。

### HTTP 连接复用

全局 aiohttp.ClientSession 支持 Keep-Alive，减少连接建立开销。

## 4. 技术栈全景

NEO Bot 的“骨架”是由一堆现代 Python 库和技术堆起来的。下面这张清单能让你一眼看清整个项目的技术选型。

### 编程语言与运行时
*   **Python 3.11+**: 项目基线版本（推荐 3.12+）
*   **JIT (Just-In-Time，可选)**: Python 3.14 启动时加 `-X jit` 参数，运行时把热点代码编译成机器码
*   **Mypyc (AOT，可选)**: 用 `scripts/compile_machine_code.py` 将核心模块编译成 C 扩展，机器码运行

### 异步与网络
*   **asyncio**: Python 原生异步框架，所有 IO 操作都是非阻塞的
*   **uvloop (Linux)**: 替代 asyncio 默认事件循环，性能更高
*   **IOCP (Windows)**: Windows 上的高性能 IO 完成端口
*   **aiohttp**: 异步 HTTP 客户端/服务器，用于 API 请求和 WebSocket 通信
*   **websockets**: 纯粹的 WebSocket 客户端/服务器库
*   **Playwright**: 浏览器自动化工具，负责截图、页面渲染

### 数据与存储
*   **Redis**: 内存数据库，用于缓存帮助图片、会话状态等
*   **orjson**: Rust 编写的 JSON 序列化库，比标准 `json` 快很多
*   **Pydantic**: 数据验证与设置管理，配置文件、API 请求/响应都靠它

### 工具与工具链
*   **Loguru**: 结构化日志记录，输出漂亮且支持文件轮转
*   **Watchdog**: 文件系统监控，实现插件热重载
*   **Jinja2**: 模板引擎，渲染 HTML 页面然后转为图片
*   **Pillow**: 图像处理库，负责图片格式转换、尺寸调整
*   **BeautifulSoup4**: HTML 解析，B站、抖音等链接解析插件在用
*   **httpx**: 异步 HTTP 客户端，某些插件用它发请求

### 测试与开发
*   **Pytest**: 测试框架，写单元测试、集成测试
*   **Docker**: 容器化，沙箱执行用户代码时可能用到
*   **cryptography**: 加密解密，处理一些安全相关的操作

### 架构模式
*   **Singleton (单例)**: 全局唯一实例，所有管理器都是单例
*   **Connection Pool (连接池)**: Redis 连接、HTTP 会话都复用
*   **Plugin System (插件系统)**: 动态导入、装饰器注册，一个 `.py` 文件就是一个插件

## 5. Python 动态语言特性运用

Python 是一门“动态”语言，这意味着你可以在运行时做很多静态语言做不到的事情。NEO Bot 大量利用了这些特性，让框架变得灵活、易扩展。

### 装饰器 (Decorator)
*   **何用**: 给函数“贴上标签”，告诉框架这个函数是干什么的
*   **何处**: 
    *   `@matcher.command("echo")` – 注册一个消息指令
    *   `@matcher.on_message()` – 注册一个通用消息处理器
    *   `@matcher.on_notice()` – 注册一个通知事件处理器
*   **何原理**: 装饰器本质上是一个高阶函数，它接收被装饰的函数，然后把它“注册”到某个管理器里

### 动态导入 (Dynamic Import)
*   **何用**: 不需要在代码开头写死 `import`，运行时根据情况加载模块
*   **何处**: `PluginManager.load_all_plugins()` 用 `importlib.import_module()` 扫描 `plugins/` 目录，找到 `.py` 文件就导入
*   **何原理**: Python 的模块系统是完全动态的，`import` 语句实际上调用了 `__import__()` 函数

### 自省 (Introspection)
*   **何用**: 让代码能“看到”自己的结构，比如函数属于哪个模块、有哪些参数
*   **何处**: 
    *   `inspect.getmodule(func)` – 获取函数所在的模块名，用于记录插件来源
    *   `func.__name__`, `func.__module__` – 获取函数名和模块名
*   **何原理**: Python 把几乎所有元信息都存在对象的 `__dict__` 里，你可以随时翻看

### 鸭子类型 (Duck Typing)
*   **何用**: “如果它走起来像鸭子，叫起来像鸭子，那它就是鸭子。”——不检查类型，只检查行为
*   **何处**: 
    *   事件处理器不要求事件对象必须是某个类，只要它有 `post_type`、`user_id` 等属性就行
    *   插件不需要继承某个基类，只要它有 `__plugin_meta__` 字典就行
*   **何原理**: Python 的变量没有类型，类型是对象自己的事。只要对象有你需要的方法或属性，你就可以调用它

### 反射 (Reflection)
*   **何用**: 在运行时检查、修改对象的结构
*   **何处**: 
    *   `getattr(module, "__plugin_meta__")` – 获取插件的元数据字典
    *   `hasattr(event, "raw_message")` – 检查事件对象是否有某个属性
    *   `setattr()` – 动态设置属性（虽然用得少）
*   **何原理**: Python 的对象本质上就是字典（`__dict__`），`getattr`/`setattr` 就是对这个字典的操作

### 元编程 (Metaprogramming)
*   **何用**: 在代码运行时改变代码的行为
*   **何处**: 
    *   `Singleton` 基类重写 `__new__` 方法，控制实例创建，确保全局只有一个实例
    *   装饰器在函数定义时修改函数，给它添加额外逻辑
*   **何原理**: Python 的类也是对象（类型对象），你可以通过修改类来影响它所有实例的行为

### 上下文管理器 (Context Manager)
*   **何用**: 安全地获取和释放资源，比如文件、网络连接、浏览器页面
*   **何处**: 
    *   `async with browser_manager.get_page() as page:` – 从页面池获取一个页面，用完后自动放回
    *   `async with aiohttp.ClientSession() as session:` – 发起 HTTP 请求后自动关闭会话
*   **何原理**: `__enter__`/`__exit__`（同步）或 `__aenter__`/`__aexit__`（异步）协议

### 描述符 (Descriptor)
*   **何用**: 控制属性访问的逻辑，比如把方法伪装成属性
*   **何处**: 
    *   `@property` – 把方法变成只读属性，比如 `PluginManager.command_manager`
    *   `@property.setter` – 给属性设置值时的自定义逻辑
*   **何原理**: 描述符是一个实现了 `__get__`、`__set__` 或 `__delete__` 方法的类

### 猴子补丁 (Monkey Patching)
*   **何用**: 在运行时修改模块、类或对象，通常用于测试或修复第三方库
*   **何处**: 测试中可能会用 `unittest.mock.patch` 临时替换某个函数，模拟它的行为
*   **何原理**: Python 的模块和类都是可变的，你可以直接给它们赋值新属性

### eval/exec
*   **何用**: 执行字符串形式的 Python 代码
*   **何处**: `code_py.py` 插件中，用户发送的代码片段会被 `exec()` 执行，实现代码沙箱功能
*   **何原理**: Python 解释器本身就是一个运行时环境，`eval()` 用于表达式，`exec()` 用于语句

### 类型提示 (Type Hints)
*   **何用**: 虽然 Python 是动态类型，但类型提示能让代码更清晰，工具（如 Mypy）也能做静态检查
*   **何处**: 几乎所有函数和方法的参数、返回值都加了类型提示，这让 Mypyc 编译成为可能
*   **何原理**: 类型提示只是注解，运行时通常被忽略（除非你用 `typing` 模块做检查）
