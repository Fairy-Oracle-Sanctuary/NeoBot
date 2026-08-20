# Calglau BOT by NEO Bot Framework

[![License: AGPL-3.0](https://img.shields.io/badge/License-AGPL--3.0-blue.svg)](https://www.gnu.org/licenses/agpl-3.0)
[![Docker Build](https://github.com/Fairy-Oracle-Sanctuary/NeoBot/actions/workflows/docker.yml/badge.svg)](https://github.com/Fairy-Oracle-Sanctuary/NeoBot/actions/workflows/docker.yml)

**Powered by NEO Bot Framework**

> ## 🚀 未来计划（Roadmap）
>
> 项目正在往**插件解耦 + 自制包管理器 + 易维护**的方向演进：
>
> - **插件系统解耦**：插件从框架核心中彻底分离，独立打包、独立版本、热插拔
> - **自制包管理器**：像 pip 一样一条命令安装 / 更新 / 卸载插件，带依赖解析与签名校验
> - **可维护性提升**：代码分层重构、测试与 CI 补强、文档体系整合
>
> 完整规划见 [ROADMAP.md](ROADMAP.md)，欢迎参与讨论。

## 开源软件使用名单

本项目基于 **AGPL-3.0** 开源（见 [LICENSE](LICENSE)）。运行过程中使用到以下开源软件与组件，在此一并致谢：

### Python 依赖（requirements.txt）

| 软件 | 用途 | 许可证 |
|---|---|---|
| aiohttp | HTTP 客户端 / 异步网络 | Apache-2.0 & MIT |
| aiomysql | MySQL 异步驱动 | MIT |
| discord.py | Discord 平台适配 | MIT |
| bilibili-api-python | B 站 API 封装 | GPL-3.0-or-later |
| cachetools | 缓存工具（TTL） | MIT |
| curl_cffi | TLS 指纹模拟（抖音逆向通道） | MIT |
| gmssl | 国密 SM3（抖音 a_bogus 签名） | BSD |
| httpx | HTTP 客户端（跨平台翻译传输层） | BSD-3-Clause |
| openai | OpenAI 兼容 SDK（跨平台翻译客户端） | Apache-2.0 |
| docker | Docker 容器管理 API | Apache-2.0 |
| Jinja2 | 模板渲染（状态图等） | BSD |
| loguru | 日志 | MIT |
| orjson | 高性能 JSON | MPL-2.0 & (Apache-2.0 OR MIT) |
| ossapi | osu! API 封装 | AGPL-3.0 |
| pillow | 图片处理 | MIT-CMU |
| playwright | 浏览器引擎（Chromium） | Apache-2.0 |
| psutil | 系统信息 | BSD-3-Clause |
| pydantic | 数据模型 / 配置校验 | MIT |
| python-dotenv | 环境变量 | BSD-3-Clause |
| redis | Redis 客户端 | MIT |
| requests | HTTP 客户端 | Apache-2.0 |
| watchdog | 文件系统监听 | Apache-2.0 |
| websockets | WebSocket（OneBot v11） | BSD-3-Clause |
| tomli | TOML 解析（Python <3.11） | MIT |

> 开发/测试依赖：pytest（MIT）、pytest-asyncio（Apache-2.0）。

### 复刻 / 参考的开源代码

| 代码 | 来源 | 许可证 |
|---|---|---|
| `douyin_abogus.py`（a_bogus 签名算法） | [JohnserfSeed/f2](https://github.com/JohnserfSeed/f2) | Apache-2.0 |
| `xhs.py`（小红书解析器，Node 版思路移植） | [LangYa466](https://github.com/LangYa466)（狼牙） | **专有软件授权**（非开源许可，见下方说明） |

> ⚠️ **小红书解析器授权说明**：`xhs.py` 移植自 LangYa466（狼牙）的 Node 版实现，该部分按**专有软件授权**分发，不属于开源许可证范畴；使用本项目时该部分仍受原作者授权条款约束，请勿将其代码另作开源分发。

### 集成的开源服务

| 服务 | 用途 | 许可证 |
|---|---|---|
| [NapCatQQ](https://github.com/NapNeko/NapCatQQ) | OneBot v11 协议实现（QQ 接入层） | 上游自定义宽松许可 |
| [JMComic-Api](https://github.com/FfmpegZZZ/JMComic-Api) | 禁漫天堂相册转 PDF（`/jmc`） | MIT |
| [FixTweet (fxtwitter)](https://github.com/FixTweet/FixTweet) | 推特/X 链接解析数据源 | 开源 API 服务 |

> **许可证兼容说明**：本项目以 AGPL-3.0 发布。AGPL-3.0 / GPL-3.0 系依赖（ossapi、bilibili-api-python）在相同或兼容许可下使用，符合各自许可要求；其他依赖均采用宽松许可，无需额外约束。完整许可文本以各上游项目为准。

---

## 项目概述

**Calglau BOT** 是一个基于 NEO Bot Framework 构建的高性能 QQ 机器人。开源免费，欢迎二次开发。

简单来说：扣一

### 核心特性

*   **模块化插件架构**：所有功能都在 `src/neobot/plugins/` 目录，开发者可轻松扩展
*   **性能优化**：
    *   **异步 IO**：`asyncio` + 连接池化管理（HTTP / Redis / 浏览器页面池）
    *   **Python 3.14 JIT（可选）**：Python 3.14 下可开启 `-X jit` 运行时编译热点代码
    *   **Mypyc AOT 编译（可选）**：`scripts/compile_machine_code.py` 可将核心模块编译为 C 扩展
*   **开发者友好**：完整的类型提示，清晰的 API 设计
*   **集成 Redis 缓存**：缓存帮助图片、权限数据、会话状态等
*   **多连接模式**：支持正向 WS（Bot 主动连接 OneBot）与反向 WS（OneBot 主动连接 Bot）
*   **多平台适配**：QQ（OneBot v11）、Discord、CLI 与 MCC 平台，含跨平台消息转发
*   **Docker 一键部署**：提供 `Dockerfile` / `docker-compose.yml`，内置全部运行依赖

### 技术栈

*   **核心框架**: Python 3.11+（推荐 3.12+，3.14 可选开启 JIT）& NEO Bot Framework
*   **异步核心**: `asyncio`
*   **网络通信**: `websockets` (OneBot v11), `aiohttp` (HTTP 客户端)
*   **浏览器引擎**: `Playwright` (Chromium) + Page Pool
*   **数据序列化**: `orjson`
*   **缓存/存储**: `Redis` + `MySQL`
*   **日志**: `Loguru`
*   **数据模型**: `Pydantic`

---

## 项目结构

```
.
├── src/
│   └── neobot/             # 核心包目录
│       ├── core/           # 框架核心，非请勿动
│       │   ├── api/        # OneBot API 封装 (account/base/friend/group/media/message)
│       │   ├── data/       # 权限数据文件 (admin.json / permissions.json)
│       │   ├── handlers/   # 事件处理器
│       │   ├── managers/   # 各种管理器 (指令, 浏览器, 图片, 插件, 权限, Redis, 反向WS, 线程, MySQL)
│       │   ├── messaging/  # 平台无关消息层 (PlatformMessage / MessageBus / CommandContext)
│       │   ├── services/   # 服务层 (本地文件服务器)
│       │   ├── utils/      # 工具函数 (logger / exceptions / input_validator / env_loader ...)
│       │   ├── bot.py      # Bot 实例
│       │   ├── config_loader.py    # 配置加载
│       │   ├── config_models.py    # 配置模型
│       │   ├── permission.py       # 权限枚举 (USER/OP/ADMIN)
│       │   ├── plugin.py           # 插件基类 (Plugin / SimplePlugin)
│       │   └── ws.py               # WebSocket 通信层
│       ├── models/         # 数据模型
│       │   ├── events/     # OneBot事件模型
│       │   ├── message.py  # 消息段模型
│       │   ├── objects.py  # API响应对象
│       │   └── sender.py   # 发送者信息
│       ├── adapters/       # 平台适配器
│       │   ├── discord_adapter.py  # Discord 适配器
│       │   ├── cli_adapter.py      # CLI 适配器
│       │   ├── router.py           # 平台路由
│       │   └── mcc_adapter/        # MCC 服务适配器
│       ├── plugins/        # 插件目录，业务逻辑都在这
│       │   ├── admin.py            # 权限管理（Admin/User两级权限）
│       │   ├── auto_approve.py     # 自动同意好友请求和群邀请
│       │   ├── bot_status.py       # Bot运行状态查询（图片形式）
│       │   ├── broadcast.py        # 管理员专用广播功能
│       │   ├── code_py.py          # Python代码沙箱执行
│       │   ├── discord_cross/      # Discord跨平台支持
│       │   ├── echo.py             # Echo/点赞功能
│       │   ├── furry.py            # Furry图片获取
│       │   ├── github_parser.py    # GitHub仓库链接解析
│       │   ├── group_welcome.py    # 群欢迎
│       │   ├── jrcd.py             # 今日人品/长度查询
│       │   ├── mcc*.py             # MCC 相关插件 (mcc/mcc_afk_data/mcc_agent/mcc_listener/mcc_map/mcc_memory)
│       │   ├── mirror_avatar.py    # 头像镜像
│       │   ├── thpic.py            # 东方Project随机图片
│       │   ├── twitter_parser.py   # Twitter/X 链接解析
│       │   ├── weather.py          # 天气查询
│       │   ├── web_parser/         # Web链接解析系统（B站、抖音、GitHub等）
│       │   ├── Greek_alphabet/     # 希腊字母表
│       │   └── osu!_plugin/        # osu! 谱面难度评估
│       ├── tests/          # 单元测试
│       ├── templates/      # Jinja2模板（用于图片生成）
│       ├── docs/           # 开发文档
│       ├── web_static/     # 静态网页文件
│       └── data/           # 数据存储
├── docs/                   # 部署 / 安全 / 性能 / 适配器架构文档
├── scripts/                # 辅助脚本 (compile_machine_code.py / export_requirements.py ...)
├── main.py                 # 启动入口
├── cli.py                  # CLI 适配器入口
├── config.toml             # 配置文件（含敏感信息，不入库）
├── config.example.toml     # 配置模板
├── requirements.txt        # 运行时依赖
├── Dockerfile              # Docker 镜像定义
├── docker-compose.yml      # Docker 编排
├── sandbox.Dockerfile      # 代码沙箱镜像定义
└── README.md               # 项目说明
```

### 目录说明

- **src/neobot/**: 核心 Python 包目录
- **core/**: 框架核心代码，包含事件处理、API封装、管理器、平台无关消息层等
- **models/**: 数据模型定义，包含事件、消息、发送者等
- **adapters/**: 平台适配器，用于连接不同平台（QQ / Discord / CLI / MCC）
- **plugins/**: 插件目录，所有业务逻辑都在这里
- **tests/**: 单元测试和集成测试
- **templates/**: Jinja2 模板文件，用于图片生成
- **docs/**: 项目文档
- **web_static/**: 静态网页文件
- **data/**: 数据存储目录（权限 JSON 等）

## 快速开始

### 方式一：Docker（推荐）

```bash
cp config.example.toml config.toml   # 填写真实凭据
chmod 600 config.toml
docker compose up -d --build
docker compose logs -f
```

详见 [src/neobot/docs/deployment.md](src/neobot/docs/deployment.md) 的 Docker 部署章节。

### 方式二：本地运行

1.  **装环境**: Python 3.11+，Redis， OneBot 客户端 (推荐 NapCat)。
2.  **装依赖**: `pip install -r requirements.txt`
3.  **装浏览器**: `playwright install chromium`
4.  **配置**: `cp config.example.toml config.toml` 并填写 NapCat 地址、Redis 等
5.  **启动**: `python main.py`

> Python 3.14 下可开启 JIT 编译加速：`python -X jit main.py`；
> 可选 AOT 编译核心模块：`python scripts/compile_machine_code.py`（产物平台相关，仅在目标环境编译）。

详细文档去 `src/neobot/docs/` 目录看

## 开发规范

- 所有代码放在 `src/neobot/` 目录下
- 插件开发参考 `src/neobot/docs/plugin-development/`
- 核心开发参考 `src/neobot/docs/core-concepts/`

## 许可证

本项目基于 **GNU Affero General Public License v3.0 (AGPL-3.0)** 授权开源。

- 你可以自由使用、修改、分发本软件
- 如果你通过网络提供服务（例如运行 QQ 机器人成为网络服务），**必须**以 AGPL 相同的许可证开放你的完整源代码
- 详情见 [LICENSE](LICENSE)

### 安全说明

本仓库**不包含任何敏感凭据**：

- `config.toml`（真实配置，含 Redis / MySQL / NapCat / Discord 等凭据）已被 `.gitignore` 排除，仅在本地部署时创建
- 部署请复制 `config.example.toml` 为 `config.toml` 填写，或通过环境变量注入（`MYSQL_*` / `REDIS_*` / `NAPCAT_WS_*` / `DISCORD_TOKEN` 等，见 `src/neobot/core/config_loader.py`）
- `ca/` 私有证书不包含在本仓库

发现安全漏洞，请按 [SECURITY.md](SECURITY.md) 的流程私下报告（GitHub Security Advisory 或邮件），多谢。
