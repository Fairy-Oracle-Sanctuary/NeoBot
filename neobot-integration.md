# neobot 对接说明

mcc-service 已改造：QQ 不再直接操控假人，所有假人操作统一在浏览器进行。
neobot 只保留两项职责：

1. **签发登录密钥**（用户私聊 bot「登录」→ neobot 调 issue 接口 → 私聊返回 login_token）
2. **只读 agent 查询服务器消息**（转发到群里）

---

## 一、签发登录密钥（issue 接口）

用户在网页输入 QQ 号后，需私聊 neobot 发送「登录」验证 QQ 归属。neobot 调用 mcc-service 的 issue 接口签发一次性 login_token，私聊发给用户。用户在网页输入 login_token 换取 session_token 完成登录。

### 流程

```
用户在网页输入 QQ 号 → 网页提示「请私聊机器人发送：登录」
   ↓
用户私聊 neobot 发送：登录
   ↓
neobot 调用 POST /api/auth/issue（带 panel_token 鉴权）
   请求体：{"qq": "<私聊者QQ>"}
   ↓
mcc-service 生成一次性 login_token（5 分钟有效）
   ↓
返回 login_token
   ↓
neobot 把 login_token 私聊发给用户，提示在网站输入完成登录
```

### 接口

**POST** `/api/auth/issue`（仅 `127.0.0.1:8800`，公网 8801 返回 404）

鉴权：`Authorization: Bearer <panel_token>`（即 config.toml `[service] panel_token`）

请求体：
```json
{"qq": "10001"}
```

成功响应：
```json
{
  "success": true,
  "login_token": "<一次性token，私聊下发，勿明文入库>",
  "expires_in": 300
}
```

失败响应：
```json
{"success": false, "message": "qq 必须是 4~15 位数字"}
```

特性：
- **一次性**：login_token 换过 session_token 后即失效
- **TTL**：5 分钟
- login_token 由用户在网页 `POST /api/auth/verify` 输入换取 session_token

### neobot 私聊命令

```
登录
```

neobot 处理逻辑（伪代码）：

```python
# 私聊消息
if msg.strip() == "登录":
    qq = str(user_id)  # 私聊者的 QQ
    resp = httpx.post(
        f"{MCC_API}/api/auth/issue",
        headers={"Authorization": f"Bearer {PANEL_TOKEN}"},
        json={"qq": qq},
        timeout=5,
    )
    data = resp.json()
    if data["success"]:
        reply = (
            f"登录密钥：{data['login_token']}\n"
            f"有效期：{data['expires_in']//60} 分钟\n"
            f"请前往 https://bot.wanfeng.cyou 输入此密钥完成登录"
        )
    else:
        reply = f"签发失败：{data['message']}"
    send_private_msg(user_id, reply)
```

> 注意：neobot 必须用私聊者的真实 QQ 号调用 issue，mcc-service 以此作为 QQ 归属验证。login_token 私聊发给用户后，用户自行在网页输入。

---

## 二、只读 agent 查询服务器消息

agent 现在只读，只能查询服务器状态，不能操控假人。仅绑定 `public` 实例。

### 接口

**POST** `/api/instances/public/agent`（仅 `127.0.0.1:8800`，公网 8801 返回 404）

鉴权：`Authorization: Bearer <auth_token>`（即 config.toml `[service] auth_token`，管理员 token）

请求体：
```json
{
  "task": "看看服务器有多少人在线",
  "caller": {"qq": "10001", "group_id": "910144523", "name": "晚风"}
}
```

响应：
```json
{"success": true, "reply": "当前在线 12 人：晚风、K2CrO4__、..."}
```

### agent 能力（只读）

- 查询在线玩家、聊天记录、服务器 TPS/MSPT
- 查询会话状态、挂机点目录
- 查询长期记忆
- 查询 MCnnyy2 Wiki（只读）
- 查询实时地图（玩家坐标、区域、标记）
- 查询租赁状态

agent **不能**：发消息、移动、攻击、传送、调用任意 MCP 工具、写 Wiki、申请租用。

### neobot 群消息命令建议

```
/ag <自然语言查询>
```

neobot 转发到 agent：

