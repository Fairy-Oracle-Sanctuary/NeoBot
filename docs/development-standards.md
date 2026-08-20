# NeoBot 开发规范

本文档为 `NeoBot` 项目的官方开发规范，旨在确保代码的高性能、高可读性和高可维护性。所有贡献者都应遵循这些规范。

本文档以 [PEP 8 -- Style Guide for Python Code](https://peps.python.org/pep-0008/) 为基础，并在此之上补充了针对本项目的特定约定。

## 核心开发原则

### 1. 异步优先
**永远不要阻塞事件循环**。任何同步阻塞操作（如 `time.sleep()`、同步网络请求、大规模文件读写）都会导致整个机器人框架卡死。

- **应当**: 使用 `asyncio.sleep()`、异步库（如 `aiohttp`），并通过 `asyncio.to_thread` 或 `run_in_executor` 将同步代码移出主事件循环。
- **禁止**: 直接在异步函数中使用任何可能阻塞的同步调用。

### 1.1 异步优先原则
- **绝对不要阻塞事件循环**：NeoBot 采用多线程异步架构，任何同步阻塞操作都会导致整个机器人卡死。
  - **禁止**：`time.sleep()`、同步 `requests`、密集 CPU 计算
  - **必须**：使用 `await asyncio.sleep()`、异步 HTTP 客户端、线程池执行同步任务

- **应当**: 通过框架提供的单例管理器（如 `redis_manager`, `browser_manager`）获取和管理资源。
- **禁止**: 自行实例化管理器或在插件中创建独立的资源实例（如 `aiohttp.ClientSession`）。

### 3. 错误处理
**健壮性是第一要务**。插件的异常不应影响框架的稳定运行。

- **应当**: 在插件和业务逻辑中进行充分的 `try...except` 异常捕获，并向用户返回友好的错误提示。
- **禁止**: 抛出未被捕获的异常，或向用户暴露原始的错误堆栈信息。

### 4. 跨平台兼容性
代码必须同时兼容 **Windows（开发环境）** 和 **Linux（生产环境）**。

- **应当**: 使用 `pathlib.Path` 处理文件路径，它能自动处理不同操作系统的路径分隔符。
- **禁止**: 硬编码路径分隔符（如 `"data\\temp"` 或 `"data/temp"`）。

## 代码风格规范

### 1. 命名规范 (PEP 8)
- **模块 (Module)**: `lower_case_with_underscores.py`
- **包 (Package)**: `lower_case_with_underscores`
- **类 (Class)**: `PascalCase`
- **函数 (Function) / 方法 (Method) / 变量 (Variable)**: `snake_case`
- **常量 (Constant)**: `UPPER_SNAKE_CASE`
- **私有成员**: 以单下划线 `_` 开头。

### 2. 类型提示 (PEP 484)
**所有函数和方法的签名都必须包含类型提示**。这是强制性要求，因为它对 `Mypyc` 编译和代码可读性至关重要。

- **应当**: 明确指定所有参数和返回值的类型。对于可能返回 `None` 的情况，使用 `Optional[...]`。
- **示例**:
  ```python
  async def get_user_data(user_id: int) -> Optional[Dict[str, Any]]:
      # ...
  ```

### 3. 文档字符串 (PEP 257)
**所有公开的模块、类、函数和方法都必须拥有文档字符串**。

- **格式**: 遵循 Google Python Style Guide 的文档字符串格式。它清晰、简洁且易于阅读。
- **内容**:
    - **模块/类**: 简要描述其职责和功能。
    - **函数/方法**:
        - 一行总结其功能。
        - `Args:`: 描述每个参数的类型和含义。
        - `Returns:`: 描述返回值的类型和含义。
        - `Raises:`: (可选) 描述可能抛出的主要异常。
- **示例**:
  ```python
  async def fetch_data(url: str, timeout: int = 10) -> str:
      """Fetches content from a URL.

      Args:
          url: The URL to fetch from.
          timeout: The request timeout in seconds.

      Returns:
          The content of the response as a string.
      
      Raises:
          asyncio.TimeoutError: If the request times out.
      """
      # ...
  ```

### 4. 导入规范
- **顺序**: 遵循 PEP 8 的建议，将导入分为三组，每组按字母顺序排列：
    1.  **标准库** (e.g., `asyncio`, `sys`)
    2.  **第三方库** (e.g., `aiohttp`, `loguru`)
    3.  **本项目模块** (e.g., `from neobot.core.managers import ...`)
- **绝对导入**: 优先使用绝对导入路径（`from neobot.core.utils import ...`），避免使用相对导入（`from ..utils import ...`），以增强代码清晰度。

### 5. 日志记录
- **应当**: 使用 `from neobot.core.utils.logger import logger` 获取全局日志记录器实例。在需要区分模块来源时，可以使用 `ModuleLogger("MyModule")`。
- **日志级别**:
    - `DEBUG`: 用于详细的诊断信息。
    - `INFO`: 用于记录常规的操作流程。
    - `WARNING`: 用于表示发生了预期内的小问题，或提示潜在风险。
    - `ERROR`: 用于记录影响功能但程序仍可运行的错误。
    - `CRITICAL`: 用于记录导致程序崩溃的严重错误。

## 项目特定约定

### 1. 单例管理器
框架的核心功能由 `neobot/core/managers/` 下的单例管理器提供。

- **获取方式**: 必须通过导入模块级别的实例来使用，例如 `from neobot.core.managers.redis_manager import redis_manager`。
- **核心职责**: 这些管理器负责维护全局状态和资源池，是确保性能和数据一致性的关键。

### 2. 配置管理
- **访问方式**: 所有配置项都应通过 `from neobot.core.config_loader import global_config` 来访问。
- **禁止**: 在代码中硬编码任何配置值（如 API 地址、端口、文件路径等）。

### 3. 插件元信息
每个插件文件都应在顶部定义 `__plugin_meta__` 字典，以供帮助系统使用。

```python
__plugin_meta__ = {
    "name": "插件名称",
    "description": "插件功能的简要描述。",
    "usage": "插件的使用方法，例如 `/command [args]`。"
}
```

## Git 提交约定

为了保持提交历史的清晰，我们采用一种简化的提交信息格式：

`<type>: <subject>`

- **`<type>`**:
    - `feat`: 新功能
    - `fix`: Bug 修复
    - `docs`: 文档变更
    - `style`: 代码格式调整（不影响逻辑）
    - `refactor`: 代码重构
    - `test`: 添加或修改测试
    - `chore`: 构建过程或辅助工具的变动
- **`<subject>`**:
    - 对本次提交的简明扼要的描述。
    - 使用祈使句，例如 `add user authentication` 而不是 `added user authentication`。

**示例**:
```
feat: Add /status command to show bot health
fix: Correctly handle empty messages in parser
docs: Update development standards with new guidelines
```
