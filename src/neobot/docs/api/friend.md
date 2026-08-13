# 好友 API

这一页讲的是怎么管理好友：获取好友列表、给好友点赞、处理加好友请求，还有获取陌生人信息。

## 好友列表

### `get_friend_list` - 获取好友列表

```python
async def get_friend_list(self, no_cache: bool = False) -> List[FriendInfo]
```

获取机器人账号的所有好友列表。默认会缓存 1 小时。

**参数：**
- `no_cache`: 是否跳过缓存，直接从服务器获取最新列表

**返回值：**
- `List[FriendInfo]`: 好友信息对象列表

**示例：**
```python
friends = await bot.get_friend_list()
print(f"我有 {len(friends)} 个好友")
for friend in friends:
    print(f"{friend.user_id}: {friend.nickname} (备注: {friend.remark})")
```

`FriendInfo` 对象包含以下字段：
- `user_id`: QQ 号
- `nickname`: 昵称
- `remark`: 备注（你给好友设置的备注名）
- 其他可能的信息字段

## 陌生人信息

### `get_stranger_info` - 获取陌生人信息

```python
async def get_stranger_info(
    self,
    user_id: int,
    no_cache: bool = False
) -> StrangerInfo
```

获取非好友的 QQ 用户信息。默认会缓存 1 小时。

**参数：**
- `user_id`: 目标用户的 QQ 号
- `no_cache`: 是否跳过缓存

**返回值：**
- `StrangerInfo`: 陌生人信息对象

**示例：**
```python
@matcher.command("who")
async def handle_who(event: MessageEvent, args: list[str]):
    if not args or not args[0].isdigit():
        await event.reply("参数错误，需要 QQ 号")
        return
    
    target_id = int(args[0])
    info = await event.bot.get_stranger_info(target_id)
    
    msg = f"用户 {target_id} 的信息：\n"
    msg += f"昵称: {info.nickname}\n"
    msg += f"性别: {info.sex}\n"
    msg += f"年龄: {info.age}\n"
    msg += f"等级: {info.level}"
    
    await event.reply(msg)
```

`StrangerInfo` 对象包含以下字段：
- `user_id`: QQ 号
- `nickname`: 昵称
- `sex`: 性别（`male`/`female`/`unknown`）
- `age`: 年龄
- `level`: QQ 等级
- 其他可能的信息字段

### `get_friends_with_category` - 获取分类好友列表

```python
async def get_friends_with_category(self) -> Dict[str, Any]
```

获取带分组信息的好友列表。

**返回值：**
- 包含分组和好友信息的字典

### `get_unidirectional_friend_list` - 获取单向好友列表

```python
async def get_unidirectional_friend_list(self) -> Dict[str, Any]
```

获取单向好友（你加了对方，对方没加你）的列表。

**返回值：**
- 单向好友列表

## 互动功能

### `send_like` - 发送点赞（戳一戳）

```python
async def send_like(
    self,
    user_id: int,
    times: int = 1
) -> Dict[str, Any]
```

给指定用户发送"戳一戳"（点赞）。每天有次数限制，建议不要超过 10 次。

**参数：**
- `user_id`: 目标用户的 QQ 号
- `times`: 点赞次数，建议 1-10 次

**示例：**
```python
@matcher.command("like")
async def handle_like(event: MessageEvent, args: list[str]):
    # 给发送者点赞
    await event.bot.send_like(event.user_id, times=1)
    await event.reply("给你点了个赞！")
    
    # 如果提供了参数，给指定用户点赞
    if args and args[0].isdigit():
        target_id = int(args[0])
        await event.bot.send_like(target_id, times=1)
        await event.reply(f"给 {target_id} 点了个赞！")
```

**注意：**
- 不是所有 OneBot 实现都支持这个 API
- 有每日次数限制，不要滥用
- 对方可能关闭了"戳一戳"功能，这时会失败

### `friend_poke` - 发送好友戳一戳 (新)

```python
async def friend_poke(self, user_id: int) -> Dict[str, Any]
```

对指定好友发送"戳一戳"（比 `send_like` 更通用的接口）。

**参数：**
- `user_id`: 目标用户的 QQ 号

## 消息历史与状态

### `mark_private_msg_as_read` - 标记私聊已读

```python
async def mark_private_msg_as_read(self, user_id: int, time: int = 0) -> Dict[str, Any]
```

将与指定用户的私聊消息标记为已读。

**参数：**
- `user_id`: 目标用户的 QQ 号
- `time`: 将此时间戳（秒）之前的消息标记为已读，传 `0` 表示全部标记

### `get_friend_msg_history` - 获取私聊历史

```python
async def get_friend_msg_history(self, user_id: int, count: int = 20) -> Dict[str, Any]
```

获取与指定用户的私聊历史记录。

**参数：**
- `user_id`: 目标用户的 QQ 号
- `count`: 要获取的消息数量，默认 20

