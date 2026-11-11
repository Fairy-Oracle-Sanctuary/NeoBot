"""出站消息钩子：核心只发布 PlatformMessage，产品插件自行订阅。"""
from __future__ import annotations

import orjson
from unittest.mock import AsyncMock, MagicMock, patch
from websockets.protocol import State

from neobot.core.messaging.bus import MessageBus
from neobot.core.messaging.message import PlatformMessage
from neobot.core.ws import WS
from neobot.plugins.discord_cross.outgoing import handle_outgoing_message


def _qq_message(**overrides) -> PlatformMessage:
    data = dict(
        platform="qq",
        channel_id=854,
        channel_type="group",
        message_id=None,
        author_id=10001,
        author_name="",
        content="",
        raw=[
            {"type": "reply", "data": {"id": "99"}},
            {"type": "text", "data": {"text": "hello"}},
            {"type": "image", "data": {"url": "https://example.com/a.png"}},
        ],
        metadata={},
    )
    data.update(overrides)
    return PlatformMessage(**data)


class TestHandleOutgoingMessage:
    async def test_qq_group_send_is_parsed_and_reported(self):
        seen = {}

        async def notify_qq_sent(**kwargs):
            seen.update(kwargs)

        async def fetch_reply(reply_id):
            assert str(reply_id) == "99"
            return {
                "raw_message": "quoted",
                "message": [{"type": "text", "data": {"text": "quoted"}}],
            }

        await handle_outgoing_message(
            _qq_message(),
            notify_qq_sent=notify_qq_sent,
            notify_discord_sent=AsyncMock(),
            fetch_reply=fetch_reply,
            enabled=True,
        )

        assert seen["qq_nickname"] == "NeoBot"
        assert seen["qq_user_id"] == 10001
        assert seen["group_id"] == 854
        assert seen["group_name"] == "群854"
        assert seen["content"] == "> quoted\nhello"
        assert seen["attachments"] == [
            {"type": "image", "url": "https://example.com/a.png", "filename": "image.png"}
        ]

    async def test_reply_lookup_failure_uses_fallback_prefix(self):
        seen = {}

        async def notify_qq_sent(**kwargs):
            seen.update(kwargs)

        async def fetch_reply(reply_id):
            raise RuntimeError("get_msg down")

        await handle_outgoing_message(
            _qq_message(),
            notify_qq_sent=notify_qq_sent,
            notify_discord_sent=AsyncMock(),
            fetch_reply=fetch_reply,
            enabled=True,
        )
        assert seen["content"] == "[回复消息 #99] hello"

    async def test_no_mirror_and_disabled_skip_without_calling_notifier(self):
        notify = AsyncMock()
        await handle_outgoing_message(
            _qq_message(metadata={"no_mirror": True}),
            notify_qq_sent=notify,
            notify_discord_sent=notify,
            fetch_reply=AsyncMock(),
            enabled=True,
        )
        await handle_outgoing_message(
            _qq_message(metadata={}),
            notify_qq_sent=notify,
            notify_discord_sent=notify,
            fetch_reply=AsyncMock(),
            enabled=False,
        )
        notify.assert_not_called()

    async def test_empty_qq_message_is_not_reported(self):
        notify = AsyncMock()
        await handle_outgoing_message(
            _qq_message(raw=""),
            notify_qq_sent=notify,
            notify_discord_sent=notify,
            fetch_reply=AsyncMock(),
            enabled=True,
        )
        notify.assert_not_called()

    async def test_discord_outgoing_is_reported(self):
        notify_discord = AsyncMock()
        message = PlatformMessage(
            platform="discord",
            channel_id=77,
            channel_type="group",
            message_id=None,
            author_id=1,
            author_name="Neo",
            content="hi",
        )
        await handle_outgoing_message(
            message,
            notify_qq_sent=AsyncMock(),
            notify_discord_sent=notify_discord,
            fetch_reply=AsyncMock(),
            enabled=True,
        )
        notify_discord.assert_awaited_once_with(77, "hi", sender_name="Neo")

    async def test_notifier_error_propagates_to_bus_not_to_other_subscribers(self):
        bus = MessageBus()
        delivered = []

        async def bad(_message):
            raise RuntimeError("subscriber down")

        async def good(message):
            delivered.append(message.content)

        bus.on_outgoing(key="test-bad")(bad)
        bus.on_outgoing(key="test-good")(good)
        await bus.publish_outgoing(
            PlatformMessage(
                platform="discord",
                channel_id=1,
                channel_type="group",
                message_id=None,
                author_id=1,
                author_name="Bot",
                content="still-delivered",
            )
        )
        assert delivered == ["still-delivered"]


