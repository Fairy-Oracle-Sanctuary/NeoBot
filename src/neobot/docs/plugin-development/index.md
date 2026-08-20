# 插件开发入门

写插件是给 NEO Bot 添加功能的唯一方式，一个 Python 文件就是一个插件。（或者一个文件夹里边有 __init__.py）

## 1. 创建你的第一个插件

在 `src/neobot/plugins/` 目录下，新建一个 `hello.py` 文件。

```python
# src/neobot/plugins/hello.py

from neobot.plugin_api import MessageEvent, command, define_plugin

# plugin_manifest 声明插件清单(新式契约插件,plugin-api-v1),
# 会在 /help 指令里显示;同时声明 api_version 即成为"契约插件",
# 加载时会校验只使用 neobot.plugin_api 命名空间。
plugin_manifest = define_plugin(
    name="hello",
    description="一个简单的示例插件",
    usage="/hello - 发送你好",
    version="0.1.0",
    author="镀铬酸钾",
)

# @command() 装饰器注册一个命令
# 命令名以及所有别名都作为位置参数传入
@command("hello", "hi", "你好")
async def handle_hello(event: MessageEvent):
    """
    处理 /hello 命令
    """
    # event.reply() 是一个快捷方法，可以直接回复消息
    await event.reply(f"你好，{event.sender.nickname}！")
```

> 新插件建议使用平台感知注册（`platform_command`），以便同时支持 QQ / Discord：
>
> ```python
> from neobot.plugin_api import Bot, MessageEvent, define_plugin, platform_command
>
> plugin_manifest = define_plugin(name="hello", description="示例", usage="/hello - 发送你好")
>
> @platform_command(["qq", "discord"], "hello", "hi", "你好")
> async def handle_hello(bot: Bot, event: MessageEvent, args: list[str]):
>     await event.reply(f"你好，{event.sender.nickname}！")
> ```

## 2. 加载插件

不用你动手，NEO Bot 启动时会自动加载 `src/neobot/plugins/` 目录下的所有 `.py` 文件（含子目录包）。
修改插件文件后，通过热重载指令即可生效，无需重启 Bot。

## 3. 测试插件

现在，去群里或者私聊给 Bot 发送：

*   `/hello`
*   `/hi`
*   `/你好`

Bot 应该会回复你：“你好，[你的昵称]！”

## 插件剖析

### `plugin_manifest`(或旧式 `__plugin_meta__`)

清单不是必须的，但强烈建议写上。它定义了插件的元信息，主要给 `/help` 命令用。

*   `name`: 插件叫啥。
*   `description`: 这插件是干嘛的。
*   `usage`: 怎么用，写上具体的指令和说明。
*   `version` / `author` / `api_version`: 新式清单附加字段（`define_plugin` 自动填充默认值）。

### `@command()`

这是最核心的装饰器，用来注册一个命令处理器。

```python
@command(*names, permission=None, override_permission_check=False)
```

*   **`*names`**: 命令名以及别名，如 `@command("hello", "hi")`。
*   `permission`: `Permission` 枚举（`USER` / `OP` / `ADMIN`），默认为 `None`（所有用户可用）。
*   `override_permission_check`: `bool`，设为 `True` 时不拦截无权限用户，而是把检查结果
    通过 `permission_granted` 参数传给处理器，由函数自行处理。

### 处理器函数

被 `@command()` 装饰的函数就是处理器。它必须是一个 `async` 异步函数。

*   **参数**: 框架会按**参数名**自动注入你需要的对象，你只需要声明需要什么：
    *   `event: MessageEvent`: 最常用，包含发送者、群号、消息内容等。
    *   `bot: Bot`: 当前 Bot 实例，用于调用 API。
    *   `args: list[str]`: 命令参数列表（去掉命令名之后，按空白切分）。
    *   `permission_granted: bool`: 权限检查结果（配合 `override_permission_check=True` 使用）。

就这么简单，一个最基础的插件就写完了。

## 极简插件开发（推荐新手）

如果你觉得上面的装饰器写法太复杂，或者只是想快速写几个简单的指令，我们提供了一种**极简模式**。
你只需要定义一个类，写几个方法，它们就会自动变成指令！

- [查看极简插件开发指南](./simple-plugin.md)

## 进阶阅读

- [指令处理](./command-handling.md): 了解如何处理参数、获取用户输入。
- [最佳实践](./best-practices.md): 学习如何编写更健壮、更高效的插件。
- [插件详解：/status 状态监控](./status-plugin.md): 深入了解内置的状态监控插件是如何实现的。
