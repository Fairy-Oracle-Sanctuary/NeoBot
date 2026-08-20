# 群组 API

管群是个技术活。这一页讲的是怎么管理群聊：踢人、禁言、改名片、设管理员……所有跟群相关的操作都在这里。

## 权限说明

**重要提醒**：很多群管理 API 需要机器人有相应的权限：
- **管理员权限**：禁言、踢人、改群名片等
- **群主权限**：解散群、设置管理员等

如果机器人权限不足，API 调用会失败。建议先检查机器人的权限，或者做好错误处理。

## 成员管理

### `set_group_kick` - 踢出群聊

```python
async def set_group_kick(
    self,
    group_id: int,
    user_id: int,
    reject_add_request: bool = False
) -> Dict[str, Any]
```

把指定成员踢出群聊。

**参数：**
- `group_id`: 群号
- `user_id`: 要踢出的成员的 QQ 号
- `reject_add_request`: 是否同时拒绝该用户此后的加群请求（默认 `False`）

**示例：**
```python
@matcher.command("kick")
async def handle_kick(event: MessageEvent, args: list[str]):
    if not args or not args[0].isdigit():
        await event.reply("参数错误，需要 QQ 号")
        return
    
    target_id = int(args[0])
    await event.bot.set_group_kick(event.group_id, target_id)
    await event.reply(f"已踢出 {target_id}")
```

### `set_group_ban` - 禁言/解除禁言

```python
async def set_group_ban(
    self,
    group_id: int,
    user_id: int,
    duration: int = 1800
) -> Dict[str, Any]
```

禁言群成员。设置 `duration=0` 可以解除禁言。

**参数：**
- `group_id`: 群号
- `user_id`: 要禁言的成员的 QQ 号
- `duration`: 禁言时长，单位秒。默认 1800 秒（30 分钟），0 表示解除禁言

**示例：**
```python
# 禁言 10 分钟
await bot.set_group_ban(123456, 789012, duration=600)

# 解除禁言
await bot.set_group_ban(123456, 789012, duration=0)
```

### `set_group_anonymous_ban` - 禁言匿名用户

```python
async def set_group_anonymous_ban(
    self,
    group_id: int,
    anonymous: Optional[Dict[str, Any]] = None,
    duration: int = 1800,
    flag: Optional[str] = None
) -> Dict[str, Any]
```

禁言发送匿名消息的用户。需要从消息事件的 `anonymous` 字段获取匿名用户信息。

**参数：**
- `group_id`: 群号
- `anonymous`: 匿名用户对象（从事件中获取）
- `duration`: 禁言时长，单位秒
- `flag`: 匿名用户的 flag 标识（从事件中获取）

**示例：**
```python
@matcher.command("ban_anonymous")
async def handle_ban_anonymous(event: GroupMessageEvent):
    if not event.anonymous:
        await event.reply("这不是匿名消息")
        return
    
    # 方法 1: 使用 anonymous 对象
    await event.bot.set_group_anonymous_ban(
        event.group_id,
        anonymous=event.anonymous,
        duration=3600  # 禁言 1 小时
    )
    
    # 方法 2: 使用 flag（如果事件中有的话）
    # await event.bot.set_group_anonymous_ban(
    #     event.group_id,
    #     flag=event.anonymous.get("flag"),
    #     duration=3600
    # )
```

### `set_group_whole_ban` - 全员禁言

```python
async def set_group_whole_ban(
    self,
    group_id: int,
    enable: bool = True
) -> Dict[str, Any]
```

开启或关闭全员禁言。

**参数：**
- `group_id`: 群号
- `enable`: `True` 开启全员禁言，`False` 关闭

**示例：**
```python
# 开启全员禁言
await bot.set_group_whole_ban(123456, enable=True)

# 关闭全员禁言
await bot.set_group_whole_ban(123456, enable=False)
```

## 权限设置

### `set_group_admin` - 设置/取消管理员

```python
async def set_group_admin(
    self,
    group_id: int,
    user_id: int,
    enable: bool = True
) -> Dict[str, Any]
```

设置或取消群管理员。**需要机器人是群主**。

**参数：**
- `group_id`: 群号
- `user_id`: 目标成员的 QQ 号
- `enable`: `True` 设为管理员，`False` 取消管理员

