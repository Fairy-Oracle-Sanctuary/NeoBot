# 项目结构

项目采用 `src` 布局：真正的 Python 包位于 `src/neobot/`，根目录的 `main.py`
在启动时把 `src` 加入 `sys.path`，因此包内一律使用 `neobot.*` 绝对导入。

## 根目录

```
.
├── src/neobot/            # 核心 Python 包（见下文）
├── docs/                  # 部署 / 安全 / 性能 / 适配器架构文档
├── scripts/               # 辅助脚本（compile_machine_code.py / export_requirements.py ...）
├── main.py                # 启动入口
├── cli.py                 # CLI 适配器入口
├── config.toml            # 配置文件（含敏感信息，不入库）
├── config.example.toml    # 配置模板（首次启动自动复制为 config.toml）
├── requirements.txt       # 运行时依赖
├── Dockerfile             # Docker 镜像定义
├── docker-compose.yml     # Docker 编排
├── sandbox.Dockerfile     # 代码沙箱镜像定义
└── README.md              # 项目说明
```

## 核心包结构

```
src/neobot/
├── core/                  # 框架核心（非请勿动）
│   ├── api/               # OneBot v11 API 封装（account/base/friend/group/media/message）
│   ├── data/              # 权限数据文件（admin.json / permissions.json）
│   ├── handlers/          # 事件处理器（MessageHandler / NoticeHandler / RequestHandler）
│   ├── managers/          # 管理器（command / permission / redis / mysql / plugin / browser /
│   │                      #   image / reverse_ws / thread / bot）
│   ├── messaging/         # 平台无关消息层（PlatformMessage / MessageBus / CommandContext）
│   ├── services/          # 服务层（local_file_server 本地文件服务器）
│   ├── utils/             # 工具（logger / exceptions / input_validator / env_loader /
│   │                      #   error_codes / executor / singleton / performance）
│   ├── bot.py             # Bot 实例（继承各 API Mixin，封装合并转发等高级方法）
│   ├── config_loader.py   # 配置加载（global_config）
│   ├── config_models.py   # Pydantic 配置模型
│   ├── permission.py      # 权限枚举（USER / OP / ADMIN）
│   ├── plugin.py          # 插件基类（Plugin / SimplePlugin）
│   └── ws.py              # WebSocket 通信层
├── models/                # 数据模型
│   ├── events/            # OneBot 事件模型（base/message/notice/request/factory）
│   ├── message.py         # 消息段模型（MessageSegment）
│   ├── objects.py         # API 响应对象（GroupInfo / StrangerInfo 等）
│   └── sender.py          # 发送者信息
├── adapters/              # 平台适配器
│   ├── discord_adapter.py # Discord 适配器（平台收发，不伪造 OneBot 事件）
│   ├── cli_adapter.py     # CLI 适配器
│   ├── router.py          # 平台路由
│   └── mcc_adapter/       # MCC 服务适配器（adapter / mcp_client / service_client）
├── plugins/               # 插件目录，业务逻辑都在这里
│   ├── admin.py           # 权限管理
│   ├── auto_approve.py    # 自动同意好友/群请求
│   ├── bot_status.py      # Bot 状态查询（图片）
│   ├── broadcast.py       # 管理员广播
│   ├── code_py.py         # Python 代码沙箱执行（Docker）
│   ├── discord_cross/     # Discord 跨平台转发（forwarder / sender / subscription / translator ...）
│   ├── echo.py            # Echo / 点赞
│   ├── furry.py           # Furry 图片
│   ├── github_parser.py   # GitHub 链接解析
│   ├── group_welcome.py   # 群欢迎
│   ├── jrcd.py            # 今日人品 / 长度查询
│   ├── mcc*.py            # MCC 相关（mcc / mcc_agent / mcc_listener / mcc_map / mcc_memory / mcc_afk_data）
│   ├── mirror_avatar.py   # 头像镜像
│   ├── thpic.py           # 东方 Project 随机图片
│   ├── twitter_parser.py  # Twitter/X 链接解析
│   ├── weather.py         # 天气查询
│   ├── web_parser/        # Web 链接解析系统（bili / douyin / github）
│   ├── Greek_alphabet/    # 希腊字母表
│   ├── osu!_plugin/       # osu! 谱面难度评估（ts_oma node bridge）
│   └── resource/          # 静态资源（city_code.py / help.png）
├── templates/             # Jinja2 模板（help / weather / status / code_execution ...）
├── tests/                 # 单元测试与集成测试
├── docs/                  # 开发文档（本目录）
├── web_static/            # 静态网页文件
└── data/                  # 数据存储目录
```

## 核心目录说明

### core/

框架核心代码：

- **api/**: OneBot API 封装（message / group / friend / account / media / base）
- **handlers/**: 事件处理器，命令与消息分发核心
- **managers/**: 各种管理器（单例，见 [核心管理器](core-concepts/singleton-managers.md)）
- **messaging/**: 平台无关消息层，跨平台转发的基石（见 [适配器架构](./adapter-architecture.md)）
- **services/**: 服务层（本地文件服务器等）
- **utils/**: 工具函数

### models/

数据模型定义：

- **events/**: OneBot 事件模型（MessageEvent / GroupMessageEvent / NoticeEvent / RequestEvent 等）
- **message.py**: `MessageSegment` 消息段模型
- **objects.py**: API 响应对象
- **sender.py**: 发送者信息

### plugins/

插件目录，所有业务逻辑都在这里。插件开发请参考 [插件开发文档](plugin-development/index.md)。

### tests/

单元测试和集成测试文件，覆盖 API / 事件 / 配置 / 权限 / 线程池 / Redis 等模块。

## 导入路径

所有代码使用绝对导入，格式为 `neobot.{module}.{submodule}`。

例如：

```python
from neobot.core.managers import plugin_manager, matcher, permission_manager
from neobot.models import MessageSegment, MessageEvent, OneBotEvent
from neobot.core.permission import Permission
```

## 新增模块

1. 在对应目录下创建模块文件
2. 若需对外暴露，在 `__init__.py` 中导出
3. 使用 `neobot.*` 绝对导入引用新模块