```python
if msg.startswith("/ag "):
    task = msg[4:].strip()
    resp = httpx.post(
        f"{MCC_API}/api/instances/public/agent",
        headers={"Authorization": f"Bearer {AUTH_TOKEN}"},
        json={"task": task, "caller": {"qq": str(user_id), "group_id": str(group_id), "name": nickname}},
    )
    data = resp.json()
    send_group_msg(group_id, data.get("reply", "查询失败"))
```

---

## 三、/mcc 指令（QQ 操控假人）

neobot 的 `/mcc` 指令用于在 QQ 里管理**该 QQ 绑定的假人**（私有假人 + 当前租用的租赁池假人）。
mcc-service 提供三个内部接口，走 `127.0.0.1:8800` + `auth_token` 鉴权，**当前选中实例**按 QQ 存 Redis（neobot 无需自己维护状态）。

### MCC 指令用法

```
/mcc 切换实例 [序号|名称]：切换当前操作的假人（默认 1）
/mcc 状态：查看当前实例与连接状态
/mcc 聊天 <文本>：在服务器发送一条聊天
/mcc 命令 <MCC内部命令>：执行 MCC 内部命令（如 respawn）
/mcc 会话 | 服务器 | 玩家 | 性能：查询服务器状态
/mcc 历史 [n] | 事件 [n]：查询聊天记录/事件
/mcc 标记 [关键词] | 区域：查询实时地图标记/区域
/mcc 挂机 [组名|挂机点]：查看挂机点菜单或传送
/mcc agent <需求>：自然语言操控当前实例
/mcc 记忆 查看 | 保存 <内容> | 清空动态：管理长期记忆（管理员）
/mcc 申请挂机 | 租赁状态：租赁相关信息

提示：/mcc 仅能管理该 QQ 绑定的实例；先用 /mcc 切换实例 选择假人
```

### 接口总览

| 接口 | 方法 | 说明 |
|------|------|------|
| `/api/mcc/instances?qq=<qq>` | GET | 列出该 QQ 可管理假人 + 当前选中 |
| `/api/mcc/select` | POST | 切换当前假人（`/mcc 切换实例`） |
| `/api/mcc/exec` | POST | 在当前假人上执行 `/mcc` 子命令 |

统一约定：
- **地址**：`http://127.0.0.1:8800`（内部端口，公网 8801 不可见）
- **鉴权**：`Authorization: Bearer <auth_token>`
- **QQ 传参**：neobot 用 auth_token 时 `request['qq']='admin'`，**真实操作者 QQ 由 body/query 传入**（`qq` 字段，4~15 位数字）

### 1. 列出可管理假人

**GET** `/api/mcc/instances?qq=<qq>`

鉴权：`Authorization: Bearer <auth_token>`

响应：
```json
{
  "success": true,
  "current": "fake3",
  "instances": [
    {
      "name": "fake3",
      "display": "晚风的小号",
      "type": "microsoft",
      "private": true,
      "running": true,
      "current": true
    },
    {
      "name": "bot02",
      "display": "bot02",
      "type": "offline",
      "private": false,
      "rentable": true,
      "running": true,
      "expires_at": 1786000000,
      "current": false
    }
  ]
}
```

字段说明：
- `current`：当前选中的假人名（顶层），`null` 表示未选
- `instances[].current`：该条是否为当前选中
- `private`：是否私有假人；`rentable` 表示租赁池假人
- `running`：MCC 进程是否在运行
- `expires_at`：租赁到期时间戳（仅租赁池假人）

### 2. 切换当前假人

**POST** `/api/mcc/select`

请求体：
```json
{
  "qq": "10001",
  "index": 1
}
```

也可用名称切换：
```json
{
  "qq": "10001",
  "name": "fake3"
}
```

- 不传 `name` 和 `index` → 默认选第 1 个
- `index` 从 1 开始，对应 `/api/mcc/instances` 返回的列表顺序

响应：
```json
{
  "success": true,
  "message": "已切换到 晚风的小号",
  "current": "fake3",
  "instance": { "name": "fake3", "display": "晚风的小号", "...": "...", "current": true },
  "running": true,
  "runtime_detail": {}
}
```

### 3. 执行 /mcc 子命令

**POST** `/api/mcc/exec`

