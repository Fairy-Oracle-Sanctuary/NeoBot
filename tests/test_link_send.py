"""链接解析发送链路：本地文件服务、合并转发失败回退、B 站地址选择。"""
from unittest.mock import AsyncMock, MagicMock

import aiohttp
import pytest
from aiohttp import web

from neobot.core.services.local_file_server import (
    LocalFileServer,
    client_timeout,
    prepare_forward_nodes,
    resolve_public_base_url,
)
from neobot.core.utils.exceptions import OneBotApiError
from neobot.plugins.web_parser.base import BaseParser
from neobot.plugins.web_parser.parsers.bili import collect_bili_media_urls
from neobot.plugins.web_parser.utils import summarize_forward_nodes


def test_client_timeout_is_not_a_bare_number():
    timeout = client_timeout(12)
    assert isinstance(timeout, aiohttp.ClientTimeout)
    assert timeout.total == 12


def test_public_base_url_uses_docker_bridge_when_unconfigured(monkeypatch):
    monkeypatch.setattr(
        "neobot.core.services.local_file_server.docker_bridge_ipv4",
        lambda: "172.17.0.1",
    )
    assert resolve_public_base_url("", 3003, "0.0.0.0") == "http://172.17.0.1:3003"


def test_public_base_url_keeps_explicit_value_and_loopback_bind(monkeypatch):
    monkeypatch.setattr(
        "neobot.core.services.local_file_server.docker_bridge_ipv4",
        lambda: "172.17.0.1",
    )
    assert resolve_public_base_url("http://10.0.0.8:3003/", 3003, "0.0.0.0") == "http://10.0.0.8:3003"
    # 只绑回环时，桥地址也连不上，保持 127.0.0.1
    assert resolve_public_base_url("", 3003, "127.0.0.1") == "http://127.0.0.1:3003"


def test_collect_bili_media_urls_prefers_muxed_then_backups():
    data = {
        "durl": [
            {
                "url": "https://upos.example/main.mp4",
                "backup_url": ["https://upos.example/backup.mp4"],
            }
        ],
        "dash": {
            "video": [
                {
                    "baseUrl": "https://upos.example/v.m4s",
                    "backupUrl": ["https://upos.example/v-backup.m4s"],
                }
            ]
        },
    }
    urls = collect_bili_media_urls(data)
    assert urls[0] == "https://upos.example/main.mp4"
    assert "https://upos.example/backup.mp4" in urls
    assert urls.index("https://upos.example/main.mp4") < urls.index("https://upos.example/v.m4s")
    assert "https://upos.example/v-backup.m4s" in urls


def test_summarize_forward_nodes_keeps_text_and_page_link():
    nodes = [
        {
            "type": "node",
            "data": {
                "content": [
                    {"type": "text", "data": {"text": "标题: 示例"}},
                    {"type": "image", "data": {"file": "https://cdn.example/a.jpg"}},
                    {"type": "video", "data": {"file": "https://cdn.example/a.mp4"}},
                ]
            },
        }
    ]
    text = summarize_forward_nodes(nodes, page_url="https://www.bilibili.com/video/BV1xx")
    assert "标题: 示例" in text
    assert "https://www.bilibili.com/video/BV1xx" in text
    assert "cdn.example" not in text
    assert "2 个媒体" in text


@pytest.mark.asyncio
async def test_download_rejects_integer_timeout_and_remembers_content_type(monkeypatch, tmp_path):
    body = b"\x89PNG\r\n\x1a\n"

    async def pic(_request):
        return web.Response(body=body, content_type="image/png")

    app = web.Application()
    app.router.add_get("/pic.png", pic)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    url = f"http://127.0.0.1:{port}/pic.png"

    monkeypatch.setattr(
        "neobot.core.services.local_file_server.input_validator.validate_http_url",
        lambda *_a, **_k: True,
    )
    server = LocalFileServer(host="127.0.0.1", port=9, base_url="http://172.17.0.1:9")
    server.download_dir = tmp_path
    try:
        file_id = await server.download_file(url, timeout=5, trust_env=False)
        assert file_id
        saved = server.file_map[file_id]
        assert saved.read_bytes() == body
        assert server._meta[file_id]["content_type"] == "image/png"
        response = await server.handle_download(type("Req", (), {"query": {"id": file_id}})())
        assert response.content_type == "image/png"
        assert response.status == 200
    finally:
        await runner.cleanup()


