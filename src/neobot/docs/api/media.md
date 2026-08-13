# 媒体 API

这一页讲的是怎么处理图片、语音等媒体文件。虽然方法不多，但都很实用。

## 能力检查

### `can_send_image` - 检查是否可以发送图片

```python
async def can_send_image(self) -> Dict[str, Any]
```

检查当前上下文是否允许发送图片。

**返回值：**
- 包含检查结果的字典，通常有 `yes` 或 `no` 字段

**示例：**
```python
from neobot.core.managers.command_manager import matcher
from neobot.models import MessageEvent, MessageSegment

@matcher.command("sendpic")
async def handle_sendpic(event: MessageEvent, args: list[str]):
    # 先检查能不能发图片
    result = await event.bot.can_send_image()
    
    if result.get("yes"):
        # 可以发图片
        await event.reply(MessageSegment.image("https://example.com/image.jpg"))
    else:
        # 不能发图片
        await event.reply("当前环境不支持发送图片")
```

### `can_send_record` - 检查是否可以发送语音

```python
async def can_send_record(self) -> Dict[str, Any]
```

检查当前上下文是否允许发送语音消息。

**示例：**
```python
result = await bot.can_send_record()
if result.get("yes"):
    print("可以发语音")
else:
    print("不能发语音")
```

## 图片信息

### `get_image` - 获取图片信息

```python
async def get_image(self, file: str) -> Dict[str, Any]
```

获取图片的详细信息，比如大小、尺寸、MD5 等。

**参数：**
- `file`: 图片文件名、路径或 URL

**返回值：**
- 包含图片信息的字典

**示例：**
```python
from neobot.core.managers.command_manager import matcher
from neobot.models import MessageEvent, MessageSegment

@matcher.command("imageinfo")
async def handle_imageinfo(event: MessageEvent):
    # 检查消息中是否有图片
    for segment in event.message:
        if segment.type == "image":
            file = segment.data.get("file", "")
            if file:
                # 获取图片信息
                info = await event.bot.get_image(file)
                await event.reply(
                    f"图片信息：\n"
                    f"大小: {info.get('size', '未知')} 字节\n"
                    f"尺寸: {info.get('width', '?')}x{info.get('height', '?')}\n"
                    f"MD5: {info.get('md5', '未知')}"
                )
                return
    
    await event.reply("消息中没有图片")
```

### `get_file` - 获取文件信息

```python
async def get_file(self, file_id: str) -> Dict[str, Any]
```

获取文件的详细信息，比如文件名、大小、URL 等。

**参数：**
- `file_id`: 文件 ID，通常从群文件上传事件中获取

**返回值：**
- 包含文件信息的字典

## 实际应用示例

### 图片转发器

```python
from neobot.core.managers.command_manager import matcher
from neobot.models import MessageEvent, MessageSegment

@matcher.command("forwardimage")
async def handle_forwardimage(event: MessageEvent, args: list[str]):
    """
    将收到的图片转发到指定群
    用法: /forwardimage 群号
    """
    if not args or not args[0].isdigit():
        await event.reply("参数错误，需要群号")
        return
    
    target_group = int(args[0])
    
    # 查找消息中的图片
    images = []
    for segment in event.message:
        if segment.type == "image":
            images.append(segment)
    
    if not images:
        await event.reply("消息中没有图片")
        return
    
    # 检查是否能发图片到目标群
    can_send = await event.bot.can_send_image()
    if not can_send.get("yes"):
        await event.reply("当前环境不支持发送图片")
        return
    
    # 转发所有图片
    for image in images:
        await event.bot.send_group_msg(target_group, image)
        await asyncio.sleep(0.5)  # 避免发送太快
    
    await event.reply(f"已转发 {len(images)} 张图片到群 {target_group}")
```

### 图片信息查询插件