### `forward_friend_single_msg` - 转发单条消息

```python
async def forward_friend_single_msg(self, user_id: int, message_id: str) -> Dict[str, Any]
```

将一条消息转发给指定好友。

**参数：**
- `user_id`: 接收消息的好友 QQ 号
- `message_id`: 要转发的消息的 ID

## 加好友请求处理

### `set_friend_add_request` - 处理加好友请求

```python
async def set_friend_add_request(
    self,
    flag: str,
    approve: bool = True,
    remark: str = ""
) -> Dict[str, Any]
```

处理收到的加好友请求。需要在 `request` 事件中调用。

**参数：**
- `flag`: 请求标识，从 `request` 事件的 `flag` 字段获取
- `approve`: 是否同意，`True` 同意，`False` 拒绝
- `remark`: 同意请求时，为该好友设置的备注（可选）

**示例：**
```python
from neobot.models import RequestEvent
from neobot.core.managers.command_manager import matcher

# 处理所有加好友请求
@matcher.on_request()
async def handle_friend_request(event: RequestEvent):
    if event.request_type == "friend":
        # 自动同意并设置备注
        await event.bot.set_friend_add_request(
            flag=event.flag,
            approve=True,
            remark=f"自动添加-{event.user_id}"
        )
        
        # 给新好友发个欢迎消息
        await event.bot.send_private_msg(
            event.user_id,
            "你好！我是机器人，已自动通过你的好友请求。"
        )
```

## 实用示例

### 好友信息查询插件

```python
@matcher.command("friendinfo")
async def handle_friendinfo(event: MessageEvent):
    # 获取好友列表
    friends = await event.bot.get_friend_list()
    
    # 按备注名排序
    sorted_friends = sorted(friends, key=lambda f: f.remark or f.nickname)
    
    # 生成好友列表消息
    if len(sorted_friends) > 50:
        msg = f"好友太多啦，只显示前50个（共{len(sorted_friends)}个）\n"
        sorted_friends = sorted_friends[:50]
    else:
        msg = f"我的好友列表（共{len(sorted_friends)}个）:\n"
    
    for i, friend in enumerate(sorted_friends, 1):
        remark_display = friend.remark if friend.remark else "（无备注）"
        msg += f"{i}. {friend.nickname} ({friend.user_id}) - 备注: {remark_display}\n"
    
    await event.reply(msg)
```

### 自动通过特定用户的好友请求

```python
from neobot.models import RequestEvent
from neobot.core.managers.command_manager import matcher

@matcher.on_request()
async def handle_specific_friend_request(event: RequestEvent):
    if event.request_type != "friend":
        return
    
    # 允许列表
    allowed_users = [123456, 789012, 345678]
    
    if event.user_id in allowed_users:
        # 自动同意
        await event.bot.set_friend_add_request(
            flag=event.flag,
            approve=True,
            remark="重要联系人"
        )
        
        # 发送欢迎消息
        await event.bot.send_private_msg(
            event.user_id,
            "你好！已通过你的好友请求。\n"
            "发送 /help 查看可用指令。"
        )
    else:
        # 拒绝其他人
        await event.bot.set_friend_add_request(
            flag=event.flag,
            approve=False,
            reason="仅限授权用户添加"
        )
```

### 批量给好友发送消息（谨慎使用！）

```python
from neobot.core.permission import Permission

@matcher.command("broadcast", permission=Permission.ADMIN)
async def handle_broadcast(event: MessageEvent, args: list[str]):
    if not args:
        await event.reply("需要广播内容")
        return
    content = " ".join(args)
    
    # 获取好友列表
    friends = await event.bot.get_friend_list()
    
    success_count = 0
    fail_count = 0
    
    await event.reply(f"开始向 {len(friends)} 个好友发送广播...")
    
    for friend in friends:
        try:
            await event.bot.send_private_msg(friend.user_id, content)
            success_count += 1
            # 避免发送太快被限制
            await asyncio.sleep(0.5)
        except Exception as e:
            print(f"发送给 {friend.user_id} 失败: {e}")
            fail_count += 1
    
    await event.reply(
        f"广播完成！\n"
        f"成功: {success_count} 个\n"
        f"失败: {fail_count} 个"
    )
```

**注意**：批量发送消息容易被腾讯限制，谨慎使用！

## 注意事项

1. **频率限制**: 获取好友列表、查询陌生人信息等操作有频率限制。
2. **缓存**: 好友列表和陌生人信息默认缓存 1 小时，如果需要实时数据，设 `no_cache=True`。
3. **权限**: 有些 API 需要特定的权限或客户端支持。
4. **隐私**: 处理好友请求时，注意保护用户隐私。

## 下一步

- [账号 API](./account.md): 管理机器人自己的信息
- [群组 API](./group.md): 管理群聊相关功能
- [消息 API](./message.md): 怎么发消息、撤回消息