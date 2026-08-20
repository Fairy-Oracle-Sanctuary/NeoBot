# 消息 API

发消息是机器人最基础的功能。这一页讲的是怎么发消息、撤回消息、转发消息，以及怎么用消息段（图片、@人、表情等等）。

## 快速开始

### 发一条简单的消息

```python
from neobot.core.managers.command_manager import matcher
from neobot.models import MessageEvent

@matcher.command("hello")
async def handle_hello(event: MessageEvent):
    # 方法 1: 直接回复（最常用）
    await event.reply("你好呀！")
    
    # 方法 2: 通过 bot 实例发消息
    await event.bot.send_group_msg(event.group_id, "这是一条群消息")
    # 如果是私聊，可以用 send_private_msg
    # await event.bot.send_private_msg(event.user_id, "这是一条私聊消息")
```

`event.reply()` 是最简单的方式，它会自动判断是群聊还是私聊，然后调用正确的 API。

## 消息段 (MessageSegment)

除了纯文字，QQ 消息还能包含图片、@某人、表情、分享链接等等。在 OneBot 里，这些叫“消息段”。

NEO Bot 用 `MessageSegment` 类来表示消息段。

### 创建消息段

```python
from neobot.models import MessageSegment

# 文本
text_seg = MessageSegment.text("这是一段文字")

# @某人
at_seg = MessageSegment.at(123456)  # @QQ号 123456
at_all = MessageSegment.at("all")    # @全体成员

# 图片
image_seg = MessageSegment.image("https://example.com/image.jpg")
# 本地图片
local_image = MessageSegment.image("file:///path/to/image.png")

# 表情 (QQ 表情，不是 emoji)
face_seg = MessageSegment(type="face", data={"id": "123"})

# 分享链接
share_seg = MessageSegment(type="share", data={
    "url": "https://example.com",
    "title": "示例网站",
    "content": "这是一个示例网站",
    "image": "https://example.com/thumb.jpg"
})
```

### 组合消息段

你可以把多个消息段组合成一条消息：

```python
# 方法 1: 用列表
message = [
    MessageSegment.text("你好，"),
    MessageSegment.at(123456),
    MessageSegment.text("！"),
    MessageSegment.image("https://example.com/welcome.jpg")
]

# 方法 2: 用加法运算符（更直观）
message = (
    MessageSegment.text("你好，") +
    MessageSegment.at(123456) +
    MessageSegment.text("！")
)

# 发送组合消息
await event.reply(message)
```

### 从 CQ 码转换

如果你熟悉 CQ 码，也可以用 `MessageSegment` 来解析：

```python
# CQ 码字符串转消息段列表（需要手动解析，这里只是示例）
# 实际使用中，框架会自动处理 CQ 码
```

## API 方法详解

### `send_group_msg` - 发送群消息

```python
async def send_group_msg(
    self,
    group_id: int,
    message: Union[str, MessageSegment, List[MessageSegment]],
    auto_escape: bool = False
) -> Dict[str, Any]
```

**参数：**
- `group_id`: 群号
- `message`: 消息内容，可以是字符串、单个消息段，或消息段列表
- `auto_escape`: 是否对消息中的 CQ 码特殊字符进行转义（仅当 `message` 是字符串时有效）

**示例：**
```python
# 发文字
await bot.send_group_msg(123456, "大家好！")

# 发图片
await bot.send_group_msg(123456, MessageSegment.image("https://example.com/cat.jpg"))

# 发组合消息
msg = MessageSegment.text("看这只猫：") + MessageSegment.image("https://example.com/cat.jpg")
await bot.send_group_msg(123456, msg)
```

### `send_private_msg` - 发送私聊消息

```python
async def send_private_msg(
    self,
    user_id: int,
    message: Union[str, MessageSegment, List[MessageSegment]],
    auto_escape: bool = False
) -> Dict[str, Any]
```

**参数：**
- `user_id`: 对方的 QQ 号
- `message`: 消息内容
- `auto_escape`: 是否转义 CQ 码

**示例：**
```python
await bot.send_private_msg(123456, "你好，这是一条私聊消息")
```

### `send` - 智能发送

```python
async def send(
    self,
    event: OneBotEvent,
    message: Union[str, MessageSegment, List[MessageSegment]],
    auto_escape: bool = False
) -> Dict[str, Any]
```

