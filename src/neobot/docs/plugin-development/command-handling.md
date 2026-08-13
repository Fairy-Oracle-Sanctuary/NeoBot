# 指令处理与参数解析

光会 `event.reply()` 只能写小插件。。。认识一下其他的方法吧

## 1. 获取命令参数

在处理器函数里声明 `args: list[str]`，框架会把命令名之后、按空白切分的内容注入进来。

```python
from neobot.core.managers.command_manager import matcher
from neobot.models import MessageEvent

@matcher.command("echo")
async def handle_echo(bot, event: MessageEvent, args: list[str]):
    # 如果用户发送 /echo hello world
    # args 的值就是 ["hello", "world"]
    if not args:
        await event.reply("你啥也没说啊")
    else:
        await event.reply(f"你说了：{' '.join(args)}")
```

`args` 是**字符串列表**（不是一整坨字符串）。如果需要原始全文，自己 `" ".join(args)`。

## 2. 手动类型转换

框架只负责把参数按空白切分注入 `args`，**不会根据类型提示自动转换**。需要数值时请手动转换：

```python
@matcher.command("add")
async def handle_add(bot, event: MessageEvent, args: list[str]):
    # /add 10 20
    if len(args) < 2:
        await event.reply("用法: /add <数字> <数字>")
        return

    try:
        a = int(args[0])
        b = int(args[1])
    except ValueError:
        await event.reply("参数必须是整数")
        return

    await event.reply(f"计算结果是：{a + b}")
```

> 如果你想要"自动类型转换 + 自动参数绑定"的写法，可以使用
> [极简插件 `SimplePlugin`](./simple-plugin.md)——它对简单方法内置了参数解析与
> `str` / `int` / `float` 转换。

## 3. 智能的参数注入

除了 `args` 列表，命令处理器还可以自动接收一些非常有用的上下文对象。框架底层使用 Python 的 `inspect` 模块分析你函数的参数签名，**按参数名**自动"注入"你需要的对象。

这是一种轻量级的**依赖注入**，让你的代码更简洁、更易于测试。

### 可用的参数

| 参数名 | 类型 | 描述 |
| --- | --- | --- |
| `bot` | `Bot` | 当前的 Bot 实例，用于调用 API 发送消息等。 |
| `event` | `MessageEvent` | 触发该命令的完整消息事件对象。 |
| `ctx` | `CommandContext` | 平台感知上下文，属性与 `MessageEvent` 兼容（平台分发时使用）。 |
| `args` | `list[str]` | 命令参数的字符串列表。 |
| `permission_granted` | `bool` | 当前用户是否通过了权限检查。 |

### 示例

假设我们想写一个"回声"命令，但只在用户拥有管理员权限时才重复他们的消息：

```python
# src/neobot/plugins/echo_plus.py
from neobot.core.managers.command_manager import matcher
from neobot.core.permission import Permission
from neobot.core.bot import Bot
from neobot.models import MessageEvent

@matcher.command("echo_plus", permission=Permission.ADMIN)
async def echo_plus(bot: Bot, event: MessageEvent, args: list[str], permission_granted: bool):
    """
    一个更强大的回声命令
    """
    # 默认情况下，权限不足的用户根本不会进入本函数（框架会回复权限不足消息）
    # 只有当 override_permission_check=True 时，才需要手动判断 permission_granted

    if not args:
        await bot.send(event, "你想要我复述什么呢？")
        return

    # 从 event 对象中获取更详细的信息
    user_id = event.user_id
    message_to_echo = " ".join(args)

    response = f"管理员 {user_id} 说：{message_to_echo}"
    await bot.send(event, response)
```

### 平台感知（推荐）

新插件建议直接使用 `platform_command`，一次注册即可同时覆盖 QQ 与 Discord 平台：

```python
from neobot.core.managers.command_manager import matcher
from neobot.core.permission import Permission

@matcher.platform_command(["qq", "discord"], "echo_plus", permission=Permission.ADMIN)
async def echo_plus(bot, event, args: list[str]):
    # event 在 QQ 平台是 MessageEvent，在 Discord 平台是 CommandContext，
    # 两者都支持 event.reply(...) / event.user_id 等属性
    await event.reply(" ".join(args))
```

## 4. 通用消息处理

除了指令，还可以用 `@matcher.on_message()` 监听所有消息（非指令触发的消息）：

```python
@matcher.on_message(priority=10, block=False)
async def handle_all_messages(bot, event: MessageEvent):
    # 不响应用户，只是记录
    logger.debug(f"收到消息: {event.raw_message}")
```

- `priority`: 处理器优先级，数值越小越先执行，默认 10。
- `block`: 是否阻断后续处理器，默认 False。

平台版本为 `@matcher.platform_message(["qq", "discord"], priority=1, block=False)`。
