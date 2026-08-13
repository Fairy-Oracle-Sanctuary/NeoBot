# API 使用示例

本文档提供了 NeoBot 框架核心 API 的使用示例，帮助开发者快速上手。

## 目录

1. [插件开发基础](#插件开发基础)
2. [消息处理](#消息处理)
3. [配置管理](#配置管理)
4. [日志记录](#日志记录)
5. [输入验证](#输入验证)
6. [环境变量管理](#环境变量管理)
7. [数据库操作](#数据库操作)
8. [网络请求](#网络请求)

## 插件开发基础

### 基本插件结构

```python
# -*- coding: utf-8 -*-
from typing import List

from neobot.core.managers.command_manager import matcher
from neobot.core.utils.logger import logger
from neobot.models import MessageEvent

# 插件元数据
__plugin_meta__ = {
    "name": "example_plugin",
    "description": "示例插件",
    "usage": "/示例命令 [参数] - 示例命令说明",
}

@matcher.command("示例命令")
async def handle_example_command(bot, event: MessageEvent, args: List[str]):
    """
    处理示例命令

    Args:
        bot: 机器人实例
        event: 消息事件
        args: 命令参数列表
    """
    try:
        if not args:
            await event.reply("请输入参数，例如：/示例命令 参数")
            return

        # 处理逻辑
        result = await process_args(args[0])

        # 回复结果
        await event.reply(f"处理结果: {result}")

    except Exception as e:
        logger.error(f"处理命令时出错: {e}")
        await event.reply("处理命令时发生错误，请稍后重试。")
```

> 事件模型统一从 `neobot.models` 导入（`MessageEvent` / `GroupMessageEvent` /
> `PrivateMessageEvent` / `MessageSegment` 等均在该包导出）。

### 平台感知注册（推荐）

新插件一律使用平台感知的注册方式，以支持 QQ / Discord / CLI 等平台：

```python
from neobot.core.managers.command_manager import matcher
from neobot.core.bot import Bot
from neobot.models import MessageEvent

# 同时注册到 QQ 与 Discord 平台
@matcher.platform_command(["qq", "discord"], "示例")
async def handle_example(bot: Bot, event: MessageEvent, args: list[str]):
    await event.reply("跨平台指令示例")
```

### 带权限检查的插件

`permission` 参数接收 `Permission` 枚举（`USER` / `OP` / `ADMIN`），而不是字符串：

```python
from neobot.core.managers.command_manager import matcher
from neobot.core.permission import Permission
from neobot.models import MessageEvent

@matcher.command("管理命令", permission=Permission.ADMIN)
async def handle_admin_command(bot, event: MessageEvent, args: List[str]):
    """
    处理管理命令（需要管理员权限）
    权限检查由框架自动完成，权限不足时框架会回复 permission_denied_message，
    无需在函数体内手动检查。
    """
    # 执行管理操作
    await event.reply("管理命令执行成功。")
```

如需手动检查权限（例如按用户判断某一操作的权限），`check_permission` 是**异步**方法：

```python
from neobot.core.managers.permission_manager import permission_manager
from neobot.core.permission import Permission

async def manual_permission_check(event):
    user_id = event.user_id
    if not await permission_manager.check_permission(user_id, Permission.ADMIN):
        await event.reply("您没有执行此命令的权限。")
        return
    await event.reply("权限校验通过。")
```

## 消息处理

### 发送消息

```python
from neobot.models import MessageSegment

async def send_messages(event: MessageEvent):
    """发送各种类型的消息"""

    # 发送纯文本
    await event.reply("这是一条文本消息")

    # 发送带格式的文本
    await event.reply("**粗体** *斜体* `代码`")

    # 发送图片
    image_segment = MessageSegment.image("https://example.com/image.jpg")
    await event.reply([image_segment, "这是一张图片"])

    # 发送文件
    file_segment = MessageSegment.file("/path/to/file.txt")
    await event.reply(file_segment)

    # 发送语音（注意是 record，不是 voice）
    voice_segment = MessageSegment.record("/path/to/voice.mp3")
    await event.reply(voice_segment)

    # 发送合并转发
    node = bot.build_forward_node(user_id=12345, nickname="示例用户", message="转发内容")
    await bot.send_forwarded_messages(event, [node])
```

> `MessageSegment` 支持 `text` / `at` / `image` / `face` / `record` / `video` /
> `file` / `json` / `xml` / `share` / `music` / `music_custom` / `reply` 等静态
> 构造方法；`__add__` 支持消息段与字符串/列表拼接。

### 处理消息事件

```python
@matcher.on_message()
async def handle_all_messages(bot, event: MessageEvent):
    """
    处理所有消息
    """
    # 获取消息内容
    message = event.message
    user_id = event.user_id
    group_id = getattr(event, "group_id", None)  # 私聊消息没有 group_id

    # 记录消息
    logger.info(f"收到消息: 用户={user_id}, 群组={group_id}, 内容={message}")

    # 简单的自动回复
    if "你好" in message:
        await event.reply("你好！我是机器人。")

    # 处理特定关键词
    if "帮助" in message:
        await event.reply("输入 /帮助 查看可用命令。")
```

## 配置管理

### 基本配置使用

框架启动时会加载 `config.toml`（缺失则从 `config.example.toml` 生成），
全局配置对象为 `global_config`，通过属性访问各配置段：

```python
from neobot.core.config_loader import global_config

# 命令前缀
prefixes = global_config.bot.command          # 例如 ["/"]

# NapCat WebSocket 地址
uri = global_config.napcat_ws.uri

# MySQL / Redis
mysql_host = global_config.mysql.host
redis_host = global_config.redis.host
redis_password = global_config.redis.password

# 其他可选配置段（属性始终存在，未配置时返回默认值）
threading_max_workers = global_config.threading.max_workers
bilibili_sessdata = global_config.bilibili.sessdata
douyin_api_key = global_config.douyin.api_key
```

> 所有配置段均通过 property 暴露：`napcat_ws` / `bot` / `redis` / `mysql` /
> `docker` / `image_manager` / `reverse_ws` / `threading` / `bilibili` / `douyin` /
> `local_file_server` / `discord` / `cross_platform` / `logging` / `mcc_adapter`。
> 不存在 `get()` / `get_list()` / `has()` / `to_dict()` 之类的字典式接口。

### 配置验证

框架使用 Pydantic 校验 `config.toml`，加载失败会抛出
`ConfigValidationError`（详情已由 `ConfigLoader` 逐条记录到日志）。

## 日志记录

### 基本日志使用

框架基于 Loguru，全局实例为 `logger`：

```python
from neobot.core.utils.logger import logger

# 不同级别的日志
logger.debug("调试信息")
logger.info("普通信息")
logger.warning("警告信息")
logger.error("错误信息")
logger.critical("严重错误")

# 带上下文的日志（直接以关键字传参，Loguru 会将其作为 extra 属性）
logger.info("用户操作", user_id=123456, action="login")

# 异常日志（需在 except 块内调用）
try:
    result = risky_operation()
except Exception as e:
    logger.exception(f"操作失败: {e}")
```

### 模块专用日志

插件建议使用模块级 Logger，便于按模块过滤与排查：

```python
from neobot.core.utils.logger import ModuleLogger

logger = ModuleLogger("MyPlugin")

logger.info("插件已加载")
logger.success("初始化完成")
logger.error("出错了")
```

## 输入验证

### 基本验证

```python
from neobot.core.utils.input_validator import input_validator

def validate_user_input(user_input: str) -> tuple[bool, str]:
    """
    验证用户输入

    Returns:
        (是否有效, 错误消息)
    """
    # 检查空输入
    if not user_input or not user_input.strip():
        return False, "输入不能为空"

    # 检查长度
    if len(user_input) > 1000:
        return False, "输入过长（最大1000字符）"

    # 安全检查
    if not input_validator.validate_sql_input(user_input):
        return False, "输入包含不安全字符"

    if not input_validator.validate_xss_input(user_input):
        return False, "输入包含不安全内容"

    return True, ""

# 在插件中使用
@matcher.command("安全命令")
async def handle_safe_command(bot, event: MessageEvent, args: List[str]):
    if not args:
        await event.reply("请输入参数")
        return

    user_input = args[0]
    is_valid, error_msg = validate_user_input(user_input)

    if not is_valid:
        await event.reply(f"输入无效: {error_msg}")
        return

    # 处理有效输入
    await event.reply(f"输入有效: {user_input}")
```

### 常用验证方法

| 方法 | 说明 |
|---|---|
| `validate_sql_input(input)` | 检测 SQL 注入模式 |
| `validate_xss_input(input)` | 检测 XSS / HTML 危险标签 |
| `validate_path_input(input)` | 检测路径遍历 |
| `validate_command_input(input)` | 检测命令注入 |
| `validate_url(url, allowed_schemes=...)` | 校验 URL 协议与主机名 |
| `validate_http_url(url)` | HTTP 请求前校验（**SSRF 防护**，默认拒绝内网/回环地址） |
| `validate_email(email)` / `validate_phone(phone)` | 邮箱 / 手机号格式 |
| `validate_integer(v, min, max)` / `validate_float(v, min, max)` | 数值范围 |
| `sanitize_html(html)` / `sanitize_sql(sql)` | 清理输入 |
| `validate_all(input, validation_types=...)` | 批量执行默认 `['sql','xss','path','command']` 校验 |

### 高级验证

```python
from datetime import datetime

class AdvancedValidator:
    """高级验证器"""

    @staticmethod
    def validate_email_domain(email: str, allowed_domains: list) -> bool:
        """验证邮箱域名"""
        if not input_validator.validate_email(email):
            return False

        domain = email.split('@')[1]
        return domain in allowed_domains

    @staticmethod
    def validate_date_range(date_str: str, start_date: str, end_date: str) -> bool:
        """验证日期范围"""
        try:
            date = datetime.strptime(date_str, "%Y-%m-%d")
            start = datetime.strptime(start_date, "%Y-%m-%d")
            end = datetime.strptime(end_date, "%Y-%m-%d")

            return start <= date <= end
        except ValueError:
            return False
```

## 环境变量管理

### 基本使用

```python
from neobot.core.utils.env_loader import env_loader

# 加载环境变量（.env 文件 + 系统环境变量；框架启动时已自动加载）
env_loader.load()

# 获取环境变量
database_url = env_loader.get("DATABASE_URL", "localhost")
api_key = env_loader.get("API_KEY")

# 获取带默认值的环境变量
port = env_loader.get_int("PORT", 8080)
debug = env_loader.get_bool("DEBUG", False)

# 获取列表类型（逗号分隔）
items = env_loader.get_list("ALLOWED_GROUPS", [], separator=",")

# 获取掩码的敏感值（用于日志），敏感键名会自动脱敏
masked_api_key = env_loader.get_masked("API_KEY")
logger.info(f"API Key: {masked_api_key}")  # 输出: AP***EY
```

### 环境变量验证

```python
from neobot.core.utils.env_loader import env_loader

# 校验必需变量是否存在（缺失会输出日志并返回 False）
if not env_loader.validate_required(["DB_HOST", "DB_PORT", "DB_USER", "DB_PASSWORD", "DB_NAME"]):
    logger.error("缺少必需的环境变量")
    return False

# 或使用抛异常的版本
env_loader.validate_required_keys(["API_KEY"])  # 缺失时抛出 ValueError
```

> 环境变量在框架中的主要用途是**覆盖 config.toml 中的敏感配置**
> （如 `MYSQL_PASSWORD` / `REDIS_PASSWORD` / `NAPCAT_WS_URI` / `DISCORD_TOKEN` /
> `DOUYIN_API_KEY` 等），详见 `docs/security-best-practices.md`。

## 数据库操作

框架提供单例 `MySQLManager`（基于 aiomysql 连接池），插件应优先使用它：

```python
from neobot.core.managers.mysql_manager import mysql_manager

# 注意：请先确认框架启动流程中已调用 initialize() 完成连接池初始化
async def query_example():
    rows = await mysql_manager.fetchall(
        "SELECT * FROM users WHERE status = %s", (1,)
    )
    row = await mysql_manager.fetchone(
        "SELECT * FROM users WHERE id = %s", (123,)
    )

    # 写操作
    await mysql_manager.execute(
        "UPDATE users SET name = %s WHERE id = %s", ("新名字", 123)
    )

    # 事务
    conn = await mysql_manager.begin_transaction()
    try:
        await mysql_manager.execute("INSERT INTO logs (msg) VALUES (%s)", ("hello",))
        await mysql_manager.commit_transaction(conn)
    except Exception:
        await mysql_manager.rollback_transaction(conn)
        raise
```

> 手动管理 aiomysql 连接池的写法可参考
> `docs/performance-optimization.md` 的「数据库优化」章节。

## 网络请求

### 异步HTTP请求

```python
import aiohttp
from typing import Dict, Any, Optional

class HttpClient:
    """HTTP客户端（每次请求使用独立 session）"""

    def __init__(self, base_url: str = "", timeout: int = 30):
        self.base_url = base_url.rstrip("/")
        self.timeout = aiohttp.ClientTimeout(total=timeout)

    async def get(self, endpoint: str, **kwargs) -> Optional[Dict[str, Any]]:
        """发送GET请求"""
        url = f"{self.base_url}/{endpoint.lstrip('/')}"

        async with aiohttp.ClientSession(timeout=self.timeout) as session:
            async with session.get(url, **kwargs) as response:
                response.raise_for_status()
                return await response.json()

    async def post(self, endpoint: str, data: Dict[str, Any], **kwargs) -> Optional[Dict[str, Any]]:
        """发送POST请求"""
        url = f"{self.base_url}/{endpoint.lstrip('/')}"

        async with aiohttp.ClientSession(timeout=self.timeout) as session:
            async with session.post(url, json=data, **kwargs) as response:
                response.raise_for_status()
                return await response.json()
```

### 发起外部请求前做 SSRF 校验

```python
from neobot.core.utils.input_validator import input_validator

async def fetch_safe(url: str):
    # 拒绝非 http/https 协议、内网/回环/链路本地地址（SSRF 防护）
    if not input_validator.validate_http_url(url):
        raise ValueError(f"不安全的 URL: {url}")

    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            response.raise_for_status()
            return await response.text()
```

## 总结

这些示例展示了 NeoBot 框架核心功能的使用方法。通过组合这些基础组件，可以构建出功能强大、安全可靠的机器人插件。

关键要点：

1. **遵循异步编程模式**：所有可能阻塞的操作都应使用异步版本
2. **验证所有用户输入**：防止安全漏洞
3. **使用配置管理**：敏感信息存放在环境变量或 `config.toml`（权限 600）
4. **记录详细的日志**：使用模块级 Logger 便于排查
5. **处理所有异常**：提供友好的错误消息

更多高级功能和最佳实践，请参考框架的其他文档：

- 插件开发：`src/neobot/docs/plugin-development/`
- 核心概念：`src/neobot/docs/core-concepts/`
- 安全实践：`docs/security-best-practices.md`

---

## 面板 API：HMAC 签名鉴权

面板（bot.wanfeng.cyou 前端）调 `/api/rental/*` 时使用 HMAC 签名代替明文 token
（密钥内置于前端 WASM，不随请求传输）。`panel_token`（Bearer）作为兼容保留。

### 签名请求头

| 头 | 说明 |
|---|---|
| `X-Timestamp` | unix 秒（误差窗口 ±300s） |
| `X-Nonce` | 随机串（一次性，服务端防重放，长度 ≤128） |
| `X-Signature` | `hex( HMAC-SHA256(panel_secret, message) )` |

### message 格式

```text
METHOD
PATH
TIMESTAMP
NONCE
SHA256_HEX(RAW_BODY)
```

按 `\n` 拼接（PATH 不含查询串；GET 无 body 时 body 为空字节串，
即 `sha256("")` 的十六进制）。

### 示例（Python）

```python
import hmac, hashlib, time, secrets

def sign(method, path, ts, nonce, body: bytes):
    body_hash = hashlib.sha256(body).hexdigest()
    msg = "\n".join([method, path, ts, nonce, body_hash])
    return hmac.new(SECRET.encode(), msg.encode(), hashlib.sha256).hexdigest()

ts = str(int(time.time()))
nonce = secrets.token_hex(16)
sig = sign("POST", "/api/rental/apply", ts, nonce, body_bytes)
# 请求头：X-Timestamp / X-Nonce / X-Signature
```

### 服务端行为

- 签名错误 / 时间戳过期 / nonce 重放 / 缺头 → `401`
- 面板接口限流不变（租赁 30 次/分/IP，申请 5 次/分/IP → `429`）
- `/health` 公开；admin（Bearer）与面板（HMAC 或兼容 Bearer）互不影响
