# 适配器架构（阶段 1~3 落地文档）

> 状态：阶段 1（转发收敛）/ 阶段 2（消息总线 + CommandContext）/ 阶段 3（Discord 不再伪造 OneBot 事件）已完成。
> 本文档描述目标架构、当前实现、数据流与插件迁移指南。

## 1. 目标架构

旧架构把 QQ（OneBot）、Discord、MCC 全部压进 OneBot 事件模型，转发逻辑散落在
`ws.py`、`router.py`、`discord_cross` 三处，靠 `_no_mirror` 等标志互相踩刹车，
导致回显/环路问题（见历史 bug）。新架构以**平台无关消息层**为中心：

```
                    ┌──────────────────────────────┐
                    │  平台无关消息层 core/messaging │
                    │  PlatformMessage / MessageBus │
                    │  CommandContext               │
                    └──────────────┬───────────────┘
            ┌───────────┬──────────┴──────────┬────────────┐
            ▼           ▼                     ▼            ▼
     OneBot(QQ)   DiscordAdapter          MCC 适配器   CrossPlatform
     适配器         (平台收发，无伪事件)     (→ mcc-service) Forwarder
            └───────────┴──────────┬──────────┴────────────┘
                                   ▼
                        插件层（CommandContext / OneBot 事件兼容）
```

约定：

- **适配器只做“平台 ↔ 总线”转换**，不包含转发/翻译/去重等业务逻辑，发送无副作用。
- **跨平台转发只有一个决策点**：`CrossPlatformForwarder`（去重 + 防环 + 映射）。
- **插件入口平台感知**：QQ 插件继续用 OneBot 事件；Discord 插件用 CommandContext，
  不再有“把 Discord 伪装成 QQ 群消息”的中间层。

## 2. 核心组件

### 2.1 PlatformMessage（`core/messaging/message.py`）

跨平台统一消息模型，是消息总线的载荷：

| 字段 | 说明 |
|---|---|
| `platform` | `"qq"` / `"discord"` / `"cli"` / `"mcc"` |
| `channel_id` / `channel_type` | 频道 ID；`"group"` / `"private"` |
| `message_id` / `author_id` / `author_name` | 消息与作者 |
| `content` | 纯文本 |
| `segments` | 平台无关消息段（text/image/video/record） |
| `reply_to` / `metadata` / `raw` | 引用、扩展元数据、平台原始对象 |

### 2.2 MessageBus（`core/messaging/bus.py`）

进程内发布/订阅：

- `message_bus.on_incoming(platform)`：订阅入站消息（转发器等业务逻辑挂这里）
- `message_bus.publish_incoming(msg)`：适配器收到消息后发布
- `message_bus.on_outgoing()` / `publish_outgoing(msg)`：出站发送通知（预留）

单个订阅者异常不影响其他订阅者（错误隔离）。

### 2.3 CommandContext（`core/messaging/context.py`）

平台感知的指令上下文，**属性与 OneBot `MessageEvent` 兼容**
（`message_type` / `group_id` / `user_id` / `raw_message` / `message` / `reply`），
因此从事件迁移到上下文时插件函数体基本不用改。

- `CommandContext.from_onebot_event(event, bot)`：QQ 事件派生（兼容桥）
- `CommandContext.from_platform_message(msg, bot)`：Discord 等平台派生
- `ctx.reply(message)`：按平台发送（群发/私发）

### 2.4 matcher 平台分发（`core/managers/command_manager.py`）

新增平台感知注册与分发：

```python
@matcher.platform_command("qq", "mcc")          # QQ 平台的指令
async def handle_mcc_command(bot, event, args): ...

@matcher.platform_command("discord", "dcmd")    # Discord 平台的指令
async def handle_dcmd(bot, event, args): ...

@matcher.platform_message("discord", priority=1)  # Discord 通用消息处理器
async def on_dc(event): ...
```

- `matcher.handle_platform_event(ctx)`：平台感知分发入口（Discord 调用）
- QQ 事件流里有一条**平台指令桥**：旧指令没匹配时，把 OneBot 事件转成
  `CommandContext` 再分发 `platform_commands["qq"]`（mcc/ag 已迁移至此）。

### 2.5 CrossPlatformForwarder（`plugins/discord_cross/forwarder.py`）

跨平台转发的唯一决策点：

- 映射：`CROSS_PLATFORM_MAP`（QQ 群 ↔ Discord 频道）
- 去重：TTL 30s，`(平台, 频道, 内容哈希)` 命中则跳过
- 防环：Discord→QQ 发送带 `_no_mirror=True`（不触发 QQ→DC）；Discord 适配器忽略
  自身 bot 消息；发送层只上报、不转发
- 入口：
  - `forward_qq_to_discord` / `forward_discord_to_qq`：用户消息
  - `notify_qq_sent` / `notify_discord_sent`：机器人发送后上报

转发器订阅消息总线（`on_incoming("qq")` / `on_incoming("discord")`），
用户消息由总线驱动转发。

## 3. 数据流

### 3.1 QQ 用户消息 → Discord

