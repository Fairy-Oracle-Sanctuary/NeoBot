# NEO Bot 开发文档

欢迎来到 NEO Bot Framework 开发文档！

这是一个现代化的 Python QQ 机器人框架，基于 OneBot v11 协议，采用异步架构和性能优化技术。无论你是想快速搭建机器人，还是深入了解框架设计，这份文档都能帮助你。


## 📖 文档导览

### 🚀 快速开始
*   [快速上手](./getting-started.md) - 5分钟搭建开发环境
*   [项目结构](./project-structure.md) - 了解代码组织方式
*   [生产部署](./deployment.md) - 将Bot部署到服务器

### 💡 核心概念
*   [架构设计](./core-concepts/architecture.md) - 了解框架的设计理念
*   [性能优化](./core-concepts/performance.md) - JIT、Mypyc、页面池等优化技术
*   [事件流程](./core-concepts/event-flow.md) - 一条消息从接收到回复的完整流程
*   [核心管理器](./core-concepts/singleton-managers.md) - matcher、权限管理、浏览器池、数据库等
*   [Redis原子操作](./core-concepts/redis-atomic-operations.md) - 权限管理的分布式实现
*   [多线程架构](./core-concepts/multithreading.md) - 线程池和线程安全设计
*   [错误处理](./core-concepts/error-handling.md) - 异常处理和错误码体系

### 🔌 API 参考
*   [API 总览](./api/index.md) - API 调用方式和快速导航
*   [消息 API](./api/message.md) - 发送、撤回、转发消息
*   [群组 API](./api/group.md) - 群管理、禁言、踢人等
*   [好友 API](./api/friend.md) - 好友列表、点赞等
*   [账号 API](./api/account.md) - 机器人自身信息获取
*   [媒体 API](./api/media.md) - 图片、语音、视频处理

### 🌟 特色功能
*   **多平台互通** - 支持 Discord 与 QQ 频道的跨平台消息互通
*   **本地文件服务** - 内置轻量级 HTTP 文件服务器，方便传输大文件和媒体
*   **多数据库支持** - 同时支持 Redis 缓存和 MySQL 持久化存储
*   **反向 WebSocket** - 支持 OneBot 客户端主动连接 Bot

### 📚 插件开发
*   [插件入门](./plugin-development/index.md) - 写你的第一个插件
*   [指令处理](./plugin-development/command-handling.md) - 参数解析、权限控制等
*   [最佳实践](./plugin-development/best-practices.md) - 避免常见的坑
*   [插件案例：状态监控](./plugin-development/status-plugin.md) - 深入学习复杂插件实现

### 📋 开发规范
*   [开发规范](./development-standards.md) - 代码风格、异步编程、错误处理规范