这个方法会根据事件的类型自动选择发群消息还是私聊消息。如果事件是消息事件，它其实会调用 `event.reply()`。

**示例：**
```python
# 在事件处理函数中
await bot.send(event, "自动判断是群聊还是私聊")
```

### `delete_msg` - 撤回消息

```python
async def delete_msg(self, message_id: int) -> Dict[str, Any]
```

**参数：**
- `message_id`: 要撤回的消息 ID（从消息事件中获取）

**示例：**
```python
@matcher.command("recall")
async def handle_recall(event: MessageEvent):
    # 撤回上一条消息（假设我们知道 message_id）
    message_id = event.message_id
    await event.bot.delete_msg(message_id)
```

### `get_msg` - 获取消息详情

```python
async def get_msg(self, message_id: int) -> Dict[str, Any]
```

获取一条消息的详细信息，包括发送者、发送时间、内容等。

### `get_forward_msg` - 获取合并转发消息

```python
async def get_forward_msg(self, id: str) -> List[Dict[str, Any]]
```

获取一条合并转发消息（聊天记录）的详细内容。

**参数：**
- `id`: 合并转发消息的 ID（从消息中获取）

**返回值：**
- 消息节点列表，每个节点包含发送者、时间、内容等信息

## 合并转发

合并转发就是那种“点击展开查看聊天记录”的消息。在 QQ 里很常见。

### 构建转发节点

先用 `bot.build_forward_node()` 创建节点：

```python
# 创建一个转发节点
node = bot.build_forward_node(
    user_id=123456,              # 发送者的 QQ 号
    nickname="张三",              # 显示的名字
    message="这是一条测试消息"    # 消息内容
)

# 消息内容也可以用消息段
node2 = bot.build_forward_node(
    user_id=789012,
    nickname="李四",
    message=MessageSegment.text("看这个图片：") + MessageSegment.image("https://example.com/img.jpg")
)
```

### 发送合并转发

```python
# 方法 1: 直接发到群聊
nodes = [node1, node2, node3]
await bot.send_group_forward_msg(group_id=123456, messages=nodes)

# 方法 2: 发到私聊
await bot.send_private_forward_msg(user_id=123456, messages=nodes)

# 方法 3: 智能发送（根据事件判断）
await bot.send_forwarded_messages(target=event, nodes=nodes)
```

### 完整示例

```python
@matcher.command("forward")
async def handle_forward(event: MessageEvent):
    # 创建几个测试节点
    nodes = [
        event.bot.build_forward_node(
            user_id=10001,
            nickname="系统",
            message="欢迎使用 NEO Bot"
        ),
        event.bot.build_forward_node(
            user_id=event.user_id,
            nickname=event.sender.nickname,
            message="这个合并转发功能真好用！"
        ),
        event.bot.build_forward_node(
            user_id=10002,
            nickname="机器人",
            message=MessageSegment.text("谢谢夸奖！") + MessageSegment.face(123)
        )
    ]
    
    # 发送
    await event.bot.send_forwarded_messages(event, nodes)
```

## 消息事件中的快捷方法

在消息事件 (`MessageEvent`) 中，有一些快捷方法：

### `event.reply()`

```python
await event.reply("你好！")
await event.reply(message_segment_list)
```

自动回复到消息来源（群聊或私聊）。

### `event.message`

获取事件中的消息内容（已经是 `MessageSegment` 列表格式）。

```python
# 检查消息是否包含图片
for segment in event.message:
    if segment.type == "image":
        await event.reply("你发了一张图片！")
        break
```

## 注意事项

1. **消息长度限制**: QQ 对单条消息有长度限制，太长的消息会被截断。
2. **频率限制**: 不要疯狂发消息，可能会被腾讯限制。
3. **图片缓存**: 默认情况下，图片会缓存到本地，下次发送同样的图片会更快。
4. **网络错误**: 发消息可能因为网络问题失败，建议做好错误处理。

## 下一步

现在你已经知道怎么发消息了。接下来可以看看：

- [群组 API](./group.md): 管理群聊，比如禁言、踢人
- [好友 API](./friend.md): 处理好友相关操作
- [账号 API](./account.md): 管理机器人自己的状态