```
QQ 群消息 → MessageHandler.handle（OneBot 事件分发）
  └─ discord_cross/handlers.handle_qq_group_message
       └─ 发布 PlatformMessage(qq) 到 message_bus
            └─ forwarder._bus_qq_incoming → forward_qq_to_discord（去重）
                 └─ sender.forward_qq_to_discord → Redis → DiscordAdapter 发送
```

### 3.2 Discord 用户消息 → QQ

```
Discord on_message → PlatformMessage(discord) → message_bus.publish_incoming
  ├─ forwarder._bus_discord_incoming → forward_discord_to_qq（去重）→ QQ（_no_mirror）
  └─ matcher.handle_platform_event(ctx) → 平台感知指令/处理器
```

### 3.3 机器人消息跨平台可见

- 机器人在 QQ 群回复 → `ws.call_api` 钩子 → `forwarder.notify_qq_sent` → Discord
- 机器人在 Discord 回复 → `send_discord_message` 后 → `forwarder.notify_discord_sent` → QQ

两者都经过同一套去重/防环。

## 4. 迁移状态

### 已完成

| 阶段 | 内容 | 位置 |
|---|---|---|
| 1 | 三处镜像收敛为转发器 + 统一去重防环 + 发送层去副作用 | `forwarder.py`、`ws.py`、`router.py` |
| 2 | 平台无关消息层（PlatformMessage / MessageBus / CommandContext） | `core/messaging/` |
| 2 | matcher 平台感知分发 + QQ 平台指令桥 | `command_manager.py`、`event_handler.py` |
| 2 | mcc 插件迁移到平台指令（`/mcc`、`/ag` 注册于 `platform_commands["qq"]`） | `plugins/mcc.py` |
| 3 | Discord 停止伪造 OneBot 事件；`create_mock_event` / `handle_discord_message_event` 删除 | `discord_adapter.py`、`router.py`、`handlers.py` |
| 3 | Discord 入站走消息总线 + CommandContext 平台分发 | `discord_adapter.py` |
| 3 | 全部插件迁移到平台感知注册（`platform_command("qq")` / `platform_message("qq")`） | 见下表 |

### 待办 / 后续

- QQ→DC 的发送仍走 Redis（`neobot_discord_send`）；可进一步收敛为总线出站
- `MessageHandler` 保留旧注册 API（`commands` / `message_handlers`）作为兼容，
  新插件一律使用平台注册
- 已迁移插件当前全部声明为 `qq` 平台（行为与迁移前一致）；需要支持 Discord 的
  插件可在注册时追加 `"discord"` 平台（函数体不变，因 CommandContext 属性兼容）

### 插件迁移清单

| 插件 | 注册 | 备注 |
|---|---|---|
| mcc（/mcc、/ag） | `platform_command(["qq","discord"])` | QQ 群路由/私聊假人；Discord 上仅申请/查询类可用 |
| echo、furry、thpic、weather、jrcd、bot_status、github_parser、web_parser、mirror_avatar、code_py、broadcast、twitter_parser、jinman_parser、osu! | `platform_command(["qq","discord"])` | 双平台，行为在 QQ 不变 |
| discord_cross（cross_config、cross_reload） | `platform_command(["qq","discord"])` | 管理命令 |
| discord_cross（handle_qq_group_message） | `platform_message("qq")` | **仅 QQ**（Discord 入站走总线，避免环路） |
| 自动触发类（web_parser、twitter、mirror_avatar、code_py、broadcast 的多步捕获） | `platform_message(["qq","discord"])` | 双平台状态机/捕获，入参为 CommandContext |

其余插件（admin、auto_approve、group_welcome 等）基于 notice/request/启动钩子，
不涉及消息分发，无需迁移。

平台差异说明（Discord 侧均为降级行为，不崩溃）：

- QQ 专有 API（`call_api`、`get_stranger_info`、`get_group_list` 等）在 Discord 包装器上不存在，
  相关插件已用 `hasattr` / try-except 兜底（如 mirror_avatar 的 `can_send_image`、twitter 的表情回应）
- Discord 回复图片/文件时，URL 会以文本形式发送（QQ 侧为真实图片）
- `/mcc` 的群路由（按 QQ 群）在 Discord 上不生效，仅 `申请挂机` / `租赁状态` 等通用子命令可用

## 5. 插件迁移指南

**新插件（Discord 可用）**：

```python
from neobot.core.managers.command_manager import matcher

@matcher.platform_command("discord", "示例")
async def example(bot, event, args):
    await event.reply("来自 Discord 的指令")
```

**旧插件从 OneBot 事件迁移**：

1. 函数签名保持 `(bot, event, args)`，把 `@matcher.command(...)` 换成
   `@matcher.platform_command("qq", ...)`（QQ 行为不变，事件参数实际是 CommandContext）
2. 若需支持 Discord，再加一个 `platform_command("discord", ...)` 注册（同一函数体）
3. 不要依赖 `event.bot.call_api(...)`（QQ Bot 有，Discord 包装器没有）；
   跨平台发送用 `event.reply` 或消息总线

**约定清单**：

- 发送函数不得直接转发到另一端，应调用 `forwarder.notify_*` 或发布到总线
- 转发一律走 `CrossPlatformForwarder`（去重/防环内置），不要另起炉灶
- Discord 消息不会进入 OneBot 事件分发——需要响应 Discord 的插件必须声明平台
