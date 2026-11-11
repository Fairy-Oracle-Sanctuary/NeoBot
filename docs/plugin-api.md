# 插件 API 契约 (plugin-api-v1)

> 本文档定义 Calglau BOT (NEO Bot Framework) 的插件公开 API。
> 它是插件与框架之间**唯一**的稳定契约:框架内部实现可以随时变化,
> 但 `neobot.plugin_api` 命名空间承诺向后兼容(契约 v1 内)。

## 1. 契约命名空间

插件只允许从以下命名空间导入:

| 命名空间 | 性质 |
|---|---|
| `neobot.plugin_api` | ✅ 公开契约(本契约) |
| `neobot.models` | ✅ 准公开:纯数据模型,框架不保证其内部结构稳定,但类名与字段在 v1 内保持不变 |
| `neobot.plugins.*` | ✅ 插件生态:插件之间可以互相导入 |
| `neobot.core.*` | ❌ **内部实现,禁止导入** |
| `neobot.adapters.*` | ❌ **内部实现,禁止导入** |

违反边界的行为会在加载时被检测(源码 AST 扫描):

- **新式契约插件**(manifest 声明了 `api_version`)**拒绝加载**,并给出具体违规模块;
- **旧式插件**(仅 `__plugin_meta__`)记录聚合警告并照常加载,迁移期兼容。

## 2. 声明插件清单

新式插件在模块级声明 `plugin_manifest`:

```python
from neobot.plugin_api import define_plugin

plugin_manifest = define_plugin(
    name="my_plugin",          # 必填:1-64 位字母/数字/下划线/连字符,字母开头
    description="一句话功能描述",
    usage="/cmd [参数] - 用法说明",
    version="0.1.0",           # semver
    author="镀铬酸钾",
    api_version="1",           # 声明契约版本 -> 成为"新式契约插件"
    dependencies=[],           # 依赖的其他插件名
)
```

- 旧式 `__plugin_meta__ = {...}` 字典仍然被支持,但**新插件必须使用 `define_plugin`**。
- manifest 校验失败(名字 / 版本 / 契约版本不合法)会在加载时直接报错,尽早暴露问题。

## 3. 注册命令与事件

模块级函数装饰器(从 `neobot.plugin_api` 顶层导入):

```python
from neobot.plugin_api import command, platform_command, on_message, on_notice, on_request

@command("hello", "hi", permission=Permission.USER)
async def handle_hello(bot: Bot, event: MessageEvent, args: list[str]):
    await event.reply("你好！")

@platform_command(["qq", "discord"], "广播")   # 仅指定平台生效
async def handle_broadcast(bot: Bot, event: MessageEvent, args: list[str]):
    ...
```

类风格插件(`Plugin` / `SimplePlugin` 基类)的方法标记装饰器从
`neobot.plugin_api.plugin` 导入,与模块级装饰器区分。

## 3.1 生命周期钩子

需要后台任务（轮询、Redis 订阅）的插件自己声明启动/关闭,核心不会在 `main.py` 里点名:

```python
from neobot.plugin_api import on_startup, on_shutdown

@on_startup
async def start():
    ...  # 此时 Redis 已经初始化

@on_shutdown
async def shutdown():
    ...  # 取消后台任务
```

- **启动**: `PluginManager` 在全部插件 import 完成、Redis 就绪后调用已加载插件的 `on_startup`。单个钩子抛错只记日志。
- **关闭**: 进程退出时调用 `on_shutdown`。热重载该模块之前也会先调用关闭钩子,重载成功后再调用启动钩子——关闭发生在 `importlib.reload` 之前,旧的任务句柄还在。
- **包插件**: 钩子写在包的 `__init__.py` 上。热重载包内某个子模块时,会先关闭再启动所属插件包的钩子。重载子模块失败时,包级任务仍会重新拉起。
- **同名替换**: 同一模块里同名函数再次注册会替换旧钩子,热重载不会把钩子叠成多份。

## 3.2 出站消息

机器人发出去的消息走 `message_bus`,适配器不 import 任何产品插件:

