# 极简插件开发指南

如果你是 Python 新手，或者只是想快速写一些简单的指令，那么 `SimplePlugin` 是你的最佳选择。它让你无需理解复杂的装饰器和事件处理机制，只需要写普通的 Python 方法即可。

## 1. 快速开始

在 `src/neobot/plugins/` 目录下创建一个新文件，例如 `my_simple_plugin.py`：

```python
from neobot.plugin_api import SimplePlugin
from neobot.plugin_api import MessageEvent

class MyPlugin(SimplePlugin):
    
    async def hello(self, event: MessageEvent):
        """
        发送 /hello 即可调用
        """
        return "你好！这是极简插件。"

    async def echo(self, event: MessageEvent, msg: str):
        """
        发送 /echo <内容> 即可调用
        """
        return f"你说了: {msg}"

# 必须实例化插件以生效
plugin = MyPlugin()
```

就是这么简单！现在你可以发送 `/hello` 和 `/echo 测试` 来测试你的插件了。

## 2. 核心特性

### 方法即指令

在 `SimplePlugin` 的子类中，任何**不以下划线开头**的方法都会自动注册为指令。
指令名称就是方法名。

例如：
- `async def ping(self, ...)` -> 注册为 `/ping`
- `async def help_me(self, ...)` -> 注册为 `/help_me`

### 自动参数解析

框架会根据你定义的参数类型，自动解析用户输入的参数。

#### 字符串参数
```python
async def greet(self, event: MessageEvent, name: str):
    return f"你好, {name}"
```
- 发送 `/greet Neo` -> `name` 参数为 `"Neo"`

#### 数字参数 (自动转换类型)
```python
async def add(self, event: MessageEvent, a: int, b: int):
    return f"{a} + {b} = {a + b}"
```
- 发送 `/add 10 20` -> `a` 为 `10` (int), `b` 为 `20` (int)
- 如果用户输入非数字（如 `/add a b`），框架会自动提示参数类型错误。

#### 捕获剩余文本
如果你的方法只有一个参数（除了 `event`），那么该参数会捕获指令后的所有文本。
```python
async def broadcast(self, event: MessageEvent, content: str):
    return f"广播内容: {content}"
```
- 发送 `/broadcast 这是一个 很长 的消息` -> `content` 为 `"这是一个 很长 的消息"`

### 自动回复

如果你的方法返回了字符串（`str`），框架会自动将其作为回复发送给用户。
如果返回 `None`（即没有 return 语句），则不发送回复。

```python
async def silent(self, event: MessageEvent):
    # 执行一些操作，但不回复
    print("Silent command executed")
    # 也可以手动调用 reply
    await event.reply("手动回复")
```

## 3. 进阶用法

### 访问事件对象

所有方法的第一个参数（除了 `self`）必须是 `event`。通过 `event` 对象，你可以获取更多信息：

```python
async def whoami(self, event: MessageEvent):
    user_id = event.user_id
    nickname = event.sender.nickname
    return f"你是 {nickname} ({user_id})"
```

### 混合使用装饰器

虽然 `SimplePlugin` 旨在简化开发，但你仍然可以使用装饰器来处理更复杂的场景，例如权限控制或监听非指令消息。

```python
from neobot.plugin_api import SimplePlugin, command, on_message
from neobot.plugin_api import Permission

class AdvancedPlugin(SimplePlugin):
    
    # 普通指令
    async def normal(self, event: MessageEvent):
        return "普通指令"
        
    # 使用装饰器添加权限控制
    @command("admin_only", permission=Permission.ADMIN)
    async def admin_op(self, event: MessageEvent, args: list[str]):
        return "只有管理员能看到这个"
        
    # 监听所有消息
    @on_message()
    async def handle_all(self, event: MessageEvent):
        if "敏感词" in event.raw_message:
            await event.reply("检测到敏感词！")
```

## 4. 注意事项

1.  **方法名**：不要使用以 `_` 开头的方法名作为指令，这些方法会被忽略。
2.  **参数类型**：目前支持 `str`, `int`, `float` 的自动转换。
3.  **实例化**：不要忘记在文件末尾实例化你的类（`plugin = MyPlugin()`），否则插件不会生效。
