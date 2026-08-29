from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from maibot_sdk import PluginContext, PluginPaths

from mai_beeper_adapter.core import MaiBeeperAdapterPlugin


class FakeGateway:
    def __init__(self) -> None:
        self.states: list[dict[str, Any]] = []
        self.messages: list[dict[str, Any]] = []

    async def update_state(self, **kwargs: Any) -> None:
        self.states.append(kwargs)

    async def route_message(self, **kwargs: Any) -> bool:
        self.messages.append(kwargs)
        return True


class FakeClient:
    def __init__(self) -> None:
        self.uploads: list[tuple[bytes, str, str]] = []
        self.sends: list[dict[str, Any]] = []

    async def upload_file(self, data: bytes, file_name: str, mime_type: str) -> dict[str, Any]:
        self.uploads.append((data, file_name, mime_type))
        return {
            "uploadID": f"upload-{len(self.uploads)}",
            "fileName": file_name,
            "mimeType": mime_type,
            "width": 64,
            "height": 32,
        }

    async def send_message(self, chat_id: str, **kwargs: Any) -> dict[str, Any]:
        payload = {"chat_id": chat_id, **kwargs}
        self.sends.append(payload)
        return {"pendingMessageID": f"pending-{len(self.sends)}"}


class FakeSyncClient(FakeClient):
    def __init__(self) -> None:
        super().__init__()
        self.pages: list[dict[str, Any]] = []
        self.list_calls: list[dict[str, Any]] = []

    async def list_messages(self, chat_id: str, *, cursor: str = "", direction: str = "before") -> dict[str, Any]:
        self.list_calls.append({"chat_id": chat_id, "cursor": cursor, "direction": direction})
        return self.pages.pop(0)


class FakeDiscoveryClient(FakeSyncClient):
    def __init__(self) -> None:
        super().__init__()
        self.chat_pages: list[dict[str, Any]] = []
        self.search_results: dict[str, list[dict[str, Any]]] = {}

    async def list_chats(self) -> dict[str, Any]:
        return self.chat_pages.pop(0)

    async def search_chats(self, query: str, *, limit: int = 50) -> dict[str, Any]:
        del limit
        return {"items": self.search_results.get(query, []), "hasMore": False}

    async def get_chat(self, chat_id: str) -> dict[str, Any]:
        return {"id": chat_id, "title": chat_id, "type": "single"}


def configured_plugin(tmp_path: Path) -> tuple[MaiBeeperAdapterPlugin, FakeGateway]:
    plugin = MaiBeeperAdapterPlugin()
    gateway = FakeGateway()
    fake_context = SimpleNamespace(
        gateway=gateway,
        paths=PluginPaths(data_dir=tmp_path / "data", runtime_dir=tmp_path / "runtime"),
        logger=SimpleNamespace(
            info=lambda *a, **k: None,
            warning=lambda *a, **k: None,
            debug=lambda *a, **k: None,
            exception=lambda *a, **k: None,
        ),
    )
    plugin._set_context(cast(PluginContext, fake_context))
    plugin.set_plugin_config(
        {
            "plugin": {"enabled": False, "config_version": "1.0.0"},
            "beeper": {"allowed_chat_ids": ["chat-1"]},
        }
    )
    return plugin, gateway


@pytest.mark.asyncio
async def test_disabled_lifecycle_reports_not_ready(tmp_path: Path) -> None:
    plugin, gateway = configured_plugin(tmp_path)
    await plugin.on_load()
    assert gateway.states[-1]["ready"] is False
    assert gateway.states[-1]["metadata"]["reason"] == "插件未啟用"


@pytest.mark.asyncio
async def test_outbound_text_and_multiple_images_preserve_order(tmp_path: Path) -> None:
    plugin, _ = configured_plugin(tmp_path)
    client = FakeClient()
    plugin._client = cast(Any, client)
    results = await plugin._send_outbound(
        "chat-1",
        {
            "raw_message": [
                {"type": "reply", "data": {"target_message_id": "original"}},
                {"type": "text", "data": "第一張"},
                {
                    "type": "image",
                    "data": {"mime_type": "image/png", "file_name": "one.png"},
                    "binary_data_base64": "b25l",
                },
                {"type": "text", "data": "第二張"},
                {
                    "type": "image",
                    "data": {"mime_type": "image/jpeg", "file_name": "two.jpg"},
                    "binary_data_base64": "dHdv",
                },
                {"type": "text", "data": "結尾"},
            ]
        },
    )
    assert len(results) == 3
    assert client.uploads == [(b"one", "one.png", "image/png"), (b"two", "two.jpg", "image/jpeg")]
    assert client.sends[0]["text"] == "第一張"
    assert client.sends[0]["reply_to_message_id"] == "original"
    assert client.sends[0]["attachment"]["uploadID"] == "upload-1"
    assert client.sends[1]["text"] == "第二張"
    assert client.sends[1]["reply_to_message_id"] == ""
    assert client.sends[2]["text"] == "結尾"


