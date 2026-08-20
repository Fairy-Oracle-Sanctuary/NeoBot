"""
框架服务 —— 插件 API 契约 (plugin-api-v1)。

插件可用的框架级服务单例与工具函数。均为只读 / 调用式接口,
插件不得修改这些单例的内部状态。

- :data:`redis_manager`:Redis 缓存(键值读写,含签名);
- :data:`image_manager`:HTML 模板渲染为图片(帮助图等);
- :data:`bot_manager`:Bot 实例注册表;
- :data:`permission_manager`:权限查询与管理员校验(含 :func:`require_admin` 装饰器);
- :data:`message_bus`:跨平台消息总线;
- :func:`download_to_local`:把远程媒体下载到本地(已内置平台防盗链头);
- :func:`get_local_file_server`:本地文件服务器(生成可访问 URL);
- :func:`run_in_thread_pool`:同步阻塞函数放入线程池执行,避免卡事件循环。
"""
from __future__ import annotations

from neobot.core.managers.bot_manager import bot_manager
from neobot.core.managers.image_manager import image_manager
from neobot.core.managers.permission_manager import permission_manager, require_admin
from neobot.core.managers.redis_manager import redis_manager
from neobot.core.messaging.bus import message_bus
from neobot.core.services.local_file_server import (
    download_to_local,
    get_local_file_server,
)
from neobot.core.utils.executor import run_in_thread_pool

__all__ = [
    "redis_manager",
    "image_manager",
    "bot_manager",
    "permission_manager",
    "require_admin",
    "message_bus",
    "download_to_local",
    "get_local_file_server",
    "run_in_thread_pool",
]
