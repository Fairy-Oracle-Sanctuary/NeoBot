# API 参考

嘿，这里是 NEO Bot 的 API 参考文档。

如果你在写插件，那这里就是你的工具库。所有能和 OneBot 交互的方法都在这了。

## 快速导航

### 1. 基础概念
- [API 调用方式](./base.md): 怎么调用 API、参数格式、返回格式
- [消息段 (MessageSegment)](./message.md#消息段): 除了文字，还能发图片、表情、@人……

### 2. 分类 API
- [消息 API](./message.md): 发消息、撤回、转发
- [群组 API](./group.md): 管群、禁言、踢人、改名片
- [好友 API](./friend.md): 好友列表、点赞、加好友请求
- [账号 API](./account.md): 机器人自己的信息、状态设置
- [媒体 API](./media.md): 图片、语音相关

### 3. 高级功能
- [合并转发](./message.md#合并转发): 怎么发那种一条消息展开好多条的“聊天记录”
- [智能回复](./message.md#智能回复): `event.reply()` 和 `bot.send()` 怎么选

## 怎么用这些 API

在插件里，你拿到的 `event` 对象自带一个 `bot` 属性，那就是你的机器人实例：

```python
from neobot.core.managers.command_manager import matcher
from neobot.models import MessageEvent

@matcher.command("test")
async def handle_test(event: MessageEvent):
    # 方法 1: 快捷回复（推荐）
    await event.reply("你好！")
    
    # 方法 2: 直接调用 bot 上的 API
    bot = event.bot
    await bot.send_group_msg(123456, "这是一条群消息")
    
    # 方法 3: 如果你只有 bot 实例，没有 event
    # （这种情况比较少见，一般只在初始化时用到）
    await bot.get_login_info()
```

大部分时候，用 `event.reply()` 就够了。它帮你判断是群聊还是私聊，自动调用正确的 API。

## 兼容性说明

NEO Bot 基于 **OneBot v11** 标准实现，兼容：
- [NapCatQQ](https://github.com/NapNeko/NapCatQQ) （推荐）
- go-cqhttp
- 以及其他实现了 OneBot v11 标准的客户端

但要注意：不同客户端的实现细节可能有差异。比如某些 API 可能不支持，或者参数格式稍有不同。

如果你发现某个 API 调用失败，先看看日志里的错误信息，或者去对应客户端的文档里查查。

## 接下来？

挑一个你感兴趣的类别开始看吧。建议从 [消息 API](./message.md) 开始，因为发消息是最常用的功能。