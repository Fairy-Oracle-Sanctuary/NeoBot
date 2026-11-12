"""合并转发：超大视频改走群文件，发送失败则重试一次再逐条发。"""
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from neobot.core.services.forward_delivery import (
    FORWARD_VIDEO_SAFE_BYTES,
    NAPCAT_FORWARD_VIDEO_LIMIT,
    ForwardNotDelivered,
    build_compress_command,
    deliver_forward,
    detach_oversized_videos,
    split_forward_batches,
    video_bitrate,
)
from neobot.core.services.local_file_server import LocalFileServer
from neobot.core.utils.exceptions import OneBotApiError


def test_safe_limit_is_under_napcat_highway_cap():
    assert NAPCAT_FORWARD_VIDEO_LIMIT == 100 * 1024 * 1024
    assert FORWARD_VIDEO_SAFE_BYTES <= 95 * 1024 * 1024
    assert FORWARD_VIDEO_SAFE_BYTES < NAPCAT_FORWARD_VIDEO_LIMIT


def test_video_bitrate_refuses_when_it_cannot_fit():
    assert video_bitrate(0, 90 * 1024 * 1024) is None
    # 十分钟压进 90MiB 仍然高于下限
    assert video_bitrate(600, 90 * 1024 * 1024) is not None
    # 太长就放弃压缩，改走群文件（音轨本身就装不下）
    assert video_bitrate(2 * 3600, 90 * 1024 * 1024) is None


def test_compress_command_needs_ffmpeg_and_a_usable_bitrate(monkeypatch):
    monkeypatch.setattr("neobot.core.services.forward_delivery.shutil.which", lambda _name: "/usr/bin/ffmpeg")
    cmd = build_compress_command(Path("a.mp4"), Path("b.mp4"), 120, 90 * 1024 * 1024)
    assert cmd is not None
    assert cmd[0] == "ffmpeg"
    assert "libx264" in cmd
    assert "-threads" in cmd
    assert cmd[cmd.index("-threads") + 1] == "2"
    monkeypatch.setattr("neobot.core.services.forward_delivery.shutil.which", lambda _name: None)
    assert build_compress_command(Path("a.mp4"), Path("b.mp4"), 120, 90 * 1024 * 1024) is None


def _server(tmp_path: Path) -> LocalFileServer:
    server = LocalFileServer(host="127.0.0.1", port=3003, base_url="http://172.19.0.1:3003")
    server.download_dir = tmp_path
    return server


def _video_node(url: str) -> dict:
    return {
        "type": "node",
        "data": {
            "content": [
                {"type": "text", "data": {"text": "封面说明"}},
                {"type": "video", "data": {"file": url}},
            ]
        },
    }


def test_under_limit_video_stays_in_the_forward(tmp_path):
    server = _server(tmp_path)
    video = tmp_path / "ok.mp4"
    video.write_bytes(b"v" * 32)
    server.file_map["vid"] = video
    node = _video_node("http://172.19.0.1:3003/download?id=vid")
    called = []

    def _compress(*_args):
        called.append(True)
        return False

    uploads = detach_oversized_videos([node], server, limit_bytes=1024, compress=_compress)
    assert uploads == []
    assert called == []
    assert node["data"]["content"][1]["type"] == "video"


def test_over_limit_video_is_compressed_back_into_the_forward(tmp_path):
    server = _server(tmp_path)
    video = tmp_path / "big.mp4"
    video.write_bytes(b"v" * 40)
    server.file_map["vid"] = video
    server._meta["vid"] = {"filename": "big.mp4", "content_type": "video/mp4"}
    node = _video_node("http://172.19.0.1:3003/download?id=vid")

    def _compress(src, dest, limit):
        dest.write_bytes(b"small")
        return True

    uploads = detach_oversized_videos([node], server, limit_bytes=16, compress=_compress)
    assert uploads == []
    file_val = node["data"]["content"][1]["data"]["file"]
    assert file_val.startswith("http://172.19.0.1:3003/download?id=")
    assert "id=vid" not in file_val
    new_id = file_val.split("id=", 1)[1]
    assert server.file_map[new_id].read_bytes() == b"small"


def test_over_limit_video_becomes_group_file_when_compress_fails(tmp_path):
    server = _server(tmp_path)
    video = tmp_path / "big.mp4"
    video.write_bytes(b"v" * 40)
    server.file_map["vid"] = video
    server._meta["vid"] = {"filename": "讲座.mp4", "content_type": "video/mp4"}
    cover = {
        "type": "node",
        "data": {"content": [{"type": "image", "data": {"file": "base64://aaaa"}}]},
    }
    node = _video_node("http://172.19.0.1:3003/download?id=vid")
    uploads = detach_oversized_videos(
        [cover, node],
        server,
        limit_bytes=16,
        compress=lambda *_a: False,
    )
    assert len(uploads) == 1
    assert uploads[0]["url"] == "http://172.19.0.1:3003/download?id=vid"
    assert uploads[0]["name"] == "讲座.mp4"
    assert uploads[0]["size"] == 40
    kinds = [seg.get("type") for seg in node["data"]["content"]]
    assert "video" not in kinds
    assert cover["data"]["content"][0]["type"] == "image"


