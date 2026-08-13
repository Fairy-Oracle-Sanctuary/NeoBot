# 账号 API

这一页讲的是怎么管理机器人自己的账号：查看登录信息、设置在线状态、修改资料、退出登录等等。这些都是跟机器人自身相关的操作。

## 账号信息

### `get_login_info` - 获取登录信息

```python
async def get_login_info(self, no_cache: bool = False) -> LoginInfo
```

获取当前登录的机器人账号信息。默认会缓存 1 小时。

**参数：**
- `no_cache`: 是否跳过缓存，直接从服务器获取

**返回值：**
- `LoginInfo`: 登录信息对象

**示例：**
```python
info = await bot.get_login_info()
print(f"机器人QQ号: {info.user_id}")
print(f"机器人昵称: {info.nickname}")
```

`LoginInfo` 对象包含：
- `user_id`: 机器人 QQ 号
- `nickname`: 机器人昵称

### `get_version_info` - 获取版本信息

```python
async def get_version_info(self) -> VersionInfo
```

获取 OneBot v11 实现的版本信息（比如 NapCatQQ 的版本）。

**返回值：**
- `VersionInfo`: 版本信息对象

**示例：**
```python
version = await bot.get_version_info()
print(f"客户端: {version.app_name}")
print(f"版本: {version.app_version}")
print(f"OneBot 协议版本: {version.protocol_version}")
```

`VersionInfo` 对象包含：
- `app_name`: 客户端名称（如 "NapCatQQ"）
- `app_version`: 客户端版本
- `protocol_version`: 支持的 OneBot 协议版本

### `get_status` - 获取运行状态

```python
async def get_status(self) -> Status
```

获取 OneBot 实现的运行状态信息。

**返回值：**
- `Status`: 状态信息对象

**示例：**
```python
status = await bot.get_status()
print(f"在线: {status.online}")
print(f"状态: {status.status}")
print(f"正常: {status.good}")
```

`Status` 对象包含：
- `online`: 是否在线
- `status`: 状态描述
- `good`: 运行是否正常

### `get_profile_like` - 获取资料点赞信息

```python
async def get_profile_like(self) -> Dict[str, Any]
```

获取个人资料的点赞信息。

**返回值：**
- 包含点赞信息的字典

### `nc_get_user_status` - 获取用户在线状态 (NapCat)

```python
async def nc_get_user_status(self, user_id: int) -> Dict[str, Any]
```

获取指定用户的在线状态（NapCatQQ 特有 API）。

**参数：**
- `user_id`: 目标用户的 QQ 号

**返回值：**
- 包含用户状态信息的字典


## 状态设置

### `set_self_longnick` - 设置个性签名

```python
async def set_self_longnick(self, long_nick: str) -> Dict[str, Any]
```

设置机器人账号的个性签名（QQ 资料里的那个长签名）。

**参数：**
- `long_nick`: 要设置的个性签名内容

**示例：**
```python
@matcher.command("setsign")
async def handle_setsign(event: MessageEvent, args: list[str]):
    if not args:
        await event.reply("需要签名内容")
        return
    
    await event.bot.set_self_longnick(" ".join(args))
    await event.reply("个性签名已更新")
```

### `set_online_status` - 设置在线状态

```python
async def set_online_status(self, status_code: int) -> Dict[str, Any]
```

设置机器人的在线状态（在线、离开、忙碌等）。

**参数：**
- `status_code`: 状态码
  - `1`: 在线
  - `2`: 离开
  - `3`: 忙碌
  - `4`: 请勿打扰
  - `5`: 隐身
  - 其他值取决于客户端支持

**示例：**
```python
# 设置为隐身
await bot.set_online_status(5)
```

### `set_diy_online_status` - 设置自定义在线状态

```python
async def set_diy_online_status(
    self,
    face_id: int,
    face_type: int,
    wording: str
) -> Dict[str, Any]
```

设置自定义的在线状态（需要客户端支持）。

**参数：**
- `face_id`: 状态表情 ID
- `face_type`: 状态表情类型
- `wording`: 状态描述文本

**示例：**
```python
# 设置为"摸鱼中"
await bot.set_diy_online_status(
    face_id=100,
    face_type=1,
    wording="摸鱼中"
)
```

### `set_input_status` - 设置"正在输入"状态

```python
async def set_input_status(
    self,
    user_id: int,
    event_type: int
) -> Dict[str, Any]
```

向指定用户显示"对方正在输入..."的状态提示。

**参数：**
- `user_id`: 目标用户的 QQ 号
- `event_type`: 事件类型（具体含义取决于客户端）

**示例：**
```python
# 向某个用户显示"正在输入"
await bot.set_input_status(123456, 1)
```

## 资料修改

### `set_qq_profile` - 设置个人资料

```python
async def set_qq_profile(self, **kwargs) -> Dict[str, Any]
```

设置机器人账号的个人资料。

**参数：**
- `**kwargs`: 个人资料的相关参数，具体字段请参考 OneBot v11 规范

**示例：**
```python
# 修改昵称
await bot.set_qq_profile(nickname="新的昵称")

# 修改多个字段
await bot.set_qq_profile(
    nickname="新昵称",
    sex="female",
    age=18,
    level=50
)
```