请求体：
```json
{
  "qq": "10001",
  "cmd": "聊天",
  "text": "大家好",
  "args": ["大家好"]
}
```

- `cmd`：子命令名（中文，见下表）
- `args`：位置参数列表（可选，部分命令也支持具名字段）
- `instance`：可选，覆盖当前选中实例（不传则用 `/mcc 切换实例` 选中的）

#### 子命令映射表

| /mcc 子命令 | `cmd` | 额外字段 | 说明 |
|---|---|---|---|
| `切换实例 [序号\|名称]` | `切换实例` | `index`/`name` | 走 select 逻辑，返回切换结果 |
| `状态` / `会话` | `状态` / `会话` | - | 会话与连接状态 |
| `聊天 <文本>` | `聊天` | `text` 或 `args[0]` | 发送聊天 |
| `命令 <MCC命令>` | `命令` | `command` 或 `args[0]` | 执行 MCC 内部命令 |
| `服务器` | `服务器` | - | 服务器信息 |
| `玩家` | `玩家` | - | 在线玩家 |
| `性能` | `性能` | - | TPS/MSPT/视距 |
| `历史 [n]` | `历史` | `args[0]=n` | 聊天记录，默认 50 条 |
| `事件 [n]` | `事件` | `args[0]=n` | 事件记录，默认 50 条 |
| `标记 [关键词]` | `标记` | `args[0]=keyword` | 实时地图标记 |
| `区域` | `区域` | - | 实时地图区域 |
| `挂机 [组名\|挂机点]` | `挂机` | `args[0]=query` | 无参数看菜单，有参数传送 |
| `agent <需求>` | `agent` | `task` 或 `args[0]` | 自然语言操控（可读可写） |
| `记忆 查看` | `记忆` | `args[0]=查看` | 查看长期记忆 |
| `记忆 保存 <内容>` | `记忆` | `args[0]=保存`, `content`/`args[1]`, `topic?` | 保存记忆 |
| `记忆 清空动态` | `记忆` | `args[0]=清空动态` | 清空动态事实 |
| `申请挂机` | `申请挂机` | `game_name`/`purpose`/`duration_minutes?` | 借用假人 |
| `租赁状态` | `租赁状态` | - | 查看自己的租赁 |
| `释放` | `释放` | - | 释放当前租用 |

响应格式因命令而异，统一含 `success` 字段：
- 文本类命令：`{"success": true, "text": "..."}`
- 操作类命令：`{"success": true, "message": "..."}`
- 查询类命令：返回结构化数据（如 `players`、`history` 等）

#### 各子命令返回字段

**`切换实例`**（走 select 逻辑）
```json
{
  "success": true,
  "message": "已切换到 晚风的小号",
  "current": "fake3",
  "instance": { "name": "fake3", "display": "晚风的小号", "type": "microsoft",
                "private": true, "running": true, "current": true },
  "running": true,
  "runtime_detail": {}
}
```

**`状态` / `会话`** → `tools.session_status()`（MCC 原样）
```json
{ "success": true, "data": { "connected": true, "username": "...", "serverHost": "...", "serverPort": 25565, "...": "MCC 会话字段" } }
```
> `data` 为 MCC `mcc_session_status` 原样返回，字段以 MCC 版本为准。

**`聊天`** → `tools.send_chat()`
```json
{ "success": true, "data": { "sent": true } }
```
失败：`{ "success": false, "message": "..." }`

**`命令`** → `tools.run_internal_command()`（MCC 原样）
```json
{ "success": true, "data": { "result": "命令输出" } }
```

**`服务器`** → `tools.server_info()`（MCC 原样）
```json
{ "success": true, "data": { "host": "...", "port": 25565, "version": "...", "tps": 19.8, "...": "..." } }
```

**`玩家`** → `tools.players_list()`（MCC 原样）
```json
{ "success": true, "data": { "players": [ {"name": "晚风", "uuid": "..."}, ... ] } }
```

