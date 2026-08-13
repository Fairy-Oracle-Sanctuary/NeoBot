# API 基础

这一页讲的是 NEO Bot 里 API 调用的底层原理。如果你只是写插件发消息，可以直接跳过这页，去看 [消息 API](./message.md)。

但如果你想了解背后发生了什么，或者想自己封装一些高级功能，那这里的信息会帮到你。

## API 调用流程

简单来说，当你调用 `bot.send_group_msg()` 时：

1.  **你的插件** → `bot.send_group_msg(123456, "hello")`
2.  **Bot 类** → 把它打包成 OneBot 标准的 JSON
3.  **WebSocket** → 通过 `ws.py` 发给 NapCatQQ（或其他 OneBot 实现）
4.  **OneBot 实现** → 收到请求，真的把消息发到 QQ 群里
5.  **响应返回** → 原路返回，告诉 Bot “消息发送成功”

整个过程是异步的，所以你要用 `await`。

## call_api 方法

所有 API 最终都会调用 `BaseAPI.call_api()` 方法。这是最底层的接口：

```python
async def call_api(self, action: str, params: Optional[Dict[str, Any]] = None) -> Any:
```

- `action`: API 动作名，比如 `"send_group_msg"`、`"get_login_info"`
- `params`: 参数字典，比如 `{"group_id": 123456, "message": "hello"}`

### 返回值

`call_api` 返回的是 OneBot 响应中的 `data` 字段。如果 API 调用失败（返回 `{"status": "failed", ...}`），它会记录一条警告日志，但**不会抛出异常**（除非网络错误）。

这样设计是为了让插件能更灵活地处理失败情况。比如：

```python
try:
    result = await bot.call_api("send_group_msg", {"group_id": 123456, "message": "test"})
    if result is None:
        print("API 调用失败，但没抛异常")
except Exception as e:
    print(f"网络或底层错误: {e}")
```

## 响应格式

OneBot v11 的标准响应格式是：

```json
{
  "status": "ok",
  "retcode": 0,
  "data": { ... },
  "message": "",
  "echo": "请求时的 echo 值（如果有）"
}
```

- `status`: `"ok"` 或 `"failed"`
- `retcode`: 状态码，0 表示成功
- `data`: 真正的返回数据
- `message`: 错误信息（失败时）
- `echo`: 用来匹配请求和响应的标识（WebSocket 用）

NEO Bot 的 `call_api` 方法会自动提取 `data` 字段返回给你。如果 `status` 是 `"failed"`，它会在日志里记录警告，但依然返回 `data`（通常是 `None` 或空字典）。

## 错误处理

API 调用可能因为各种原因失败：

1.  **网络问题**: WebSocket 断开、超时
2.  **权限不足**: 机器人不是管理员却想踢人
3.  **参数错误**: 群号不存在、消息太长
4.  **客户端不支持**: 某些 OneBot 实现可能没实现某些 API

建议在插件里做好错误处理：

```python
@matcher.command("kick")
async def handle_kick(event: MessageEvent, args: list[str]):
    target_id = int(args[0]) if args and args[0].isdigit() else 0
    if not target_id:
        await event.reply("参数错误，需要 QQ 号")
        return
    
    try:
        result = await event.bot.set_group_kick(event.group_id, target_id)
        if result.get("status") == "failed":
            await event.reply(f"踢人失败: {result.get('message', '未知错误')}")
        else:
            await event.reply("踢人成功")
    except Exception as e:
        await event.reply(f"网络错误: {e}")
```

## 直接调用 vs 高级封装

NEO Bot 提供了两种调用 API 的方式：

### 1. 直接调用 `call_api`

```python
await bot.call_api("send_group_msg", {"group_id": 123456, "message": "hello"})
```

**什么时候用？**
- 你想调用的 API 没有被封装成独立方法（很少见）
- 你在调试，想看看原始请求和响应
- 你在写框架代码，需要动态生成 action 名

### 2. 使用封装好的方法

```python
await bot.send_group_msg(123456, "hello")
```

**这是推荐的方式**，因为：
- 有类型提示，编辑器能帮你补全
- 参数有文档，不用去查 OneBot 标准
- 有些方法有额外逻辑（比如缓存、参数转换）

## 下一步

现在你了解了 API 调用的基础。接下来可以去看看具体的 API 类别：

- [消息 API](./message.md): 最常用，先看这个
- [群组 API](./group.md): 管理群聊
- [好友 API](./friend.md): 好友相关操作
- [账号 API](./account.md): 机器人自身状态
- [媒体 API](./media.md): 图片、语音