### `set_qq_avatar` - 设置头像

```python
async def set_qq_avatar(self, **kwargs) -> Dict[str, Any]
```

设置机器人账号的头像。

**参数：**
- `**kwargs`: 头像的相关参数，具体字段请参考 OneBot v11 规范

**示例：**
```python
# 设置头像（具体参数格式取决于客户端）
await bot.set_qq_avatar(file="path/to/avatar.jpg")
```

## 系统操作

### `bot_exit` - 退出登录

```python
async def bot_exit(self) -> Dict[str, Any]
```

让机器人进程退出（需要客户端支持）。谨慎使用！

**示例：**
```python
from neobot.core.permission import Permission

@matcher.command("shutdown", permission=Permission.ADMIN)
async def handle_shutdown(event: MessageEvent):
    await event.reply("机器人正在退出...")
    await event.bot.bot_exit()
```

### `clean_cache` - 清理缓存

```python
async def clean_cache(self) -> Dict[str, Any]
```

清理 OneBot 客户端的缓存。

**示例：**
```python
from neobot.core.permission import Permission

@matcher.command("clearcache", permission=Permission.ADMIN)
async def handle_clearcache(event: MessageEvent):
    await event.bot.clean_cache()
    await event.reply("缓存已清理")
```

### `get_clientkey` - 获取客户端密钥

```python
async def get_clientkey(self) -> Dict[str, Any]
```

获取客户端密钥（通常用于 QQ 登录相关操作）。

**返回值：**
- 包含客户端密钥的字典

## 实用示例

### 机器人状态查询插件

```python
@matcher.command("status")
async def handle_status(event: MessageEvent):
    # 获取各种信息
    login_info = await event.bot.get_login_info()
    version_info = await event.bot.get_version_info()
    status_info = await event.bot.get_status()
    
    # 构建状态消息
    msg = "🤖 机器人状态\n"
    msg += f"QQ号: {login_info.user_id}\n"
    msg += f"昵称: {login_info.nickname}\n"
    msg += f"客户端: {version_info.app_name} v{version_info.app_version}\n"
    msg += f"协议: OneBot v{version_info.protocol_version}\n"
    msg += f"状态: {'在线' if status_info.online else '离线'}\n"
    msg += f"运行: {'正常' if status_info.good else '异常'}"
    
    await event.reply(msg)
```

### 自动切换状态

```python
import asyncio
from datetime import datetime

async def auto_status_scheduler(bot):
    """
    定时自动切换状态
    """
    while True:
        now = datetime.now().hour
        
        if 9 <= now < 18:
            # 工作时间：在线
            await bot.set_online_status(1)
            status_text = "工作中"
        elif 18 <= now < 22:
            # 晚上：离开
            await bot.set_online_status(2)
            status_text = "休息中"
        else:
            # 深夜：隐身
            await bot.set_online_status(5)
            status_text = "睡眠模式"
        
        # 设置个性签名
        await bot.set_self_longnick(f"当前状态: {status_text} | 最后更新: {datetime.now():%H:%M}")
        
        # 每小时更新一次
        await asyncio.sleep(3600)

# 在初始化插件时启动
# （注意：这只是一个示例，实际使用需要考虑插件生命周期）
```

### 资料备份与恢复

```python
import json

from neobot.core.permission import Permission

@matcher.command("backupprofile", permission=Permission.ADMIN)
async def handle_backup_profile(event: MessageEvent):
    """
    备份当前资料到文件
    """
    # 获取当前登录信息
    login_info = await event.bot.get_login_info()
    
    # 构建备份数据
    backup_data = {
        "user_id": login_info.user_id,
        "nickname": login_info.nickname,
        "backup_time": datetime.now().isoformat()
    }
    
    # 保存到文件
    filename = f"profile_backup_{login_info.user_id}.json"
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(backup_data, f, ensure_ascii=False, indent=2)
    
    await event.reply(f"资料已备份到 {filename}")

@matcher.command("restoreprofile", permission=Permission.ADMIN)
async def handle_restore_profile(event: MessageEvent, args: list[str]):
    """
    从备份恢复资料
    """
    if not args:
        await event.reply("需要备份文件名")
        return
    
    filename = args[0]
    try:
        with open(filename, "r", encoding="utf-8") as f:
            backup_data = json.load(f)
        
        # 恢复资料（这里只是示例，实际可能需要更多字段）
        await event.bot.set_qq_profile(
            nickname=backup_data.get("nickname", "")
        )
        
        await event.reply("资料已恢复")
    except Exception as e:
        await event.reply(f"恢复失败: {e}")
```

## 注意事项

1. **权限**: 修改资料、退出登录等操作通常需要机器人有相应权限。
2. **频率限制**: 不要频繁修改资料或状态，可能被限制。
3. **客户端支持**: 不是所有 OneBot 客户端都支持全部 API，使用前最好测试一下。
4. **谨慎操作**: `bot_exit` 会让机器人下线，谨慎使用。

## 下一步

- [好友 API](./friend.md): 管理好友相关功能
- [群组 API](./group.md): 管理群聊相关功能
- [消息 API](./message.md): 怎么发消息、撤回消息