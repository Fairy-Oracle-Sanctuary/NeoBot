# Redis 原子操作与数据一致性

## 概述

NEO Bot 的权限管理系统采用了文件为主、Redis 为辅的架构设计，确保数据可靠性和高性能访问的平衡。为了保证数据一致性，系统在所有写操作中都实现了原子操作机制。

## 设计理念

### 以文件为权威数据源

- **主数据源**: `neobot/core/data/permissions.json` 作为权限数据的权威来源
- **缓存层**: Redis 作为高速缓存，提供快速访问能力
- **一致性保障**: 所有写操作都以文件为准，再同步到 Redis

### 原子操作实现

所有权限管理的写操作都遵循以下原子操作模式：

1. **读取当前状态**: 从 `permissions.json` 读取当前数据
2. **内存中修改**: 在内存中完成数据修改
3. **原子写入**: 使用临时文件 + 原子重命名的方式写入磁盘
4. **缓存同步**: 将修改同步到 Redis 缓存

## 核心实现细节

### 原子文件写入

```python
# 原子写入操作示例
temp_file = self.data_file + ".tmp"
with open(temp_file, "w", encoding="utf-8") as f:
    f.write(json.dumps(data, indent=2, ensure_ascii=False))
os.replace(temp_file, self.data_file)  # 原子操作
```

- 使用临时文件避免写入过程中数据损坏
- `os.replace()` 确保操作的原子性
- 即使在写入过程中断电，也不会破坏原文件

### Redis 同步机制

```python
# 同步文件内容到 Redis
async def _sync_file_to_redis(self):
    # 清空 Redis 中的现有数据
    await redis_manager.redis.delete(self._REDIS_KEY)
    await redis_manager.redis.delete(self._REDIS_ADMINS_KEY)
    
    # 从文件加载数据并同步到 Redis
    # ...
```

- 使用 Redis 管道操作提高批量写入效率
- 确保 Redis 与文件数据的一致性

## 支持的操作

### 权限管理操作

- `set_user_permission()`: 设置用户权限
- `remove_user()`: 移除用户权限
- `add_admin()`: 添加管理员
- `remove_admin()`: 移除管理员
- `clear_all()`: 清空所有权限

### 数据隔离

- 普通权限存储在 Redis Hash (`neobot:permissions`) 中
- 管理员列表存储在 Redis Set (`neobot:admins`) 中
- 避免数据冲突，提高查询效率

## 性能优化

### 读取优化

- 读取操作直接从 Redis 缓存获取，毫秒级响应
- 减少磁盘 I/O，提升系统性能

### 批量操作

- 使用 Redis 管道进行批量操作
- 减少网络往返次数，提高吞吐量

## 错误处理

### 异常恢复

- 文件写入失败时，保留原数据不丢失
- Redis 操作失败时，不影响文件数据
- 提供详细的错误日志便于排查

### 数据校验

- 写入前校验数据格式
- 防止非法数据进入系统

## 最佳实践

### 插件开发建议

```python
# 在插件中使用权限管理器
from neobot.core.managers.permission_manager import permission_manager
from neobot.core.permission import Permission

# 查询权限
user_perm = await permission_manager.get_user_permission(user_id)

# 检查权限
if await permission_manager.check_permission(user_id, Permission.ADMIN):
    # 执行管理员操作
    pass
```

### 高并发场景

- 系统设计支持高并发读取
- 写操作频率较低，适合权限管理场景
- Redis 缓存有效缓解数据库压力

## 故障恢复

### Redis 故障

- Redis 不可用时，系统仍可通过文件数据提供服务
- Redis 恢复后，自动从文件同步最新数据

### 文件损坏

- 系统定期备份权限数据
- 可从历史备份中恢复数据

## 总结

通过以文件为权威数据源、Redis 为缓存层的设计，结合原子操作机制，NEO Bot 的权限管理系统在保证数据可靠性的同时，提供了高性能的访问能力。这种设计既满足了数据一致性的要求，又兼顾了系统性能的需求。

## 扩展应用：指令调用统计

除了权限管理，原子操作的思想也应用在了指令调用统计中，但实现方式更为高效。

### 痛点
如果每次调用指令都执行 `GET` -> `(本地+1)` -> `SET` 的流程，在高并发下会产生“竞争条件”（Race Condition），导致计数不准确。例如，两个请求同时读取到计数值 10，各自加一后都写回 11，而正确的结果应该是 12。

### 解决方案：Lua 脚本
`NeoBot` 使用 Redis 的 `EVAL` 命令执行一个 Lua 脚本来实现原子化的计数器。

```lua
-- Lua 脚本 (简化版)
local current = redis.call('HGET', KEYS[1], ARGV[1])
local count = tonumber(current) or 0
count = count + 1
redis.call('HSET', KEYS[1], ARGV[1], count)
return count
```

- **原子性**: Redis 会保证整个 Lua 脚本的执行是原子性的，执行期间不会被其他命令打断。
- **高效性**: 将多个操作（读取、计算、写入）在 Redis 服务器端一次性完成，减少了网络往返的开销。

### 核心实现
在 `RedisManager` 中，我们封装了 `execute_lua_script` 方法，使得在 Python 中调用 Lua 脚本变得非常简单。它接收 Lua 脚本字符串，内部通过 `register_script` 缓存脚本并执行：

```python
# Python 调用示例
lua_script = """
local current = redis.call('HGET', KEYS[1], ARGV[1])
local count = tonumber(current) or 0
count = count + 1
redis.call('HSET', KEYS[1], ARGV[1], count)
return count
"""

count = await redis_manager.execute_lua_script(
    lua_script,
    keys=["neobot:stats:command_usage"],
    args=[command_name]
)
```

### 收益
- **数据准确性**: 彻底杜绝了高并发下的计数错误问题。
- **高性能**: 相比于传统的“读取-修改-写入”模式，使用 Lua 脚本能显著提升性能，特别是在指令调用这种高频场景下。
- **可扩展性**: 这种模式可以轻松应用于其他需要原子操作的场景，如频率限制、资源池管理等。