**示例：**
```python
# 设某人为管理员
await bot.set_group_admin(123456, 789012, enable=True)

# 取消某人的管理员
await bot.set_group_admin(123456, 789012, enable=False)
```

### `set_group_anonymous` - 匿名聊天设置

```python
async def set_group_anonymous(
    self,
    group_id: int,
    enable: bool = True
) -> Dict[str, Any]
```

开启或关闭群匿名聊天功能。**需要机器人是管理员**。

**参数：**
- `group_id`: 群号
- `enable`: `True` 开启匿名，`False` 关闭

## 成员信息

### `set_group_card` - 设置群名片

```python
async def set_group_card(
    self,
    group_id: int,
    user_id: int,
    card: str = ""
) -> Dict[str, Any]
```

设置群成员的群名片（群内显示的名称）。传空字符串可以删除群名片，恢复为昵称。

**参数：**
- `group_id`: 群号
- `user_id`: 目标成员的 QQ 号
- `card`: 要设置的群名片内容，空字符串表示删除

**示例：**
```python
# 设置群名片
await bot.set_group_card(123456, 789012, "技术大佬")

# 删除群名片（恢复为昵称）
await bot.set_group_card(123456, 789012, "")
```

### `set_group_special_title` - 设置专属头衔

```python
async def set_group_special_title(
    self,
    group_id: int,
    user_id: int,
    special_title: str = "",
    duration: int = -1
) -> Dict[str, Any]
```

为群成员设置专属头衔（群主/管理员才有权限设置）。**需要机器人是群主**。

**参数：**
- `group_id`: 群号
- `user_id`: 目标成员的 QQ 号
- `special_title`: 专属头衔内容，空字符串表示删除
- `duration`: 头衔有效期，单位秒。-1 表示永久

**示例：**
```python
# 设置永久头衔
await bot.set_group_special_title(123456, 789012, "御用摄影师", duration=-1)

# 设置 7 天有效的头衔
await bot.set_group_special_title(123456, 789012, "本周活跃之星", duration=7*24*3600)

# 删除头衔
await bot.set_group_special_title(123456, 789012, "")
```

## 群信息管理

### `set_group_name` - 修改群名

```python
async def set_group_name(
    self,
    group_id: int,
    group_name: str
) -> Dict[str, Any]
```

修改群名称。**需要机器人是群主或管理员**。

**参数：**
- `group_id`: 群号
- `group_name`: 新的群名称

**示例：**
```python
await bot.set_group_name(123456, "技术交流群")
```

### `set_group_leave` - 退出/解散群聊

```python
async def set_group_leave(
    self,
    group_id: int,
    is_dismiss: bool = False
) -> Dict[str, Any]
```

退出群聊，如果是群主还可以解散群。

**参数：**
- `group_id`: 群号
- `is_dismiss`: 是否解散群（仅群主有效）

**示例：**
```python
# 普通退群
await bot.set_group_leave(123456)

# 解散群（需要是群主）
await bot.set_group_leave(123456, is_dismiss=True)
```

## 获取信息

### `get_group_info` - 获取群信息

```python
async def get_group_info(
    self,
    group_id: int,
    no_cache: bool = False
) -> GroupInfo
```

获取群的详细信息，包括群名、成员数、创建时间等。默认会缓存 1 小时。

**参数：**
- `group_id`: 群号
- `no_cache`: 是否跳过缓存，直接从服务器获取最新信息

**返回值：**
- `GroupInfo` 对象，包含群信息

**示例：**
```python
info = await bot.get_group_info(123456)
print(f"群名: {info.group_name}")
print(f"成员数: {info.member_count}")
print(f"创建时间: {info.create_time}")
```

### `get_group_list` - 获取群列表

```python
async def get_group_list(self) -> List[GroupInfo]
```

获取机器人加入的所有群列表。

**示例：**
```python
groups = await bot.get_group_list()
for group in groups:
    print(f"{group.group_id}: {group.group_name}")
```

### `get_group_member_info` - 获取群成员信息

```python
async def get_group_member_info(
    self,
    group_id: int,
    user_id: int,
    no_cache: bool = False
) -> GroupMemberInfo
```

