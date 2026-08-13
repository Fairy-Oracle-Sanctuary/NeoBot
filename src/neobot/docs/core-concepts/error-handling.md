# 错误处理机制

NEO Bot 采用了统一的错误处理机制，确保在各种异常情况下提供清晰、一致的错误信息。本文档将介绍系统的错误处理架构、错误码定义和使用方法。

## 1. 错误处理架构

### 1.1 自定义异常体系

系统定义了一套完整的自定义异常类体系，覆盖了各种常见的错误场景：

- **WebSocket 相关错误**：`WebSocketError`、`WebSocketConnectionError`、`WebSocketAuthenticationError`
- **插件相关错误**：`PluginError`、`PluginLoadError`、`PluginReloadError`、`PluginNotFoundError`
- **配置相关错误**：`ConfigError`、`ConfigNotFoundError`、`ConfigValidationError`
- **权限相关错误**：`NeoPermissionError`（命名为 `NeoPermissionError` 以避免覆盖 Python 内置的 `PermissionError`）
- **命令相关错误**：`CommandError`、`CommandNotFoundError`、`CommandParameterError`
- **Redis 相关错误**：`RedisError`
- **浏览器管理器相关错误**：`BrowserManagerError`、`BrowserPoolError`
- **代码执行相关错误**：`CodeExecutionError`

所有自定义异常类都位于 `neobot.core.utils.exceptions` 模块中。

### 1.2 统一的错误码系统

系统使用统一的错误码来标识不同类型的错误，错误码规则如下：

- `1xxx`：系统级错误
- `2xxx`：WebSocket 相关错误
- `3xxx`：插件相关错误
- `4xxx`：配置相关错误
- `5xxx`：权限相关错误
- `6xxx`：命令相关错误
- `7xxx`：Redis 相关错误
- `8xxx`：浏览器管理器相关错误
- `9xxx`：代码执行相关错误

完整的错误码定义可以在 `neobot.core.utils.error_codes` 模块的 `ErrorCode` 类中找到。

### 1.3 统一的错误响应格式

系统提供了统一的错误响应格式，确保所有模块返回一致的错误信息：

```json
{
  "code": 错误代码,
  "message": 错误消息,
  "success": false,
  "data": 附加数据（可选）,
  "request_id": 请求ID（可选）
}
```

## 2. 日志记录增强

### 2.1 模块专用日志记录器

系统提供了 `ModuleLogger` 类，用于创建模块专用的日志记录器，自动添加模块标识：

```python
from neobot.core.utils.logger import ModuleLogger

# 创建模块专用日志记录器
logger = ModuleLogger("MyModule")

# 使用日志记录器
logger.info("模块初始化完成")
logger.error("发生错误")
logger.exception("发生异常")
```

### 2.2 异常详情记录

系统提供了 `log_exception` 函数，用于记录自定义异常的详细信息：

```python
from neobot.core.utils.logger import log_exception
from neobot.core.utils.exceptions import PluginError

try:
    # 代码逻辑
    raise PluginError("test_plugin", "插件加载失败")
except Exception as e:
    log_exception(e, module_name="PluginManager")
```

## 3. 核心模块的错误处理

### 3.1 WebSocket 模块

WebSocket 模块使用自定义异常类处理各种连接错误：

- `WebSocketConnectionError`：连接失败
- `WebSocketAuthenticationError`：认证失败
- `WebSocketError`：其他 WebSocket 相关错误

### 3.2 插件管理器模块

插件管理器模块使用自定义异常类处理各种插件操作错误：

- `PluginLoadError`：插件加载失败
- `PluginReloadError`：插件重载失败
- `PluginNotFoundError`：插件未找到

### 3.3 配置加载器模块

配置加载器模块使用自定义异常类处理各种配置加载错误：

- `ConfigNotFoundError`：配置文件未找到
- `ConfigValidationError`：配置验证失败
- `ConfigError`：其他配置相关错误

## 4. 全局异常捕获

系统在主程序入口添加了全局异常捕获机制，确保所有未处理的异常都能被捕获并提供友好的错误信息：

- 捕获并记录所有未处理的异常
- 生成统一格式的错误响应
- 根据错误类型给出不同的排查建议
- 提供详细的错误信息和日志记录位置

## 5. 如何在插件中使用错误处理

### 5.1 抛出自定义异常

在插件中，您可以使用系统提供的自定义异常类来抛出更精确的错误：

```python
from neobot.core.utils.exceptions import CommandParameterError
from neobot.core.utils.logger import ModuleLogger

logger = ModuleLogger("MyPlugin")

@matcher.command("test")
async def test_command(bot, event, args):
    if len(args) < 1:
        raise CommandParameterError("test", "缺少必要参数")
    
    # 命令逻辑
```

### 5.2 捕获并处理异常

在插件中，您可以捕获并处理异常，提供更友好的错误信息：

```python
from neobot.core.utils.exceptions import PluginError
from neobot.core.utils.logger import ModuleLogger

logger = ModuleLogger("MyPlugin")

@matcher.command("test")
async def test_command(bot, event, args):
    try:
        # 可能抛出异常的代码
        result = await some_operation()
        await bot.send(event, f"操作结果: {result}")
    except PluginError as e:
        logger.error(f"插件操作失败: {e}")
        await bot.send(event, f"操作失败: {e.message}")
    except Exception as e:
        logger.exception(f"发生未知错误: {e}")
        await bot.send(event, "操作失败，请检查日志获取详细信息")
```

## 6. 错误排查建议

### 6.1 WebSocket 错误

- 检查 WebSocket 服务是否正在运行
- 检查配置文件中的 WebSocket 地址和令牌是否正确
- 检查网络连接是否正常

### 6.2 插件错误

- 检查插件目录是否存在
- 检查插件文件是否有语法错误
- 检查插件是否符合插件开发规范

### 6.3 配置错误

- 检查配置文件 config.toml 是否存在
- 检查配置文件格式是否正确
- 检查所有必填配置项是否都已设置

## 7. 总结

NEO Bot 的错误处理机制提供了：

- 完整的自定义异常类体系
- 统一的错误码系统
- 一致的错误响应格式
- 增强的日志记录功能
- 全局异常捕获和友好提示

这些功能确保了系统在各种异常情况下都能提供清晰、一致的错误信息，便于开发和维护。