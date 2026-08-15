# -*- coding: utf-8 -*-
"""
MCC 独立服务客户端：neobot 只做指令路由，实际能力全部转发到
mcc-service（HTTP JSON API，Bearer 鉴权）。
"""
import asyncio
import json
from typing import Any, Dict, List, Optional

import aiohttp

from neobot.core.utils.logger import ModuleLogger

logger = ModuleLogger("MccServiceClient")


class McpError(Exception):
    """MCC 调用错误基类（兼容旧模块名）。"""


class McpUnreachableError(McpError):
    """MCC 服务不可达。"""


class McpAuthError(McpError):
    """鉴权失败（服务端 token 不匹配）。"""


class McpToolError(McpError):
    """MCC 工具返回错误。"""

    def __init__(self, message: str, code: Optional[int] = None, data: Any = None):
        super().__init__(message)
        self.code = code
        self.data = data


class McpTimeoutError(McpError):
    """请求超时。"""


class MccServiceClient:
    """mcc-service HTTP 客户端。"""

    # Agent 需要跑 LLM 多轮工具循环，独立使用更长超时
    AGENT_TIMEOUT_SECONDS = 180

    def __init__(self, service_url: str, service_token: str = "", timeout_ms: int = 10000, panel_token: str = ""):
        self.base_url = service_url.rstrip("/")
        self.service_token = service_token
        self.panel_token = panel_token
        self.timeout = max(timeout_ms, 1000) / 1000
        self._http: Optional[aiohttp.ClientSession] = None

    def _get_http(self) -> aiohttp.ClientSession:
        if self._http is None or self._http.closed:
            self._http = aiohttp.ClientSession(trust_env=False)
        return self._http

    def _headers(self, token: Optional[str] = None) -> Dict[str, str]:
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        # token 参数优先；其次 service_token（管理员）；无则不带鉴权
        effective = token if token is not None else self.service_token
        if effective:
            headers["Authorization"] = f"Bearer {effective}"
        return headers

    async def _post(self, path: str, payload: Dict[str, Any], timeout_ms: Optional[int] = None, token: Optional[str] = None) -> Any:
        http = self._get_http()
        effective_timeout = max(timeout_ms or int(self.timeout * 1000), 1000) / 1000
        headers = self._headers(token=token)
        try:
            async with http.post(
                f"{self.base_url}{path}",
                json=payload,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=effective_timeout),
            ) as response:
                if response.status in (401, 403):
                    raise McpAuthError(f"MCC 服务鉴权失败（HTTP {response.status}）")
                if response.status >= 500:
                    raise McpUnreachableError(f"MCC 服务错误（HTTP {response.status}）")
                if response.status != 200:
                    raise McpUnreachableError(f"MCC 服务请求失败（HTTP {response.status}）")
                try:
                    return await response.json(content_type=None)
                except Exception as e:
                    raise McpUnreachableError(f"MCC 服务响应解析失败: {type(e).__name__}: {e}") from e
        except McpError:
            raise
        except (asyncio.TimeoutError, aiohttp.ServerTimeoutError) as e:
            raise McpTimeoutError(f"MCC 服务请求超时（{effective_timeout:.1f}s）") from e
        except aiohttp.ClientError as e:
            raise McpUnreachableError(f"MCC 服务不可达: {type(e).__name__}: {e}") from e

    async def _get(self, path: str) -> Any:
        http = self._get_http()
        try:
            async with http.get(
                f"{self.base_url}{path}",
                headers=self._headers(),
                timeout=aiohttp.ClientTimeout(total=self.timeout),
            ) as response:
                if response.status in (401, 403):
                    raise McpAuthError(f"MCC 服务鉴权失败（HTTP {response.status}）")
                if response.status >= 500:
                    raise McpUnreachableError(f"MCC 服务错误（HTTP {response.status}）")
                if response.status != 200:
                    raise McpUnreachableError(f"MCC 服务请求失败（HTTP {response.status}）")
                return await response.json(content_type=None)
        except McpError:
            raise
        except (asyncio.TimeoutError, aiohttp.ServerTimeoutError) as e:
            raise McpTimeoutError(f"MCC 服务请求超时（{self.timeout:.1f}s）") from e
        except aiohttp.ClientError as e:
            raise McpUnreachableError(f"MCC 服务不可达: {type(e).__name__}: {e}") from e

    # ── 实例管理 ────────────────────────────────────────────────

    async def get_instances(self) -> List[Dict[str, Any]]:
        data = await self._get("/api/instances")
        return data if isinstance(data, list) else []

    async def lifecycle(self, name: str, action: str) -> Dict[str, Any]:
        data = await self._post(
            f"/api/instances/{name}/lifecycle",
            {"action": action},
        )
        return data if isinstance(data, dict) else {"success": False, "message": str(data)}

    async def rental_status(self, qq: int) -> Dict[str, Any]:
        """查询某 QQ 的租赁状态（私聊路由用）。"""
        data = await self._get(f"/api/rental/status?qq={int(qq)}")
        return data if isinstance(data, dict) else {"success": False, "message": str(data)}

    async def issue_login_token(self, qq: str) -> Dict[str, Any]:
        """
        签发一次性登录密钥：POST /api/auth/issue。

        使用 panel_token 鉴权，仅 127.0.0.1:8800 可用（公网 8801 返回 404）。
        mcc-service 以私聊者 QQ 作为归属验证，login_token 5 分钟有效，
        用户在网页 POST /api/auth/verify 输入换取 session_token。

        Args:
            qq: 私聊者的 QQ 号（字符串）

        Returns:
            服务端响应 dict，成功时含 login_token / expires_in
        """
        data = await self._post(
            "/api/auth/issue",
            {"qq": str(qq)},
            token=self.panel_token or None,
        )
        return data if isinstance(data, dict) else {"success": False, "message": str(data)}

    # ── 永久租赁人工审核（admin/service_token 鉴权，仅内部 8800）──

    async def rental_pending(self) -> Dict[str, Any]:
        """
        GET /api/rental/pending：列出全部待审核的永久租赁申请（仅 admin）。
        返回 {"success": true, "pending": [...], "count": n}
        """
        data = await self._get("/api/rental/pending")
        return data if isinstance(data, dict) else {"success": False, "message": str(data)}

    async def rental_approve(self, qq: str) -> Dict[str, Any]:
        """
        POST /api/rental/approve：人工审核通过某 QQ 的永久租赁申请（仅 admin）。
        """
        data = await self._post("/api/rental/approve", {"qq": str(qq)})
        return data if isinstance(data, dict) else {"success": False, "message": str(data)}

    async def rental_reject(self, qq: str) -> Dict[str, Any]:
        """
        POST /api/rental/reject：人工拒绝某 QQ 的永久租赁申请（仅 admin）。
        """
        data = await self._post("/api/rental/reject", {"qq": str(qq)})
        return data if isinstance(data, dict) else {"success": False, "message": str(data)}

    # ── /mcc 指令转发（auth_token 鉴权，真实 QQ 由 body/query 传入）──

    async def mcc_instances(self, qq: str) -> Dict[str, Any]:
        """
        GET /api/mcc/instances?qq=<qq>：列出该 QQ 可管理假人 + 当前选中。

        返回：
            {"success": true, "current": "fake3", "instances": [...]}
        """
        from urllib.parse import quote
        data = await self._get(f"/api/mcc/instances?qq={quote(str(qq))}")
        return data if isinstance(data, dict) else {"success": False, "message": str(data)}

    async def mcc_select(
        self,
        qq: str,
        index: Optional[int] = None,
        name: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        POST /api/mcc/select：切换当前假人。

        Args:
            qq: 操作者 QQ
            index: 1-based 序号（与 instances 列表顺序对应）
            name: 假人名称（与 index 二选一；都不传则默认选第 1 个）
        """
        body: Dict[str, Any] = {"qq": str(qq)}
        if index is not None:
            body["index"] = index
        elif name is not None:
            body["name"] = name
        data = await self._post("/api/mcc/select", body)
        return data if isinstance(data, dict) else {"success": False, "message": str(data)}

    async def mcc_exec(
        self,
        qq: str,
        cmd: str,
        args: Optional[list] = None,
        timeout_ms: Optional[int] = None,
        **fields,
    ) -> Dict[str, Any]:
        """
        POST /api/mcc/exec：在当前假人上执行 /mcc 子命令。

        Args:
            qq: 操作者 QQ
            cmd: 子命令名（中文，如 "聊天"/"命令"/"agent"/"记忆" 等）
            args: 位置参数列表（可选）
            timeout_ms: 单次请求超时覆盖（agent 子命令可能 30s+）
            **fields: 具名字段（如 text/command/content/task/index/name 等）
        """
        body: Dict[str, Any] = {"qq": str(qq), "cmd": cmd}
        if args:
            body["args"] = list(args)
        for k, v in fields.items():
            if v is not None:
                body[k] = v
        data = await self._post("/api/mcc/exec", body, timeout_ms=timeout_ms)
        return data if isinstance(data, dict) else {"success": False, "message": str(data)}

    # ── 能力转发 ────────────────────────────────────────────────

    async def instance_tool(self, name: str, tool: str, arguments: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """调用实例高层工具，返回与服务端一致的 dict。"""
        data = await self._post(
            f"/api/instances/{name}/tool",
            {"name": tool, "arguments": arguments or {}},
        )
        if isinstance(data, dict):
            return data
        return {"success": False, "message": f"服务端返回异常: {data}"}

    async def agent(self, name: str, task: str, caller: Optional[Dict[str, Any]] = None) -> str:
        payload: Dict[str, Any] = {"task": task}
        if caller:
            payload["caller"] = caller
        data = await self._post(
            f"/api/instances/{name}/agent",
            payload,
            timeout_ms=self.AGENT_TIMEOUT_SECONDS * 1000,
        )
        if isinstance(data, dict) and data.get("success"):
            return str(data.get("reply") or "（Agent 无回复）")
        if isinstance(data, dict):
            return f"❌ Agent 服务错误：{data.get('message') or data}"
        return "❌ Agent 服务返回异常"

    async def global_tool(self, tool: str, arguments: Optional[Dict[str, Any]] = None) -> str:
        """全局工具（map_*/wiki_*），返回文本。"""
        data = await self._post("/api/tool", {"name": tool, "arguments": arguments or {}})
        if isinstance(data, dict) and data.get("success"):
            return str(data.get("result") or "")
        if isinstance(data, dict):
            return f"❌ {tool} 服务错误：{data.get('message') or data}"
        return f"❌ {tool} 服务返回异常"

    async def close(self):
        if self._http is not None and not self._http.closed:
            await self._http.close()
            self._http = None