获取指定群成员的详细信息，包括昵称、群名片、加群时间、最后发言时间等。

**参数：**
- `group_id`: 群号
- `user_id`: 成员 QQ 号
- `no_cache`: 是否跳过缓存

**返回值：**
- `GroupMemberInfo` 对象

**示例：**
```python
member = await bot.get_group_member_info(123456, 789012)
print(f"昵称: {member.nickname}")
print(f"群名片: {member.card}")
print(f"权限: {member.role}")  # owner, admin, member
```

### `get_group_member_list` - 获取群成员列表

```python
async def get_group_member_list(self, group_id: int) -> List[GroupMemberInfo]
```

获取群的所有成员列表。

**示例：**
```python
members = await bot.get_group_member_list(123456)
print(f"群里有 {len(members)} 个成员")
for member in members:
    print(f"{member.user_id}: {member.nickname}")
```

### `get_group_honor_info` - 获取群荣誉信息

```python
async def get_group_honor_info(
    self,
    group_id: int,
    type: str
) -> GroupHonorInfo
```

获取群的荣誉信息，比如龙王、群聊之火、快乐源泉等。

**参数：**
- `group_id`: 群号
- `type`: 荣誉类型，可选值:
  - `"talkative"`: 龙王（发言最多）
  - `"performer"`: 群聊之火（发言最活跃）
  - `"legend"`: 群传奇（连续多天发言最多）
  - `"strong_newbie"`: 冒尖小萌新（新人中发言最多）
  - `"emotion"`: 快乐源泉（发送表情包最多）

**示例：**
```python
honor = await bot.get_group_honor_info(123456, "talkative")
print(f"本周龙王: {honor.current_talkative.user_id}")
```

### `get_group_info_ex` - 获取群扩展信息 (NapCat)

```python
async def get_group_info_ex(self, group_id: int) -> Dict[str, Any]
```

获取群的扩展信息（NapCatQQ 特有 API）。

**参数：**
- `group_id`: 群号

**返回值：**
- 包含群扩展信息的字典

## 精华消息

### `delete_essence_msg` - 删除精华消息

```python
async def delete_essence_msg(self, message_id: int) -> Dict[str, Any]
```

删除一条精华消息。

**参数：**
- `message_id`: 目标消息的 ID

## 互动与状态

### `group_poke` - 群内戳一戳

```python
async def group_poke(self, group_id: int, user_id: int) -> Dict[str, Any]
```

在群内对指定成员发送"戳一戳"。

**参数：**
- `group_id`: 群号
- `user_id`: 目标成员的 QQ 号

### `mark_group_msg_as_read` - 标记群消息已读

```python
async def mark_group_msg_as_read(self, group_id: int, time: int = 0) -> Dict[str, Any]
```

将指定群聊的消息标记为已读。

**参数：**
- `group_id`: 群号
- `time`: 将此时间戳（秒）之前的消息标记为已读，传 `0` 表示全部标记

## 消息转发

### `forward_group_single_msg` - 转发单条群消息

```python
async def forward_group_single_msg(self, group_id: int, message_id: str) -> Dict[str, Any]
```

将一条群消息转发到当前群聊。

**参数：**
- `group_id`: 群号
- `message_id`: 要转发的消息的 ID

## 群设置 (高级)

### `set_group_portrait` - 设置群头像

```python
async def set_group_portrait(self, group_id: int, file: str, cache: int = 1) -> Dict[str, Any]
```

设置群头像。

**参数：**
- `group_id`: 群号
- `file`: 图片文件的路径、URL 或 Base64 字符串
- `cache`: 是否使用缓存（`1` 是，`0` 否）

### `set_group_remark` - 设置群备注

```python
async def set_group_remark(self, group_id: int, remark: str) -> Dict[str, Any]
```

设置群备注（NapCatQQ 特有 API）。

**参数：**
- `group_id`: 群号
- `remark`: 要设置的备注

### `set_group_sign` - 群签到

```python
async def set_group_sign(self, group_id: int) -> Dict[str, Any]
```

在指定群聊中进行签到。

**参数：**
- `group_id`: 群号

## 群公告

### `_send_group_notice` - 发送群公告