def _open_ws() -> WS:
    with patch("neobot.core.ws.global_config") as mock_config:
        mock_config.napcat_ws.uri = "ws://localhost:8080"
        mock_config.napcat_ws.token = "test_token"
        mock_config.napcat_ws.reconnect_interval = 5
        ws = WS()
    socket = MagicMock()
    socket.state = State.OPEN

    async def fake_send(payload):
        echo = orjson.loads(payload)["echo"]
        ws._pending_requests[echo].set_result({"status": "ok", "data": {"message_id": 1}})

    socket.send = fake_send
    ws.ws = socket
    ws.self_id = 10001
    return ws


class TestWSPublishesOutgoing:
    async def test_group_send_publishes_raw_message_without_blocking_on_subscriber_error(self):
        from neobot.core.messaging.bus import message_bus

        ws = _open_ws()
        seen = []

        async def boom(_message):
            raise RuntimeError("mirror failed")

        async def record(message):
            seen.append(message)

        message_bus.on_outgoing(key="test-ws-boom")(boom)
        message_bus.on_outgoing(key="test-ws-record")(record)
        try:
            result = await ws.call_api(
                "send_group_msg",
                {"group_id": 42, "message": "ping"},
            )
            import asyncio
            pending = list(ws._background_tasks)
            if pending:
                await asyncio.gather(*pending)
        finally:
            message_bus._outgoing = [
                hook
                for hook in message_bus._outgoing
                if getattr(hook, "_bus_key", None) not in {"test-ws-boom", "test-ws-record"}
            ]

        assert result["status"] == "ok"
        assert len(seen) == 1
        assert seen[0].platform == "qq"
        assert seen[0].channel_id == 42
        assert seen[0].channel_type == "group"
        assert seen[0].author_id == 10001
        assert seen[0].raw == "ping"
        assert seen[0].metadata.get("no_mirror") is False

    async def test_no_mirror_flag_is_visible_and_private_send_is_not_published(self):
        from neobot.core.messaging.bus import message_bus

        ws = _open_ws()
        seen = []

        async def record(message):
            seen.append(message)

        message_bus.on_outgoing(key="test-ws-record-2")(record)
        try:
            await ws.call_api(
                "send_group_msg",
                {"group_id": 42, "message": "echo", "_no_mirror": True},
            )
            await ws.call_api(
                "send_msg",
                {"message_type": "private", "user_id": 1, "message": "dm"},
            )
            await ws.call_api(
                "send_msg",
                {"message_type": "group", "group_id": 7, "message": [{"type": "text", "data": {"text": "g"}}]},
            )
            import asyncio
            pending = list(ws._background_tasks)
            if pending:
                await asyncio.gather(*pending)
        finally:
            message_bus._outgoing = [
                hook
                for hook in message_bus._outgoing
                if getattr(hook, "_bus_key", None) != "test-ws-record-2"
            ]

        assert [message.metadata.get("no_mirror") for message in seen] == [True, False]
        assert [message.channel_id for message in seen] == [42, 7]
        assert seen[1].raw == [{"type": "text", "data": {"text": "g"}}]

    async def test_discord_send_publishes_outgoing_and_subscriber_error_does_not_raise(self):
        from neobot.adapters.router import DiscordToOneBotConverter
        from neobot.core.messaging.bus import message_bus

        seen = []

        async def boom(_message):
            raise RuntimeError("mirror failed")

        async def record(message):
            seen.append(message)

        message_bus.on_outgoing(key="test-dc-boom")(boom)
        message_bus.on_outgoing(key="test-dc-record")(record)
        channel = MagicMock()
        channel.id = 55
        channel.send = AsyncMock()
        adapter = MagicMock()
        adapter.user = None
        try:
            await DiscordToOneBotConverter.send_discord_message(channel, "hello", adapter)
        finally:
            message_bus._outgoing = [
                hook
                for hook in message_bus._outgoing
                if getattr(hook, "_bus_key", None) not in {"test-dc-boom", "test-dc-record"}
            ]

        channel.send.assert_awaited()
        assert len(seen) == 1
        assert seen[0].platform == "discord"
        assert seen[0].channel_id == 55
        assert seen[0].content == "hello"
        assert seen[0].author_name == "Bot"


def test_forwarder_subscribes_to_outgoing_bus():
    source = (
        __import__("pathlib").Path(__file__).resolve().parents[1]
        / "src"
        / "neobot"
        / "plugins"
        / "discord_cross"
        / "forwarder.py"
    ).read_text(encoding="utf-8")
    assert "on_outgoing" in source
    assert "forwarder._bus_outgoing" in source
    assert "handle_outgoing_message" in source