**`性能`** → `tools.query_performance()`（高层封装）
```json
// 来源 1：实时地图
{ "success": true, "data": { "source": "map", "text": "TPS 19.9 / MSPT 38ms / 视距 8" } }
// 来源 2：/mspt 解析
{ "success": true, "data": { "tps": 19.8, "mspt": 38.5 } }
// 无权限时
{ "success": true, "data": { "tps": 19.8, "mspt_error": "服务器未开放 /mspt 权限..." } }
// 失败
{ "success": false, "message": "未能获取 TPS/MSPT..." }
```

**`历史 [n]`** → `tools.chat_history()`（MCC 原样）
```json
{
  "success": true,
  "data": {
    "entries": [
      { "kind": "chat", "text": "大家好", "timestampUtc": "2026-08-06T04:00:00Z" },
      { "kind": "system", "text": "晚风 加入了游戏", "timestampUtc": "..." }
    ]
  }
}
```

**`事件 [n]`** → `tools.recent_events()`（MCC 原样）
```json
{
  "success": true,
  "data": {
    "events": [ { "id": 123, "type": "player_join", "data": {...}, "timestampUtc": "..." } ]
  }
}
```

**`标记 [关键词]`** → 包装 `map_tools.markers_text()`
```json
{ "success": true, "text": "标记1：xx（100,200）/ 标记2：..." }
```

**`区域`** → 包装 `map_tools.regions_text()`
```json
{ "success": true, "text": "主城 / 交易所 / ..." }
```

**`挂机 [组名|挂机点]`**
```json
// 无参数：菜单
{ "success": true, "text": "挂机点分组：\n主城（5个）：A、B、C、D、E\n..." }
// 有参数：传送结果
{ "success": true, "text": "已传送到 主城A（/res tp main_a）" }
// 失败
{ "success": true, "text": "传送 主城A 失败：位置不安全" }
{ "success": true, "text": "未找到匹配的挂机点，请先调用 mcc_afk_list 查看目录" }
```

**`agent <需求>`** → `self.agent.run()`
```json
{ "success": true, "reply": "当前在线 12 人：晚风、..." }
```
> agent 可能较慢（30s+），neobot 需设置足够超时。

**`记忆 查看`**
```json
{
  "success": true,
  "server_memory": "服务器长期记忆文本...",
  "facts": [ {"topic": "通用", "content": "...", "time": 1786000000} ]
}
```

**`记忆 保存 <内容>`**
```json
{ "success": true, "message": "已保存动态记忆：这是记忆内容" }
```

**`记忆 清空动态`**
```json
{ "success": true, "message": "动态记忆已清空" }
```

**`申请挂机`** → `rental.apply()`
```json
{
  "success": true,
  "message": "借用成功",
  "rental": {
    "qq": "10001", "game_name": "晚风", "purpose": "挂机",
    "duration_minutes": 60, "started_at": 1786000000, "expires_at": 1786003600,
    "bot": "bot02"
  },
  "instance_name": "bot02"
}
```
失败：`{ "success": false, "message": "暂时没有空闲假人，请稍后再试" }`

**`租赁状态`** → `rental.status(qq)`
```json
{
  "success": true,
  "rental": { "qq": "10001", "bot": "bot02", "expires_at": 1786003600, "...": "..." },
  "rentals": [ { "qq": "10001", "bot": "bot02", "..." : "..." } ]
}
```
> 无借用时 `rental=null, rentals=[]`。

**`释放`** → `rental.release(qq)`
```json
{ "success": true, "message": "已释放 bot02" }
{ "success": false, "message": "该 QQ 没有有效借用" }
```

> **说明**：标注「MCC 原样」的命令，`data` 字段结构由 MCC 的 MCP 工具决定，可能随版本变化；neobot 建议直接透传 `data` 或取 `data.entries` / `data.players` 等已知字段，遇到缺失字段降级处理。

### neobot 实现示例