```python
async def _send_group_notice(self, group_id: int, content: str, **kwargs) -> Dict[str, Any]
```

发送群公告。

**参数：**
- `group_id`: 群号
- `content`: 公告内容
- `**kwargs`: 其他可选参数，如 `image`

### `_get_group_notice` - 获取群公告

```python
async def _get_group_notice(self, group_id: int) -> Dict[str, Any]
```

获取群公告列表。

**参数：**
- `group_id`: 群号

### `_del_group_notice` - 删除群公告

```python
async def _del_group_notice(self, group_id: int, notice_id: str) -> Dict[str, Any]
```

删除指定的群公告。

**参数：**
- `group_id`: 群号
- `notice_id`: 要删除的公告的 ID

## 其他信息获取

### `get_group_at_all_remain` - 获取@全体剩余次数

```python
async def get_group_at_all_remain(self, group_id: int) -> Dict[str, Any]
```

获取当天在指定群聊中 @全体成员 的剩余次数。

**参数：**
- `group_id`: 群号

### `get_group_system_msg` - 获取群系统消息

```python
async def get_group_system_msg(self) -> Dict[str, Any]
```

获取群系统消息（如加群请求、退群通知等）。

### `get_group_shut_list` - 获取群禁言列表

```python
async def get_group_shut_list(self, group_id: int) -> Dict[str, Any]
```

获取被禁言的群成员列表。

**参数：**
- `group_id`: 群号

## 加群请求处理

### `set_group_add_request` - 处理加群请求/邀请

```python
async def set_group_add_request(
    self,
    flag: str,
    sub_type: str,
    approve: bool = True,
    reason: str = ""
) -> Dict[str, Any]
```

处理加群请求或邀请。需要在 `request` 事件中调用。

**参数：**
- `flag`: 请求标识，从 `request` 事件的 `flag` 字段获取
- `sub_type`: 请求类型，`"add"`（加群请求）或 `"invite"`（群邀请）
- `approve`: 是否同意，`True` 同意，`False` 拒绝
- `reason`: 拒绝理由（仅在 `approve=False` 时有效）

**示例：**
```python
from neobot.models import RequestEvent

# 在请求事件处理函数中
async def handle_group_request(event: RequestEvent):
    if event.request_type == "group":
        # 自动同意所有加群请求
        await event.bot.set_group_add_request(
            flag=event.flag,
            sub_type=event.sub_type,
            approve=True
        )
```

## 实用示例

### 自动同意加群请求

```python
from neobot.models import RequestEvent
from neobot.core.managers.command_manager import matcher

@matcher.on_request()
async def handle_all_requests(event: RequestEvent):
    if event.request_type == "group":
        # 检查是否来自特定用户
        if event.user_id in [123456, 789012]:
            await event.bot.set_group_add_request(
                flag=event.flag,
                sub_type=event.sub_type,
                approve=True
            )
            await event.bot.send_private_msg(
                event.user_id,
                f"已同意你的加群请求，欢迎加入！"
            )
```

### 群活跃度统计

```python
@matcher.command("active")
async def handle_active(event: MessageEvent):
    # 获取群成员列表
    members = await event.bot.get_group_member_list(event.group_id)
    
    # 找出最后发言时间最近的一批成员
    active_members = sorted(
        members,
        key=lambda m: m.last_sent_time or 0,
        reverse=True
    )[:10]
    
    # 生成统计消息
    msg = "本群最近活跃成员TOP10:\n"
    for i, member in enumerate(active_members, 1):
        msg += f"{i}. {member.nickname} (最后发言: {member.last_sent_time})\n"
    
    await event.reply(msg)
```

## 注意事项

1. **权限检查**: 调用管理 API 前，最好先检查机器人的权限。
2. **频率限制**: 不要频繁调用 API，尤其是获取群成员列表这种大数据量的操作。
3. **缓存**: 获取信息的 API 默认有缓存，如果需要实时数据，记得设 `no_cache=True`。
4. **错误处理**: 管理操作可能失败（权限不足、参数错误等），要做好错误处理。

## 下一步

- [好友 API](./friend.md): 处理好友相关操作
- [账号 API](./account.md): 管理机器人自身状态
- [消息 API](./message.md): 怎么发消息、撤回消息