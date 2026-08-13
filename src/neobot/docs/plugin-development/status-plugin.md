# 插件详解：`/status` 状态监控

`/status` 是 `NeoBot` 内置的一个强大插件，它能让你实时了解机器人的运行状态、性能指标和指令调用情况。这不仅是一个酷炫的功能，更是一个重要的运维工具。

## 功能概览

发送 `/status` 指令后，机器人会返回一张精心设计的状态图，包含以下核心信息：

1.  **系统信息**:
    *   **CPU 使用率**: 当前服务器的 CPU 负载情况。
    *   **内存占用**: 机器人进程占用了多少物理内存。
    *   **磁盘空间**: 服务器磁盘的使用情况。

2.  **机器人核心指标**:
    *   **启动时间**: 机器人本次运行了多久。
    *   **连接状态**: 与 OneBot 客户端的连接是否正常。
    *   **消息收发**: 接收和发送了多少条消息。

3.  **指令调用统计**:
    *   **总调用次数**: 所有指令一共被调用了多少次。
    *   **热门指令**: 哪些指令被使用的频率最高。

4.  **版本信息**:
    *   **框架版本**: `NeoBot` 的版本号。
    *   **客户端信息**: 连接的 OneBot 客户端名称和版本（如 NapCatQQ）。

## 实现技术

这个插件综合运用了 `NeoBot` 框架的多种核心能力：

-   **系统监控 (`psutil`)**: 通过 `psutil` 库获取实时的系统性能数据。
-   **原子化统计 (`Redis + Lua`)**: 指令调用次数通过 Redis 的 Lua 脚本进行原子化递增，保证高并发下的数据准确性。
-   **异步任务**: 启动时间、消息计数等信息在后台通过异步任务持续更新。
-   **动态 HTML 渲染 (`Jinja2`)**: 状态信息被注入到一个 HTML 模板中。
-   **网页截图 (`Playwright`)**: 渲染好的 HTML 页面通过 Playwright 的页面池进行截图，生成最终的状态图片。

## 如何使用

直接在与机器人聊天的任何地方（私聊或群聊）发送：

```
/status
```

机器人会处理几秒钟（主要是截图耗时），然后将状态图片发送给你。

## 自定义与扩展

想在状态图中添加你自己的信息？很简单！

1.  **找到插件文件**: `src/neobot/plugins/bot_status.py`。
2.  **修改数据收集函数**: 状态数据由 `handle_status` 汇总以下函数的结果：
    - `_get_system_info()`：CPU / 内存 / 磁盘等系统指标
    - `_get_bot_info(bot, start_time)`：机器人运行时长与连接状态
    - `_get_stats(redis_manager)`：消息收发与指令调用统计
    - `_get_version_info(bot)`：框架与客户端版本

    你可以在 `handle_status` 中追加自己的数据源，或新增一个收集函数并合并进
    传入模板的 `status_data` 字典：

    ```python
    # src/neobot/plugins/bot_status.py（节选）

    async def _get_my_extra_data():
        return {
            "custom_metric": await get_my_metric(),
            "plugin_version": "1.2.3"
        }
    ```
3.  **修改 HTML 模板**: `src/neobot/templates/status.html`。
    在这个文件中，你可以用 Jinja2 的语法把你刚刚添加的数据展示出来。
    ```html
    <!-- templates/status.html -->

    <!-- ... 已有的代码 ... -->

    <div class="card">
        <h2>我的插件状态</h2>
        <p>自定义指标: {{ custom_metric }}</p>
        <p>插件版本: {{ plugin_version }}</p>
    </div>
    ```

通过这种方式，你可以轻松地将 `/status` 打造成一个专属于你的、功能更加丰富的机器人仪表盘。
