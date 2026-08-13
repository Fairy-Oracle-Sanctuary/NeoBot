# -*- coding: utf-8 -*-
"""
MCC 适配器（转发层）：neobot 只做指令路由，把能力转发到独立程序 mcc-service。

实例元信息（角色名/触发词/挂机开关/群映射）由 mcc-service 的 /api/instances
提供；聊天、性能、传送、Agent 等全部走 HTTP 转发，本地不再直连 MCC MCP。
"""
import asyncio
import time
from typing import Any, Dict, List, Optional, Tuple

from neobot.core.config_loader import global_config
from neobot.core.utils.logger import ModuleLogger

from .service_client import (
    McpAuthError,
    McpError,
    McpTimeoutError,
    McpToolError,
    McpUnreachableError,
    MccServiceClient,
)

logger = ModuleLogger("MccAdapter")


class McpAdapterDisabledError(McpError):
    """适配器未启用时调用 API 抛出。"""


class McpAdapter:
    """
    MCC 实例的转发适配器：方法与旧版一致，内部全部转发到 mcc-service。
    监听去重等本地状态保留在 neobot。
    """

    def __init__(self):
        self.name = ""
        self.role_name = ""
        self.trigger_words: List[str] = ["luoxiaolei"]
        self.afk_enabled = True
        self._client: Optional[MccServiceClient] = None
        self._configured = False
        self._enabled = False
        # 监听轮询互斥锁与响应去重（本地状态）
        self._listener_lock = asyncio.Lock()
        self._listener_responded: Dict[Tuple[str, str], float] = {}

    # ── 服务器内监听辅助 ─────────────────────────────────────────

    def listener_poll_guard(self) -> asyncio.Lock:
        return self._listener_lock

    def listener_should_respond(self, key: str, window_seconds: float = 60.0) -> bool:
        now = time.monotonic()
        last = self._listener_responded.get(key, 0.0)
        if now - last < window_seconds:
            return False
        self._listener_responded[key] = now
        if len(self._listener_responded) > 256:
            oldest_keys = sorted(self._listener_responded, key=self._listener_responded.get)[:128]
            for old_key in oldest_keys:
                del self._listener_responded[old_key]
        return True

    def configure(self, name: str, role_name: str, trigger_words: List[str], afk_enabled: bool, client: MccServiceClient):
        self.name = name
        self.role_name = role_name
        self.trigger_words = list(trigger_words)
        self.afk_enabled = afk_enabled
        self._client = client
        self._enabled = True
        self._configured = True

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def url(self) -> str:
        """mcc-service 端点（用于状态展示）。"""
        return self._client.base_url if self._client else ""

    def _ensure(self) -> MccServiceClient:
        if not self._configured or self._client is None:
            raise McpAdapterDisabledError(
                "MCC 实例未从 mcc-service 加载，请检查服务是否启动且 config.toml 的 [mcc_adapter] 配置正确"
            )
        return self._client

    async def _tool(self, tool: str, arguments: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        client = self._ensure()
        try:
            return await client.instance_tool(self.name, tool, arguments)
        except McpError:
            raise
        except Exception as e:
            raise McpUnreachableError(f"MCC 服务转发异常: {type(e).__name__}: {e}") from e

    # ── 对外 API（与旧版一致，转发到 mcc-service）────────────────

    async def send_chat(self, text: str) -> Dict[str, Any]:
        return await self._tool("mcc_send_chat", {"text": text})

    async def run_internal_command(self, command: str) -> Dict[str, Any]:
        return await self._tool("mcc_run_internal_command", {"command": command})

    async def session_status(self) -> Dict[str, Any]:
        return await self._tool("mcc_session_status")

    async def server_info(self) -> Dict[str, Any]:
        return await self._tool("mcc_server_info")

    async def players_list(self) -> Dict[str, Any]:
        return await self._tool("mcc_players_list")

    async def chat_history(self, max_count: int = 50, include_json: bool = False) -> Dict[str, Any]:
        return await self._tool(
            "mcc_chat_history",
            {"maxCount": max(1, min(int(max_count), 500)), "includeJson": bool(include_json)},
        )

    async def recent_events(
        self,
        after_id: int = 0,
        max_count: int = 50,
        type_filter: Optional[str] = None,
    ) -> Dict[str, Any]:
        return await self._tool(
            "mcc_recent_events",
            {"afterId": int(after_id), "maxCount": max(1, min(int(max_count), 500)), "typeFilter": type_filter},
        )

    async def tools_list(self) -> List[Dict[str, Any]]:
        result = await self._tool("mcc_tools_list")
        return (result.get("data") or {}).get("tools") or []

    async def call_tool(self, name: str, arguments: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        return await self._tool("mcc_call_tool", {"name": name, "arguments": arguments})

    async def query_performance(self) -> Dict[str, Any]:
        return await self._tool("query_performance")

    async def tp_to(self, command: str) -> Dict[str, Any]:
        return await self._tool("tp_to", {"command": command})

    async def afk_list(self) -> str:
        result = await self._tool("afk_list")
        return str(result.get("text") or "")

    async def afk_tp(self, spot: str) -> str:
        result = await self._tool("afk_tp", {"spot": spot})
        return str(result.get("text") or result.get("message") or "")

    async def agent(self, task: str, caller: Optional[Dict[str, Any]] = None) -> str:
        return await self._ensure().agent(self.name, task, caller)

    async def close(self):
        pass


class McpAdapterManager:
    """
    多实例管理器（转发层）：从 mcc-service 拉取实例列表并建立群路由。
    """

    def __init__(self):
        self._instances: Dict[str, McpAdapter] = {}
        self._group_map: Dict[int, str] = {}
        self._configured = False
        self._loading = False
        self._client: Optional[MccServiceClient] = None

    async def _ensure_configured(self):
        """首次使用时从 mcc-service 拉取实例列表（并发去重）。"""
        if self._configured:
            return
        cfg = global_config.mcc_adapter
        if not cfg.enabled:
            self._configured = True
            return
        if self._loading:
            return
        self._loading = True
        try:
            client = MccServiceClient(
                service_url=cfg.service_url,
                service_token=cfg.service_token,
                panel_token=cfg.panel_token,
                timeout_ms=cfg.timeout_ms,
            )
            self._client = client
            instances = await client.get_instances()
            for info in instances:
                if not isinstance(info, dict) or not info.get("name"):
                    continue
                adapter = McpAdapter()
                adapter.configure(
                    name=str(info["name"]),
                    role_name=str(info.get("role_name") or ""),
                    trigger_words=[str(w) for w in info.get("trigger_words") or []],
                    afk_enabled=bool(info.get("afk_enabled", True)),
                    client=client,
                )
                self._instances[adapter.name] = adapter
                for gid in info.get("groups") or []:
                    try:
                        self._group_map[int(gid)] = adapter.name
                    except (TypeError, ValueError):
                        continue
            logger.info(f"MCC 转发层就绪：{', '.join(self._instances)}（来自 mcc-service）")
        except Exception as e:
            logger.error(f"从 mcc-service 拉取实例失败: {type(e).__name__}: {e}")
        finally:
            self._loading = False
            self._configured = True

    async def get_for_group(self, group_id: int) -> Optional[McpAdapter]:
        await self._ensure_configured()
        name = self._group_map.get(int(group_id))
        return self._instances.get(name) if name else None

    async def get_for_private(self, user_id: int) -> Optional[McpAdapter]:
        """
        私聊路由：登记的 QQ（存在有效租赁）→ 其租到的假人实例。
        未登记/无租赁/服务不可用返回 None。
        """
        await self._ensure_configured()
        if not user_id or self._client is None:
            return None
        try:
            data = await self._client.rental_status(int(user_id))
        except Exception as e:
            logger.debug(f"查询租赁状态失败: {type(e).__name__}: {e}")
            return None
        if not isinstance(data, dict):
            return None
        rental = data.get("rental")
        bot = (rental or {}).get("bot") if isinstance(rental, dict) else None
        if not bot:
            return None
        for adapter in self._instances.values():
            if adapter.role_name == bot:
                return adapter
        return None

    async def get_by_name(self, name: str) -> Optional[McpAdapter]:
        await self._ensure_configured()
        return self._instances.get(name)

    async def all(self) -> List[McpAdapter]:
        await self._ensure_configured()
        return list(self._instances.values())

    async def get_client(self) -> MccServiceClient:
        """
        返回共享的 MccServiceClient 单例（与所有 adapter 复用同一连接池）。
        若 mcc_adapter 未启用或尚未初始化，则按当前配置现场创建一个。
        """
        await self._ensure_configured()
        if self._client is not None:
            return self._client
        # mcc_adapter 未启用时 _ensure_configured 直接返回，_client 仍为 None
        cfg = global_config.mcc_adapter
        self._client = MccServiceClient(
            service_url=cfg.service_url,
            service_token=cfg.service_token,
            panel_token=cfg.panel_token,
            timeout_ms=cfg.timeout_ms,
        )
        return self._client

    async def close(self):
        if self._client is not None:
            try:
                await self._client.close()
            except Exception as e:
                logger.debug(f"关闭 MccServiceClient 失败: {type(e).__name__}: {e}")
        self._instances.clear()
        self._group_map.clear()


# 兼容旧版单实例引用：默认取第一个实例（若有）
mcc = McpAdapter()
mcc_manager = McpAdapterManager()