@pytest.mark.asyncio
async def test_http_403_retries_without_proxy(monkeypatch, tmp_path):
    created = []

    class _Content:
        def __init__(self):
            self._done = False

        async def read(self, _n):
            if self._done:
                return b""
            self._done = True
            return b"img"

    class _Resp:
        def __init__(self, status):
            self.status = status
            self.headers = {"Content-Type": "image/jpeg", "Content-Length": "3"}
            self.url = "https://cdn.example/a.jpg"
            self.content = _Content()

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_a):
            return False

        def release(self):
            return None

    class _Session:
        def __init__(self, *args, trust_env=True, **kwargs):
            self.trust_env = trust_env
            created.append(self)

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_a):
            return False

        async def get(self, url, timeout, headers=None, allow_redirects=False):
            assert isinstance(timeout, aiohttp.ClientTimeout)
            return _Resp(403 if self.trust_env else 200)

    monkeypatch.setattr("neobot.core.services.local_file_server.aiohttp.ClientSession", _Session)
    monkeypatch.setattr(
        "neobot.core.services.local_file_server.input_validator.validate_http_url",
        lambda *_a, **_k: True,
    )
    server = LocalFileServer(host="0.0.0.0", port=3003, base_url="http://172.17.0.1:3003")
    server.download_dir = tmp_path
    file_id = await server.download_file("https://cdn.example/a.jpg", timeout=5, trust_env=True)
    assert file_id
    assert [item.trust_env for item in created] == [True, False]
    assert server.file_map[file_id].read_bytes() == b"img"


def test_small_image_is_inlined_and_video_uses_reachable_url(monkeypatch, tmp_path):
    server = LocalFileServer(host="0.0.0.0", port=3003, base_url="http://172.17.0.1:3003")
    image = tmp_path / "a.jpg"
    image.write_bytes(b"tiny")
    video = tmp_path / "a.mp4"
    video.write_bytes(b"v" * 32)
    server.file_map["img"] = image
    server.file_map["vid"] = video
    server._meta["img"] = {"content_type": "image/jpeg", "filename": "media.jpg"}
    server._meta["vid"] = {"content_type": "video/mp4", "filename": "media.mp4"}
    monkeypatch.setattr(
        "neobot.core.services.local_file_server.get_local_file_server",
        lambda: server,
    )
    nodes = [
        {
            "type": "node",
            "data": {
                "content": [
                    {"type": "image", "data": {"file": "http://127.0.0.1:3003/download?id=img"}},
                    {"type": "video", "data": {"file": "http://127.0.0.1:3003/download?id=vid"}},
                ]
            },
        }
    ]
    prepare_forward_nodes(nodes)
    image_file = nodes[0]["data"]["content"][0]["data"]["file"]
    video_file = nodes[0]["data"]["content"][1]["data"]["file"]
    assert image_file.startswith("base64://")
    assert video_file == "http://172.17.0.1:3003/download?id=vid"


class _StubParser(BaseParser):
    async def parse(self, url):
        return {"title": "ok"}

    async def get_real_url(self, short_url):
        return short_url

    async def format_response(self, event, data):
        return [
            {
                "type": "node",
                "data": {"content": [{"type": "text", "data": {"text": "解析标题"}}]},
            }
        ]


@pytest.mark.asyncio
async def test_forward_failure_falls_back_to_text_summary():
    parser = _StubParser()
    parser.name = "测试解析"
    event = MagicMock()
    event.bot.send_forwarded_messages = AsyncMock(
        side_effect=OneBotApiError("send_group_forward_msg", {"status": "failed", "retcode": 1400})
    )
    event.reply = AsyncMock()
    await parser.process_url(event, "https://www.bilibili.com/video/BV1xx")
    event.reply.assert_awaited()
    sent = event.reply.await_args.args[0]
    assert "解析标题" in sent
    assert "BV1xx" in sent


@pytest.mark.asyncio
async def test_forward_api_strict_raises():
    from neobot.core.api.base import BaseAPI

    ws = MagicMock()
    ws.call_api = AsyncMock(return_value={"status": "failed", "retcode": 1400, "message": "upload failed", "data": None})
    api = BaseAPI(ws, 1)
    with pytest.raises(OneBotApiError):
        await api.call_api("send_group_forward_msg", {"group_id": 1, "messages": []}, strict=True)
    plain = await api.call_api("send_group_msg", {})
    assert plain is None