```python
import httpx

MCC_API = "http://127.0.0.1:8800"
AUTH_TOKEN = "f8a1d990..."  # config.toml [service] auth_token

async def handle_mcc(user_id, group_id, msg):
    """处理 /mcc 指令。msg 为去掉 /mcc 前缀的剩余文本。"""
    qq = str(user_id)
    headers = {"Authorization": f"Bearer {AUTH_TOKEN}"}
    parts = msg.strip().split(maxsplit=1)
    cmd = parts[0] if parts else "状态"
    rest = parts[1] if len(parts) > 1 else ""

    # 切换实例 / 状态 / 服务器等无参命令
    if cmd in ("切换实例", "状态", "会话", "服务器", "玩家", "性能", "区域", "租赁状态"):
        if cmd == "切换实例" and rest:
            # /mcc 切换实例 2  或  /mcc 切换实例 fake3
            body = {"qq": qq, "cmd": "切换实例"}
            if rest.isdigit():
                body["index"] = int(rest)
            else:
                body["name"] = rest
        else:
            body = {"qq": qq, "cmd": cmd}
    # 带参数的命令
    elif cmd in ("聊天", "命令", "agent", "挂机", "标记", "历史", "事件"):
        body = {"qq": qq, "cmd": cmd, "args": [rest] if rest else []}
    elif cmd == "记忆":
        sub_parts = rest.split(maxsplit=1)
        sub = sub_parts[0] if sub_parts else "查看"
        body = {"qq": qq, "cmd": "记忆", "args": [sub]}
        if sub == "保存" and len(sub_parts) > 1:
            body["content"] = sub_parts[1]
    elif cmd in ("申请挂机", "申请"):
        body = {"qq": qq, "cmd": "申请挂机", "game_name": rest}
    else:
        return f"未知 /mcc 子命令：{cmd}"

    resp = httpx.post(f"{MCC_API}/api/mcc/exec", headers=headers, json=body, timeout=30)
    data = resp.json()

    if not data.get("success"):
        return data.get("message", "操作失败")

    # 格式化返回给 QQ
    if "text" in data:
        return data["text"]
    if "reply" in data:  # agent
        return data["reply"]
    return data.get("message", "完成")


async def cmd_mcc_instances(user_id):
    """单独查列表（/mcc 无参数时展示）。"""
    qq = str(user_id)
    headers = {"Authorization": f"Bearer {AUTH_TOKEN}"}
    resp = httpx.get(f"{MCC_API}/api/mcc/instances", headers=headers,
                     params={"qq": qq}, timeout=10)
    data = resp.json()
    if not data["success"] or not data["instances"]:
        return "你当前没有可管理的假人，先用 /mcc 申请挂机"
    lines = ["可管理的假人："]
    for i, inst in enumerate(data["instances"], 1):
        mark = "★" if inst.get("current") else f"{i}"
        status = "在线" if inst.get("running") else "离线"
        lines.append(f"  {mark}. {inst['display']}（{status}）")
    cur = data.get("current")
    if cur:
        lines.append(f"当前选中：{cur}")
    else:
        lines.append("提示：/mcc 切换实例 <序号> 选择假人")
    return "\n".join(lines)
```

> **提示**：`/mcc` 无参数时建议调 `GET /api/mcc/instances` 展示列表；有参数时调 `POST /api/mcc/exec`。
> agent 子命令可能较慢（30s+），建议 neobot 设置足够超时并提示用户"思考中..."。

---

## 四、废弃接口

以下 neobot 命令已废弃：

| 旧命令 | 状态 | 替代方案 |
|--------|------|----------|
| `验证 <借用密钥>`（exchange） | 废弃 | 登录后直接在网页借用，无需二次验证 |

保留：
- `/mcc <指令>` 已恢复并增强（见第三节）
- `/ag <只读查询>` 仍可用（如"在线多少人""服务器 TPS"）
- 私聊「登录」获取登录密钥

---

## 五、配置项

neobot 需要的 token（在 mcc-service 的 config.toml）：

```toml
[service]
auth_token = "f8a1d990..."   # agent 查询用（管理员）
panel_token = "035c58f1..."  # issue 接口用（neobot 调用）
```

**token 职责**：
- `auth_token`：管理员 token，neobot 调 agent 查询服务器消息时用
- `panel_token`：neobot 调 issue 签发登录密钥时用

mcc-service 地址（neobot 必须用内部端口）：

- **内部端口 `http://127.0.0.1:8800`**：neobot 直连，注册全部路由（issue / agent / mcp / tool 等）
- 公开端口 `8801`：frp 穿透到公网，仅前端路由，**不含 issue / agent**，neobot 不要用

neobot 配置时统一用 `http://127.0.0.1:8800`。