```python
from neobot.core.managers.command_manager import matcher
from neobot.models import MessageEvent

@matcher.on_message()
async def handle_image_autoinfo(event: MessageEvent):
    """
    自动回复图片信息（当有人发图片时）
    """
    # 只处理包含图片的消息
    images = [seg for seg in event.message if seg.type == "image"]
    if not images:
        return
    
    # 只处理第一张图片（避免消息太长）
    image_seg = images[0]
    file = image_seg.data.get("file", "")
    
    if not file:
        return
    
    try:
        # 获取图片信息
        info = await event.bot.get_image(file)
        
        # 构建回复消息
        msg = "📷 图片信息：\n"
        if "size" in info:
            size_kb = info["size"] / 1024
            msg += f"大小: {size_kb:.1f} KB\n"
        if "width" in info and "height" in info:
            msg += f"尺寸: {info['width']}×{info['height']}\n"
        if "md5" in info:
            msg += f"MD5: {info['md5'][:8]}...\n"
        
        await event.reply(msg)
    except Exception as e:
        # 获取图片信息失败，静默处理
        pass
```

### 图片发送安全检查

```python
from neobot.core.managers.command_manager import matcher
from neobot.models import MessageEvent, MessageSegment

async def safe_send_image(bot, target_id, image_url, is_group=True):
    """
    安全发送图片：先检查是否能发，再发送
    """
    # 检查发送能力
    can_send = await bot.can_send_image()
    if not can_send.get("yes"):
        return False, "当前环境不支持发送图片"
    
    # 检查图片是否存在（简单检查）
    if not image_url:
        return False, "图片URL为空"
    
    try:
        # 发送图片
        if is_group:
            await bot.send_group_msg(target_id, MessageSegment.image(image_url))
        else:
            await bot.send_private_msg(target_id, MessageSegment.image(image_url))
        return True, "图片发送成功"
    except Exception as e:
        return False, f"发送失败: {e}"

@matcher.command("safepic")
async def handle_safepic(event: MessageEvent, args: list[str]):
    """
    安全发送图片示例
    """
    if not args:
        await event.reply("需要图片URL")
        return
    image_url = " ".join(args)
    # 是判断群聊还是私聊
    is_group = hasattr(event, "group_id") and event.group_id
    
    if is_group:
        target_id = event.group_id
    else:
        target_id = event.user_id
    
    # 安全发送
    success, message = await safe_send_image(
        event.bot, target_id, image_url, is_group
    )
    
    if not success:
        await event.reply(message)
```

## 注意事项

1. **客户端支持**: 不是所有 OneBot 客户端都完全支持媒体 API。
2. **网络限制**: 发送图片和语音可能受网络环境限制。
3. **文件大小**: 图片和语音文件有大小限制，太大的文件可能发送失败。
4. **缓存**: 图片默认会缓存，重复发送同一图片会更快。
5. **安全性**: 不要发送可疑或非法内容。

## 常见问题

### Q: 为什么 `can_send_image` 总是返回可以？
A: 这取决于 OneBot 客户端的实现。有些客户端可能不检查实际能力，总是返回可以。

### Q: 怎么发送本地图片？
A: 使用 `file://` 协议或直接使用本地路径：
```python
# 本地文件路径
image = MessageSegment.image("file:///path/to/image.jpg")
# 或者（取决于客户端）
image = MessageSegment.image("/path/to/image.jpg")
```

### Q: 怎么发送语音消息？
A: NEO Bot 目前没有封装发送语音的 API，但你可以通过 `call_api` 直接调用：
```python
await bot.call_api("send_group_msg", {
    "group_id": 123456,
    "message": [{
        "type": "record",
        "data": {"file": "http://example.com/voice.amr"}
    }]
})
```

## 下一步

- [消息 API](./message.md): 怎么发消息、撤回消息，包含消息段的使用
- [群组 API](./group.md): 管理群聊相关功能
- [好友 API](./friend.md): 管理好友相关功能