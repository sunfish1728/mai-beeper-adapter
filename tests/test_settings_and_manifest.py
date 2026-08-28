from __future__ import annotations

import json
from pathlib import Path

from mai_beeper_adapter.core import MaiBeeperAdapterPlugin
from mai_beeper_adapter.settings import MaiBeeperSettings

ROOT = Path(__file__).resolve().parents[1]


def test_manifest_targets_current_maibot_sdk() -> None:
    manifest = json.loads((ROOT / "_manifest.json").read_text(encoding="utf-8"))
    assert manifest["manifest_version"] == 2
    assert manifest["version"] == "0.2.2"
    assert manifest["plugin_type"] == "adapter"
    assert manifest["author"]["url"]
    assert manifest["urls"]["repository"]
    assert manifest["sdk"]["min_version"] == "2.8.0"
    assert manifest["dependencies"] == []


def test_plugin_registers_duplex_gateway() -> None:
    plugin = MaiBeeperAdapterPlugin()
    components = plugin.get_components()
    assert len(components) == 1
    gateway = components[0]
    assert gateway["name"] == "beeper_gateway"
    assert gateway["type"] == "MESSAGE_GATEWAY"
    assert gateway["metadata"]["route_type"] == "duplex"
    assert gateway["metadata"]["platform"] == "beeper"


def test_settings_are_safe_by_default_and_normalize_allowlist() -> None:
    settings = MaiBeeperSettings.model_validate(
        {
            "beeper": {
                "base_url": "http://127.0.0.1:23373/",
                "allowed_chat_ids": [" chat-a ", "chat-a", "", "chat-b"],
            }
        }
    )
    assert settings.plugin.enabled is False
    assert settings.beeper.base_url == "http://127.0.0.1:23373"
    assert settings.beeper.allowed_chat_ids == ["chat-a", "chat-b"]


def test_discovery_settings_normalize_names_and_pairing_phrase() -> None:
    settings = MaiBeeperSettings.model_validate(
        {
            "discovery": {
                "allowed_chat_names": [" 家人群組 ", "家人群組", "FAMILY", "family", ""],
                "pairing_phrase": "  #MaiBot配對5827  ",
                "unpairing_phrase": "  #MaiBot取消配對  ",
            }
        }
    )
    assert settings.discovery.allowed_chat_names == ["家人群組", "FAMILY"]
    assert settings.discovery.pairing_phrase == "#MaiBot配對5827"
    assert settings.discovery.unpairing_phrase == "#MaiBot取消配對"
    assert settings.reliability.poll_interval_seconds == 10.0
