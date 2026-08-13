# 核心概念：单例管理器

`core/managers/` 这地方，放的都是些**管事的**。它们是 NEO Bot 的核心。梨花飘落在你窗前。。。

## 为啥是单例？

就是**全局独一份**。

*   **到处都能用**: 在插件里 `import` 就行，不用传来传去。
*   **数据不打架**: 权限、命令这些东西，全局就一份，改了都认。
*   **省资源**: Redis 连接池、浏览器这种东西，开一个就够了，多了浪费。

我专门在 `core/utils/singleton.py` 搞了个基类，继承一下就行，你会的，加油。。。

## 认识一下

### 1. `CommandManager` (`matcher`)

*   **怎么找**: `from neobot.core.managers.command_manager import matcher`
*   **管啥**:
    *   **总调度**: 所有消息都得从它这过一遍
    *   **发牌的**: 你用的 `@matcher.command()` 这种装饰器，就是它发的。
    *   **对号入座**: 消息来了，它负责对一下，看是哪个插件的。

写插件天天都得跟它打交道。

### 2. `PermissionManager` (`permission_manager`)

*   **怎么找**: `from neobot.core.managers.permission_manager import permission_manager`
*   **管啥**:
    *   **划分三六九等**: `ADMIN`, `OP`, `USER` 这些等级都是它定的。
    *   **管理权限**: 谁有啥权限，都记在 `core/data/permissions.json` 里。
    *   **管理员管理**: 超级管理员的增删改查也在这里，统一管理。
    *   **双重存储**: 普通权限存储在 Redis Hash 中，管理员列表存储在 Redis Set 中。
    *   **原子操作**: 所有写操作都采用原子操作，确保数据一致性。详见 [Redis 原子操作与数据一致性](./redis-atomic-operations.md)

### 4. `PluginManager`

*   **管啥**:
    *   **拉人头**: 启动时把 `plugins/` 目录下的插件都拉进来。
    *   **热更新**: 你改了插件代码，它负责重载，不用重启机器人。

这一般在幕后，你基本不用找它。

### 5. `RedisManager` (`redis_manager`)

*   **怎么找**: `from neobot.core.managers.redis_manager import redis_manager`
*   **管啥**:
    *   **接线员**: 管着和 Redis 的连接。
    *   **提供工具**: 你要用 Redis，就找 `redis_manager.redis`。

### 6. `BrowserManager` (`browser_manager`)

*   **怎么找**: `from neobot.core.managers.browser_manager import browser_manager`
*   **管啥**:
    *   **浏览器**: 负责启动和关闭 Playwright。
    *   **页面池**: 提前准备好几个空白页面（默认3个），你要用直接拿
    *   **循环利用**: 用完记得还回来 (`release_page`)

### 7. `ImageManager` (`image_manager`)

*   **怎么找**: `from neobot.core.managers.image_manager import image_manager`
*   **管啥**:
    *   **美工**: 把数据塞进网页模板
    *   **记性好**: 模板用一次就记住，下次直接用缓存。
    *   **自动借还**: 它会自动找 `BrowserManager` 借页面，你只管 `render_template` 就行。

### 8. `BotManager` (`bot_manager`)

*   **怎么找**: `from neobot.core.managers.bot_manager import bot_manager`
*   **管啥**:
    *   **Bot 实例管理**: 统一管理 Bot 实例，方便在任何地方获取当前运行的 Bot。
    *   **生命周期**: 协助管理 Bot 的启动和关闭流程。

### 9. `MysqlManager` (`mysql_manager`)

*   **怎么找**: `from neobot.core.managers.mysql_manager import mysql_manager`
*   **管啥**:
    *   **数据库连接**: 管理与 MySQL 数据库的异步连接池。
    *   **数据持久化**: 提供执行 SQL 语句的接口，用于需要长期保存的数据。

### 10. `ReverseWsManager` (`reverse_ws_manager`)

*   **怎么找**: `from neobot.core.managers.reverse_ws_manager import reverse_ws_manager`
*   **管啥**:
    *   **反向 WS 服务**: 启动并管理反向 WebSocket 服务器，允许 OneBot 客户端主动连接 Bot。
    *   **连接管理**: 处理客户端的连接、断开和消息接收。

### 11. `ThreadManager` (`thread_manager`)

*   **怎么找**: `from neobot.core.managers.thread_manager import thread_manager`
*   **管啥**:
    *   **线程池管理**: 提供全局的线程池执行器，用于执行阻塞的同步任务。
    *   **异步桥接**: 方便地将同步函数转换为异步调用，避免阻塞事件循环。

## 咋用？

`import`

**例子**: 查查这人是不是op

```python
# plugins/my_plugin.py

from neobot.core.managers.command_manager import matcher
from neobot.core.managers.permission_manager import permission_manager
from neobot.core.permission import Permission
from neobot.models import MessageEvent

@matcher.command("secret")
async def secret_command(event: MessageEvent):
    # 只有管理员能看
    is_admin = await permission_manager.check_permission(event.user_id, Permission.ADMIN)
    if is_admin:
        await event.reply("这是秘密！")
    else:
        await event.reply("你没权限看这个。")
```