@pytest.mark.asyncio
async def test_outbound_voice_base64_is_uploaded_as_audio_attachment(tmp_path: Path) -> None:
    plugin, _ = configured_plugin(tmp_path)
    client = FakeClient()
    plugin._client = cast(Any, client)

    results = await plugin._send_outbound(
        "chat-1",
        {
            "raw_message": [
                {
                    "type": "voice",
                    "data": {"mime_type": "audio/wav", "file_name": "voice.wav"},
                    "binary_data_base64": "UklGRg==",
                }
            ]
        },
    )

    assert len(results) == 1
    assert client.uploads == [(b"RIFF", "voice.wav", "audio/wav")]
    assert client.sends[0]["attachment"]["type"] == "audio"


def test_outbound_chat_id_prefers_beeper_specific_target() -> None:
    target = MaiBeeperAdapterPlugin._outbound_chat_id(
        {
            "message_info": {
                "additional_config": {
                    "beeper_chat_id": "right-chat",
                    "platform_io_target_user_id": "wrong-user",
                },
                "group_info": {"group_id": "wrong-group"},
            }
        },
        {"chat_id": "route-chat"},
    )
    assert target == "right-chat"


def test_sync_state_round_trip(tmp_path: Path) -> None:
    plugin, _ = configured_plugin(tmp_path)
    plugin._cursors = {"chat-1": "cursor-9"}
    plugin._initialized_chats = {"chat-1", "empty-chat"}
    plugin._paired_chat_ids = {"paired-chat"}
    plugin._save_state()

    restored, _ = configured_plugin(tmp_path)
    restored._load_state()
    assert restored._cursors == {"chat-1": "cursor-9"}
    assert restored._initialized_chats == {"chat-1", "empty-chat"}
    assert restored._paired_chat_ids == {"paired-chat"}


@pytest.mark.asyncio
async def test_unique_exact_chat_name_is_allowed_but_duplicate_is_not(tmp_path: Path) -> None:
    plugin, _ = configured_plugin(tmp_path)
    plugin.set_plugin_config(
        {
            "plugin": {"enabled": False, "config_version": "1.0.0"},
            "beeper": {"allowed_chat_ids": []},
            "discovery": {"allowed_chat_names": ["家人群組", "同名群組"]},
        }
    )
    client = FakeDiscoveryClient()
    client.chat_pages = [{"items": []}]
    client.search_results = {
        "家人群組": [{"id": "family-chat", "title": "家人群組", "network": "Signal"}],
        "同名群組": [
            {"id": "duplicate-1", "title": "同名群組"},
            {"id": "duplicate-2", "title": "同名群組"},
        ],
    }
    plugin._client = cast(Any, client)

    await plugin._refresh_chat_cache()

    assert plugin._allowed_chat_ids() == {"family-chat"}
    assert "duplicate-1" not in plugin._allowed_chat_ids()


@pytest.mark.asyncio
async def test_pairing_ignores_existing_preview_then_saves_new_exact_phrase(tmp_path: Path) -> None:
    plugin, _ = configured_plugin(tmp_path)
    plugin.set_plugin_config(
        {
            "plugin": {"enabled": False, "config_version": "1.0.0"},
            "beeper": {"allowed_chat_ids": []},
            "discovery": {"pairing_enabled": True, "pairing_phrase": "#MaiBot配對5827"},
        }
    )
    client = FakeDiscoveryClient()
    client.chat_pages = [
        {
            "items": [
                {
                    "id": "chat-old",
                    "title": "舊聊天",
                    "preview": {"id": "old-preview", "text": "#MaiBot配對5827"},
                }
            ]
        },
        {
            "items": [
                {
                    "id": "chat-new",
                    "title": "正確聊天",
                    "preview": {"id": "new-preview", "text": "#MaiBot配對5827"},
                }
            ]
        },
        {
            "items": [
                {
                    "id": "chat-new",
                    "title": "正確聊天",
                    "preview": {"id": "unpair-preview", "text": "#MaiBot取消配對"},
                }
            ]
        },
    ]
    plugin._client = cast(Any, client)

    await plugin._refresh_chat_cache()
    assert plugin._paired_chat_ids == set()
    await plugin._refresh_chat_cache(scan_pairing=True)

    assert plugin._paired_chat_ids == {"chat-new"}
    assert plugin._allowed_chat_ids() == {"chat-new"}
    restored, _ = configured_plugin(tmp_path)
    restored._load_state()
    assert restored._paired_chat_ids == {"chat-new"}

    await plugin._refresh_chat_cache(scan_pairing=True)
    assert plugin._paired_chat_ids == set()
    restored_after_unpair, _ = configured_plugin(tmp_path)
    restored_after_unpair._load_state()
    assert restored_after_unpair._paired_chat_ids == set()