def test_split_isolates_video_and_packs_light_nodes():
    light = [{"type": "node", "data": {"content": [{"type": "text", "data": {"text": str(i)}}]}} for i in range(5)]
    heavy = [{"type": "node", "data": {"content": [{"type": "video", "data": {"file": "http://x/a.mp4"}}]}}]
    batches = split_forward_batches(light[:2] + heavy + light[2:], batch_size=4)
    assert batches[0] == light[:2]
    assert batches[1] == heavy
    assert batches[2] == light[2:]


def test_file_url_small_image_is_inlined(tmp_path):
    from neobot.core.services.local_file_server import _prepare_segment

    server = _server(tmp_path)
    image = tmp_path / "a.jpg"
    image.write_bytes(b"tiny-image")
    segment = {"type": "image", "data": {"file": image.as_uri()}}
    _prepare_segment(server, segment)
    assert segment["data"]["file"].startswith("base64://")


def _bot():
    bot = MagicMock()
    bot.send_group_forward_msg = AsyncMock()
    bot.send_private_forward_msg = AsyncMock()
    bot.call_api = AsyncMock()
    bot._process_message = lambda message: message
    return bot


@pytest.mark.asyncio
async def test_forward_retries_once_then_sends_nodes_individually(monkeypatch):
    bot = _bot()
    bot.send_group_forward_msg.side_effect = OneBotApiError(
        "send_group_forward_msg", {"status": "failed", "retcode": 1200, "message": "res_id"}
    )
    nodes = [
        {"type": "node", "data": {"content": [
            {"type": "text", "data": {"text": "标题"}},
            {"type": "image", "data": {"file": "base64://aaaa"}},
        ]}},
    ]
    monkeypatch.setattr(
        "neobot.core.services.local_file_server.get_local_file_server",
        lambda: None,
    )
    await deliver_forward(bot, "group", 1, nodes)
    assert bot.send_group_forward_msg.await_count == 2
    plain = [
        call.args[0]
        for call in bot.call_api.await_args_list
        if call.args[0] == "send_group_msg"
    ]
    assert plain == ["send_group_msg"]
    message = bot.call_api.await_args_list[0].args[1]["message"]
    assert any(seg.get("type") == "image" for seg in message)


@pytest.mark.asyncio
async def test_forward_success_does_not_retry(monkeypatch):
    bot = _bot()
    nodes = [{"type": "node", "data": {"content": "你好"}}]
    monkeypatch.setattr(
        "neobot.core.services.local_file_server.get_local_file_server",
        lambda: None,
    )
    await deliver_forward(bot, "group", 9, nodes)
    bot.send_group_forward_msg.assert_awaited_once()
    bot.call_api.assert_not_called()


@pytest.mark.asyncio
async def test_oversized_video_is_uploaded_as_group_file(monkeypatch, tmp_path):
    server = _server(tmp_path)
    video = tmp_path / "big.mp4"
    video.write_bytes(b"v" * 40)
    server.file_map["vid"] = video
    server._meta["vid"] = {"filename": "big.mp4", "content_type": "video/mp4"}
    nodes = [
        {"type": "node", "data": {"content": [{"type": "text", "data": {"text": "标题"}}]}},
        _video_node("http://172.19.0.1:3003/download?id=vid"),
    ]
    monkeypatch.setattr(
        "neobot.core.services.local_file_server.get_local_file_server",
        lambda: server,
    )
    monkeypatch.setattr(
        "neobot.core.services.forward_delivery.detach_oversized_videos",
        lambda nodes, server, **kwargs: detach_oversized_videos(
            nodes, server, limit_bytes=16, compress=lambda *_a: False
        ),
    )
    bot = _bot()
    await deliver_forward(bot, "group", 42, nodes)
    forwarded_types = []
    for call in bot.send_group_forward_msg.await_args_list:
        for node in call.args[1]:
            for seg in node["data"]["content"]:
                if isinstance(seg, dict):
                    forwarded_types.append(seg.get("type"))
    assert "video" not in forwarded_types
    upload = next(call for call in bot.call_api.await_args_list if call.args[0] == "upload_group_file")
    assert upload.args[1]["group_id"] == 42
    assert upload.args[1]["file"].endswith("id=vid")
    assert upload.args[1]["name"] == "big.mp4"


@pytest.mark.asyncio
async def test_total_failure_raises(monkeypatch):
    bot = _bot()
    bot.send_group_forward_msg.side_effect = OneBotApiError(
        "send_group_forward_msg", {"status": "failed", "retcode": 1200}
    )
    bot.call_api.side_effect = OneBotApiError("send_group_msg", {"status": "failed", "retcode": 1200})
    nodes = [{"type": "node", "data": {"content": "只有文字"}}]
    monkeypatch.setattr(
        "neobot.core.services.local_file_server.get_local_file_server",
        lambda: None,
    )
    with pytest.raises(ForwardNotDelivered):
        await deliver_forward(bot, "group", 1, nodes)