- QQ 群 `send_group_msg` / `send_msg(message_type="group")` 发布 `PlatformMessage(platform="qq")`。OneBot 原文在 `raw`,`metadata["no_mirror"]` 为真表示这条消息不应再镜像到其他平台(防环)。发布是后台任务,订阅者抛错或变慢不会影响这次发送。
- Discord 发送成功后发布 `PlatformMessage(platform="discord", content=...)`。
- 订阅: `message_bus.on_outgoing(key="你的插件.outgoing")`。`key` 相同会替换旧订阅,方便热重载。总线对每个订阅者单独捕获异常。

## 4. 公开接口一览

| 分类 | 符号 | 说明 |
|---|---|---|
| 注册 | `command` / `platform_command` / `on_message` / `platform_message` / `on_notice` / `on_request` | 命令与事件注册 |
| 生命周期 | `on_startup` / `on_shutdown` | 插件后台任务的启动与关闭 |
| 模型 | `MessageEvent` 及其子类 / `NoticeEvent` / `RequestEvent` / `Sender` / `MessageSegment` | 事件与消息数据 |
| 平台 | `PlatformMessage` / `PlatformSegment` | 跨平台消息载体 |
| 核心对象 | `Bot` | OneBot API 聚合入口(消息/群组/好友/账号/媒体) |
| 权限 | `Permission` | 权限枚举(`USER` / `ADMIN` / `OPERATOR` ...) |
| 基类 | `Plugin` / `SimplePlugin` | 类风格插件基类 |
| 服务 | `redis_manager` / `image_manager` / `bot_manager` / `permission_manager` / `message_bus` | 框架服务单例(只读使用) |
| 工具 | `download_to_local` / `get_local_file_server` / `run_in_thread_pool` / `input_validator` / `require_admin` | 常用能力 |
| 配置 | `global_config` | 全局配置对象 |
| 日志 | `logger` / `ModuleLogger` | 日志 |
| 清单 | `define_plugin` / `PluginManifest` / `resolve_manifest` | manifest 声明与解析 |

完整的符号清单以 `neobot.plugin_api.__all__` 为准(可执行检查)。

## 5. 版本策略

- `neobot.plugin_api.__version__`(如 `1.0.0`):契约实现版本,随框架发布,遵循 semver;
- `neobot.plugin_api.API_VERSION`(如 `"1"`):契约级别,插件 manifest 中声明;
- 契约 v1 内保证向后兼容:新增符号不加破坏,已有符号不改变语义;
- 不兼容变更(删除 / 改名 / 改变签名)必须提升契约大版本(`v2`),
  并提供迁移工具与过渡期(旧版本插件继续可用)。

## 6. 迁移指南(旧式 → 新式)

1. 把 `from neobot.core.managers.command_manager import matcher` 替换为
   `from neobot.plugin_api import command, on_message, ...`,并把
   `@matcher.command(...)` 改为 `@command(...)`(其余参数不变);
2. 把 `from neobot.core.utils.logger import logger, ModuleLogger` 替换为
   `from neobot.plugin_api import logger, ModuleLogger`;
3. 把 `from neobot.core.bot import Bot`、`from neobot.core.permission import Permission`
   等替换为 `from neobot.plugin_api import Bot, Permission`;
4. 把 `from neobot.core.plugin import SimplePlugin` 替换为
   `from neobot.plugin_api import SimplePlugin`;
5. 把 `__plugin_meta__ = {...}` 替换为 `plugin_manifest = define_plugin(...)`
   (字段名相同:`name` / `description` / `usage`,新增 `version` / `author` / `api_version`);
6. 删除 `from neobot.core.managers.redis_manager import redis_manager` 等内部导入,
   统一走 `neobot.plugin_api` 的对应符号(见第 4 节表格)。

迁移后可运行 `pytest src/neobot/tests/test_plugin_api.py` 验证契约,以及
启动日志中的"旧式插件聚合警告"确认边界状态。

## 7. 相关文档

- `docs/plugin-development/` — 插件开发指南(已按契约写法更新)
- `docs/adapter-architecture.md` — 适配器架构与平台感知注册
- `ROADMAP.md` — 插件系统解耦路线图(本契约是 1.1 的落地)
