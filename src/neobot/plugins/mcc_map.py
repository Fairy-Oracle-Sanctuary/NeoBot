# -*- coding: utf-8 -*-
"""
实时地图（BlueMap）转发层：数据获取已迁移到 mcc-service（/api/tool map_*）。
保持 map_players / map_regions / map_performance / map_markers 签名不变。
"""
from typing import Optional

from neobot.adapters.mcc_adapter.service_client import MccServiceClient
from neobot.core.config_loader import global_config

_client: Optional[MccServiceClient] = None


def _get_client() -> MccServiceClient:
    global _client
    if _client is None:
        cfg = global_config.mcc_adapter
        _client = MccServiceClient(
            service_url=cfg.service_url,
            service_token=cfg.service_token,
            timeout_ms=cfg.timeout_ms,
        )
    return _client


async def map_players() -> str:
    """实时地图在线玩家列表（含坐标）。"""
    return await _get_client().global_tool("map_players")


async def map_regions() -> str:
    """已加载区域列表及 TPS/MSPT。"""
    return await _get_client().global_tool("map_regions")


async def map_performance() -> str:
    """服务器 TPS/MSPT 文本；地图不可用时返回 MAP_DISABLED/MAP_ERROR:/MAP_EMPTY。"""
    return await _get_client().global_tool("map_performance")


async def map_markers(keyword: str = "", set_name: str = "") -> str:
    """按集合/关键词搜索地图标记。"""
    return await _get_client().global_tool("map_markers", {"keyword": keyword, "set_name": set_name})
