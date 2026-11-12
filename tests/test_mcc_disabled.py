"""MCC 默认关闭时不得创建客户端，也不得启动后台探测。"""
import pytest

from neobot.adapters.mcc_adapter.adapter import McpAdapterDisabledError, McpAdapterManager
from neobot.adapters.mcc_adapter.service_client import MccServiceClient
from neobot.core.config_loader import global_config
from neobot.core.config_models import McCAdapterModel


def test_mcc_adapter_model_defaults_to_disabled():
    assert McCAdapterModel().enabled is False


@pytest.mark.asyncio
async def test_get_client_does_not_open_http_when_disabled(monkeypatch):
    constructed = []
    real_init = MccServiceClient.__init__

    def _wrapped(self, *args, **kwargs):
        constructed.append(args)
        return real_init(self, *args, **kwargs)

    monkeypatch.setattr(MccServiceClient, "__init__", _wrapped)
    monkeypatch.setattr(global_config.mcc_adapter, "enabled", False)

    manager = McpAdapterManager()
    with pytest.raises(McpAdapterDisabledError):
        await manager.get_client()
    assert await manager.all() == []
    assert constructed == []


@pytest.mark.asyncio
async def test_review_poll_does_not_start_when_mcc_disabled(monkeypatch):
    import neobot.plugins.wanfeng_review as review

    monkeypatch.setattr(global_config.mcc_adapter, "enabled", False)
    review._running = False
    review._tasks = []
    started = await review.start()
    assert started is False
    assert review._running is False
    assert review._tasks == []