@pytest.mark.asyncio
async def test_first_enable_sets_cursor_without_replaying_then_routes_new_message(tmp_path: Path) -> None:
    plugin, gateway = configured_plugin(tmp_path)
    client = FakeSyncClient()
    client.pages = [
        {
            "items": [
                {
                    "id": "old-message",
                    "chatID": "chat-1",
                    "senderID": "old-user",
                    "text": "這是以前的訊息",
                }
            ],
            "hasMore": False,
            "newestCursor": "cursor-now",
        },
        {
            "items": [
                {
                    "id": "new-message",
                    "accountID": "signal-account",
                    "chatID": "chat-1",
                    "senderID": "new-user",
                    "senderName": "新訊息使用者",
                    "timestamp": "2026-08-28T12:00:00Z",
                    "text": "這是新增的訊息",
                    "isSender": False,
                    "attachments": [],
                }
            ],
            "hasMore": False,
            "newestCursor": "cursor-next",
        },
    ]
    plugin._client = cast(Any, client)
    plugin._chat_cache["chat-1"] = {"id": "chat-1", "title": "測試私聊", "type": "single"}

    await plugin._initialize_new_chats()
    assert gateway.messages == []
    assert plugin._cursors["chat-1"] == "cursor-now"

    await plugin._reconcile_chat("chat-1")
    assert client.list_calls[-1] == {"chat_id": "chat-1", "cursor": "cursor-now", "direction": "after"}
    assert len(gateway.messages) == 1
    assert gateway.messages[0]["message"]["message_id"] == "new-message"
    assert gateway.messages[0]["route_metadata"]["self_id"] == "beeper-desktop"
    assert plugin._cursors["chat-1"] == "cursor-next"


@pytest.mark.asyncio
async def test_gateway_blocks_outbound_chat_outside_allowlist(tmp_path: Path) -> None:
    plugin, _ = configured_plugin(tmp_path)
    client = FakeClient()
    plugin._client = cast(Any, client)
    plugin._ready = True
    result = await plugin.handle_beeper_gateway(
        {
            "message_info": {"additional_config": {"beeper_chat_id": "not-allowed"}},
            "raw_message": [{"type": "text", "data": "不應送出"}],
        }
    )
    assert result["success"] is False
    assert "不在 Beeper 白名單" in result["error"]
    assert client.sends == []


@pytest.mark.asyncio
async def test_inbound_route_matches_registered_gateway_route(tmp_path: Path) -> None:
    plugin, gateway = configured_plugin(tmp_path)
    plugin._client = cast(Any, FakeClient())
    plugin._chat_cache["chat-1"] = {"id": "chat-1", "title": "測試聊天", "type": "single"}
    await plugin._set_ready(True)

    await plugin._route_inbound(
        {
            "id": "incoming-1",
            "accountID": "facebook-account",
            "chatID": "chat-1",
            "senderID": "sender-1",
            "senderName": "測試使用者",
            "timestamp": "2026-08-28T15:53:52Z",
            "text": "測試訊息",
            "isSender": False,
            "attachments": [],
        }
    )

    registered = gateway.states[-1]
    inbound = gateway.messages[-1]["route_metadata"]
    assert inbound["self_id"] == registered["account_id"]
    assert inbound["connection_id"] == registered["scope"]


@pytest.mark.asyncio
async def test_inbound_audio_is_routed_as_voice_segment(tmp_path: Path) -> None:
    plugin, gateway = configured_plugin(tmp_path)
    plugin._client = cast(Any, FakeClient())
    plugin._chat_cache["chat-1"] = {"id": "chat-1", "title": "測試聊天", "type": "single"}
    audio_path = tmp_path / "voice.ogg"
    audio_path.write_bytes(b"OggS-audio")

    await plugin._route_inbound(
        {
            "id": "incoming-voice",
            "accountID": "facebook-account",
            "chatID": "chat-1",
            "senderID": "sender-1",
            "senderName": "測試使用者",
            "timestamp": "2026-08-30T02:38:33Z",
            "text": "",
            "isSender": False,
            "attachments": [
                {
                    "id": "attachment-opaque-id",
                    "type": "audio",
                    "fileName": "voice.ogg",
                    "mimeType": "audio/ogg",
                    "srcURL": str(audio_path),
                    "isVoiceNote": True,
                }
            ],
        }
    )

    raw_message = gateway.messages[-1]["message"]["raw_message"]
    assert raw_message[0]["type"] == "voice"
    assert raw_message[0]["data"]["mime_type"] == "audio/ogg"
    assert raw_message[0]["data"]["is_voice_note"] is True
    assert raw_message[0]["binary_data_base64"] == "T2dnUy1hdWRpbw=="
