# 安全最佳实践

本文档介绍了 NeoBot 框架的安全最佳实践，包括配置安全、输入验证、异常处理等方面。

## 目录

1. [配置安全](#配置安全)
2. [输入验证](#输入验证)
3. [异常处理](#异常处理)
4. [代码执行安全](#代码执行安全)
5. [网络通信安全](#网络通信安全)
6. [文件操作安全](#文件操作安全)

## 配置安全

### 敏感配置管理

框架读取 `config.toml` 作为唯一配置文件（缺失时自动从 `config.example.toml` 生成）。
所有凭据（Redis 密码、MySQL 密码、Bot Token 等）都应写入 `config.toml`，或通过
**环境变量覆盖**，避免把敏感值硬编码在代码里。

#### 使用环境变量覆盖

启动时 `Config` 会读取 `.env` 文件（若存在）并把系统环境变量叠加到配置之上：

```bash
# 示例：用环境变量覆盖 config.toml 中的敏感字段
export MYSQL_PASSWORD=your_secure_password
export REDIS_PASSWORD=your_redis_password
export NAPCAT_WS_URI=ws://localhost:8080
export DISCORD_TOKEN=your_discord_bot_token
export BILIBILI_SESSDATA=your_bilibili_sessdata
export DOUYIN_API_KEY=your_douyin_api_key

python main.py
```

支持覆盖的键（详见 `core/config_loader.py` 的 `_override_with_env_vars`）：

| 环境变量 | 覆盖字段 |
|---|---|
| `MYSQL_HOST` / `MYSQL_PORT` / `MYSQL_USER` / `MYSQL_PASSWORD` / `MYSQL_DB` | `[mysql]` |
| `REDIS_HOST` / `REDIS_PORT` / `REDIS_DB` / `REDIS_PASSWORD` / `REDIS_SIGNING_SECRET` | `[redis]` |
| `NAPCAT_WS_URI` / `NAPCAT_WS_TOKEN` | `[napcat_ws]` |
| `DISCORD_TOKEN` / `DISCORD_PROXY` | `[discord]` |
| `BILIBILI_SESSDATA` / `BILIBILI_BILI_JCT` / `BILIBILI_BUVID3` / `BILIBILI_DEDEUSERID` | `[bilibili]` |
| `DOUYIN_API_KEY` | `[douyin]` |
| `DOCKER_BASE_URL` / `DOCKER_TLS_VERIFY` | `[docker]` |
| `REVERSE_WS_ENABLED` / `REVERSE_WS_HOST` / `REVERSE_WS_PORT` / `REVERSE_WS_TOKEN` | `[reverse_ws]` |
| `LOCAL_FILE_SERVER_ENABLED` / `LOCAL_FILE_SERVER_HOST` / `LOCAL_FILE_SERVER_PORT` | `[local_file_server]` |
| `LOG_LEVEL` / `LOG_FILE_LEVEL` / `LOG_CONSOLE_LEVEL` | `[logging]` |

#### 配置优先级

1. 环境变量（最高优先级）
2. `config.toml` 文件
3. Pydantic 模型默认值（最低优先级）

#### 代码中使用

```python
from neobot.core.utils.env_loader import env_loader

# 加载环境变量（.env 文件 + 系统环境变量）
env_loader.load()

# 获取配置值
mysql_host = env_loader.get("MYSQL_HOST", "localhost")
mysql_port = env_loader.get_int("MYSQL_PORT", 3306)
discord_token = env_loader.get("DISCORD_TOKEN")

# 获取掩码的敏感值（用于日志）
masked_password = env_loader.get_masked("MYSQL_PASSWORD")
# 输出: pa***rd（仅显示前2个和后2个字符）
```

### 配置文件权限检查

框架启动时会自动检查 `config.toml` 的权限，发现不安全权限会输出警告：

```
[WARNING] 配置文件 config.toml 其他用户可读，存在安全风险
[INFO] 建议使用命令: chmod 600 config.toml
```

部署时请确保：

```bash
chmod 600 config.toml
```

## 输入验证

### 输入验证器

NeoBot 提供了全面的输入验证工具（`neobot.core.utils.input_validator`），
内置 SQL 注入、XSS、路径遍历、命令注入等检测模式。

#### 基本使用

```python
from neobot.core.utils.input_validator import input_validator

# 验证 SQL 输入
if not input_validator.validate_sql_input(user_input):
    await event.reply("输入包含不安全字符")

# 验证 XSS 攻击
if not input_validator.validate_xss_input(user_input):
    await event.reply("输入包含不安全内容")

# 验证命令注入
if not input_validator.validate_command_input(user_input):
    await event.reply("输入包含危险命令")

# 验证路径遍历
if not input_validator.validate_path_input(file_path):
    await event.reply("文件路径不安全")
```

#### 综合验证

```python
# 执行所有默认验证（sql / xss / path / command）
results = input_validator.validate_all(user_input)
# results = {'sql': True, 'xss': True, 'path': True, 'command': True}

# 自定义验证类型
results = input_validator.validate_all(
    user_input,
    validation_types=['sql', 'xss', 'email', 'url']
)
```

#### 数据清理

```python
# 清理 HTML，防止 XSS
safe_html = input_validator.sanitize_html(user_html_input)

# 清理 SQL，防止注入
safe_sql = input_validator.sanitize_sql(user_sql_input)
```

### 插件中的输入验证

#### 天气插件示例

```python
from neobot.core.managers.command_manager import matcher
from neobot.core.utils.input_validator import input_validator
from neobot.models import MessageEvent
from typing import List

@matcher.command("天气")
async def handle_weather(bot, event: MessageEvent, args: List[str]):
    city_input = args[0].strip()

    # 输入验证
    if not input_validator.validate_sql_input(city_input):
        await event.reply("输入包含不安全字符，请重新输入。")
        return

    if not input_validator.validate_xss_input(city_input):
        await event.reply("输入包含不安全内容，请重新输入。")
        return

    # 继续处理...
```

## 异常处理

### 最佳实践

1. **避免裸异常捕获**：
   ```python
   # 错误做法
   try:
       # 一些操作
   except Exception:
       pass

   # 正确做法
   try:
       # 一些操作
   except (ValueError, TypeError) as e:
       logger.error(f"处理数据时出错: {e}")
   except ConnectionError as e:
       logger.error(f"网络连接失败: {e}")
   ```

2. **提供有意义的错误信息**：
   ```python
   try:
       result = await some_async_operation()
   except asyncio.TimeoutError:
       await event.reply("操作超时，请稍后重试")
   except aiohttp.ClientError as e:
       logger.error(f"网络请求失败: {e}")
       await event.reply("网络请求失败，请检查网络连接")
   ```

3. **记录异常堆栈**：
   ```python
   try:
       # 一些操作
   except Exception as e:
       logger.exception(f"处理消息时发生未预期错误: {e}")
       # 不要向用户暴露堆栈信息
       await event.reply("处理消息时发生错误，请稍后重试")
   ```

### 框架提供的异常类

框架在 `neobot.core.utils.exceptions` 中定义了完整的异常体系：

```python
from neobot.core.utils.exceptions import (
    ConfigError,
    ConfigNotFoundError,
    ConfigValidationError,
    NeoPermissionError,
    PluginError,
    WebSocketError,
    RedisError,
    BrowserManagerError,
    CodeExecutionError,
    CommandError,
)
```

使用示例：

```python
from neobot.core.utils.logger import logger

# 配置错误（加载 config.toml 时由 ConfigLoader 抛出）
try:
    # 应用启动阶段 ConfigLoader 会完成加载，这里通常无需手动构造
    ...
except ConfigValidationError as e:
    logger.error(f"配置验证失败: {e}")
    if e.original_error:
        logger.error(f"原始错误: {e.original_error}")
except ConfigNotFoundError as e:
    logger.error(f"配置文件不存在: {e}")

# 权限错误
try:
    raise NeoPermissionError(user_id=123, operation="broadcast", message="权限不足")
except NeoPermissionError as e:
    logger.warning(f"权限错误: {e}")

# 命令错误
try:
    ...
except CommandError as e:
    await event.reply(f"命令处理失败: {e.message}")
```

> 注意：权限相关的异常是 `NeoPermissionError`（避免覆盖 Python 内置的
> `PermissionError`），不存在 `PermissionDeniedError`。

## 代码执行安全

### Docker 沙箱隔离

`/py`（`code_py` 插件）执行用户提交的 Python 代码时，代码在 **Docker 沙箱容器**
中运行（镜像由 `[docker] sandbox_image` 指定，默认 `python-sandbox:latest`），
与主进程完全隔离，具备以下限制：

| 限制项 | 说明 |
|---|---|
| 执行超时 | `[docker] timeout`（默认 10 秒），超时即终止 |
| 并发上限 | `[docker] concurrency_limit`（默认 5），防止资源耗尽 |
| 网络隔离 | 沙箱容器默认不暴露外部网络 |
| 文件系统隔离 | 沙箱内文件系统与宿主机隔离，不共享主进程数据 |

相关配置：

```toml
[docker]
base_url = ""                 # Docker 守护进程地址，留空使用环境默认
sandbox_image = "python-sandbox:latest"
timeout = 10                  # 单次执行超时（秒）
concurrency_limit = 5         # 同时执行的沙箱数量上限
tls_verify = false
```

插件侧约束（`plugins/code_py.py`）：

- 命令注册为 `permission=Permission.ADMIN`，仅管理员可执行
- 提交内容要求为多行代码块（`/py ``` ... ``` `），避免单行混淆注入
- 执行结果经 `CodeExecutionError` 统一包装，向用户展示脱敏后的错误信息

> 不要试图用"字符串黑名单"来保证安全（绕过方式太多），沙箱隔离才是正确边界。

## 网络通信安全

### HTTPS 与 URL 校验

所有外部请求都应使用 HTTPS，并在发起请求前做 URL 校验：

```python
from neobot.core.utils.input_validator import input_validator

# 基础校验（协议 + 主机名 + 路径）
if not input_validator.validate_url(url, allowed_schemes=["https"]):
    raise ValueError("不安全的 URL 协议")

# HTTP 请求前校验（SSRF 防护，默认拒绝内网/回环/链路本地/保留地址）
if not input_validator.validate_http_url(url):
    raise ValueError("拒绝访问内网或保留地址")
```

> `validate_http_url` 是 SSRF 防护的推荐入口：只允许 `http` / `https` 协议，
> 且通过 `ipaddress` 判断字面量 IP 与 `localhost` 等保留主机名，命中即拒绝。
> 框架内所有对外抓取/下载（web_parser、mirror_avatar、local_file_server、
> bili 解析等）均已接入该校验。

### 请求超时设置

避免请求无限期等待：

```python
import aiohttp

timeout = aiohttp.ClientTimeout(
    total=30,      # 总超时时间
    connect=10,    # 连接超时
    sock_read=15   # 读取超时
)

async with aiohttp.ClientSession(timeout=timeout) as session:
    async with session.get(url) as response:
        data = await response.json()
```

### 请求重试机制

```python
import asyncio
from typing import Optional

async def safe_request(
    url: str,
    max_retries: int = 3,
    base_delay: float = 1.0
) -> Optional[str]:
    """安全的网络请求，带重试机制（指数退避）"""
    for attempt in range(max_retries):
        try:
            timeout = aiohttp.ClientTimeout(total=10)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(url) as response:
                    response.raise_for_status()
                    return await response.text()

        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            if attempt == max_retries - 1:
                logger.error(f"请求失败，已达最大重试次数: {e}")
                return None

            delay = base_delay * (2 ** attempt)  # 指数退避
            logger.warning(f"请求失败，{delay}秒后重试: {e}")
            await asyncio.sleep(delay)

    return None
```

## 文件操作安全

### 路径验证

所有文件操作前都应验证路径安全性：

```python
from pathlib import Path
from neobot.core.utils.input_validator import input_validator

def safe_file_operation(file_path: str) -> bool:
    """安全的文件操作"""
    # 验证路径安全性
    if not input_validator.validate_path_input(file_path):
        logger.error(f"不安全的文件路径: {file_path}")
        return False

    # 解析路径
    path = Path(file_path).resolve()

    # 检查是否在允许的目录内
    allowed_base = Path("/var/data").resolve()
    if not str(path).startswith(str(allowed_base)):
        logger.error(f"文件路径不在允许的目录内: {file_path}")
        return False

    # 检查文件大小限制
    if path.exists() and path.stat().st_size > 10 * 1024 * 1024:  # 10MB
        logger.error(f"文件过大: {file_path}")
        return False

    return True
```

### 临时文件安全

```python
import tempfile
import os

def create_temp_file(content: bytes) -> str:
    """创建安全的临时文件"""
    # 创建临时文件
    with tempfile.NamedTemporaryFile(
        mode='wb',
        delete=False,
        suffix='.tmp',
        dir='/tmp'  # 指定临时目录
    ) as f:
        f.write(content)
        temp_path = f.name

    # 设置安全权限
    os.chmod(temp_path, 0o600)

    return temp_path

def cleanup_temp_file(file_path: str):
    """清理临时文件"""
    try:
        if os.path.exists(file_path):
            os.unlink(file_path)
    except Exception as e:
        logger.warning(f"清理临时文件失败: {e}")
```

## 日志安全

### 敏感信息掩码

框架自动掩码敏感信息：

```python
from neobot.core.utils.env_loader import env_loader

# 敏感值会自动掩码
password = env_loader.get_masked("MYSQL_PASSWORD")
# 输出: pa***rd（不会显示完整密码）

token = env_loader.get_masked("DISCORD_TOKEN")
# 输出: di***en（不会显示完整令牌）
```

此外，`ws.py` 的参数记录层对含敏感键名（password / token / secret 等）的参数
做截断脱敏，`bot_status` 的网络信息展示也会隐藏内网细节。

### 安全日志记录

```python
from neobot.core.utils.logger import logger

# 安全记录用户输入（截断长内容）
def safe_log_user_input(user_input: str, max_length: int = 100):
    """安全记录用户输入"""
    if len(user_input) > max_length:
        logged_input = user_input[:max_length] + "..."
    else:
        logged_input = user_input

    # 移除敏感信息
    logged_input = logged_input.replace("\n", "\\n")
    logged_input = logged_input.replace("\r", "\\r")

    logger.info(f"用户输入: {logged_input}")

# 记录操作时避免敏感信息
def log_operation(user_id: int, operation: str, details: str = ""):
    """记录用户操作"""
    logger.info(f"用户 {user_id} 执行操作: {operation}")
    if details:
        # 确保 details 不包含敏感信息
        safe_details = input_validator.sanitize_html(details)
        logger.debug(f"操作详情: {safe_details}")
```

## 网络层认证与防重放

### 反向 WebSocket 鉴权

`[reverse_ws]` 开启时，NapCat 以反向连接方式连入 Bot，需配置 `token`，
连接握手阶段校验 `Authorization: Bearer <token>`，不匹配返回 `401` 并断开。

### Redis pubsub 消息签名

多实例共享 Redis 时，广播/跨平台转发通过 pubsub 通道通信。若设置了
`[redis] signing_secret`（推荐，多机器人共享），或回退到 Redis 密码，
消息体会携带 HMAC-SHA256 签名，订阅方校验失败即丢弃，防止伪造消息注入。

```toml
[redis]
host = "localhost"
port = 6379
db = 0
password = "..."          # Redis 密码
signing_secret = "..."    # pubsub 签名密钥（可选，留空回退用 password）
```

## 总结

遵循这些安全最佳实践可以显著提高 NeoBot 应用的安全性：

1. **敏感配置用环境变量覆盖**，并保持 `config.toml` 权限为 600
2. **对所有用户输入进行验证**（SQL / XSS / 路径 / 命令注入）
3. **使用具体的异常类型**进行错误处理，区分内部错误与用户可见信息
4. **在 Docker 沙箱中执行不可信代码**，而不是依赖字符串过滤
5. **对外请求前做 SSRF 校验**（`validate_http_url`）并设置超时
6. **验证所有文件路径**，掩码日志中的敏感信息
7. **为反向 WS 与 Redis pubsub 配置鉴权/签名**

定期审查代码，确保遵循这些安全实践，可以保护你的应用免受常见的安全威胁。
