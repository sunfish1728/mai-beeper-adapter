from __future__ import annotations

import json
import subprocess
from pathlib import Path

from mai_beeper_adapter.core import MaiBeeperAdapterPlugin
from mai_beeper_adapter.settings import MaiBeeperSettings

ROOT = Path(__file__).resolve().parents[1]


def test_manifest_targets_current_maibot_sdk() -> None:
    manifest = json.loads((ROOT / "_manifest.json").read_text(encoding="utf-8"))
    assert manifest["manifest_version"] == 2
    assert manifest["version"] == "0.4.3"
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


def test_windows_launcher_uses_ascii_and_crlf() -> None:
    launcher = (ROOT / "install.cmd").read_bytes()
    assert b"powershell.exe" in launcher
    assert b"\r\n" in launcher
    assert launcher.count(b"\n") == launcher.count(b"\r\n")
    assert launcher.isascii()


def test_windows_launcher_runs_through_cmd(tmp_path: Path) -> None:
    launcher = tmp_path / "install.cmd"
    launcher.write_bytes((ROOT / "install.cmd").read_bytes())
    (tmp_path / "install.ps1").write_text("exit 0\n", encoding="ascii")

    result = subprocess.run(
        ["cmd.exe", "/d", "/c", str(launcher)],
        input="\n",
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "rshell.exe" not in result.stdout + result.stderr


def test_windows_powershell_installer_has_utf8_bom() -> None:
    installer = (ROOT / "install.ps1").read_bytes()
    assert installer.startswith(b"\xef\xbb\xbf")
    assert b"Get-FileHash" not in installer


def test_settings_combine_chat_names_and_pairing_phrase_in_beeper_section() -> None:
    settings = MaiBeeperSettings.model_validate(
        {
            "beeper": {
                "base_url": "http://127.0.0.1:23373/",
                "chat_names": [" 家人群組 ", "家人群組", "FAMILY", "family", ""],
                "pairing_phrase": "  #MaiBot配對5827  ",
            }
        }
    )
    assert settings.plugin.enabled is False
    assert settings.beeper.base_url == "http://127.0.0.1:23373"
    assert settings.beeper.chat_names == ["家人群組", "FAMILY"]
    assert settings.beeper.pairing_phrase == "#MaiBot配對5827"
    assert "discovery" not in MaiBeeperSettings.model_fields
    assert "allowed_chat_ids" not in type(settings.beeper).model_fields
    assert "pairing_enabled" not in type(settings.beeper).model_fields
    assert "unpairing_phrase" not in type(settings.beeper).model_fields


def test_settings_are_safe_with_no_chat_names() -> None:
    settings = MaiBeeperSettings()
    assert settings.beeper.chat_names == []
    assert settings.beeper.pairing_phrase == "#MaiBot配對"
    assert settings.reliability.poll_interval_seconds == 10.0


def test_legacy_name_and_pairing_phrase_move_into_unified_section() -> None:
    settings = MaiBeeperSettings.model_validate(
        {
            "beeper": {"allowed_chat_ids": ["obsolete-id"]},
            "discovery": {
                "allowed_chat_names": ["舊版聊天室"],
                "pairing_phrase": "#舊版配對5827",
            },
        }
    )
    assert settings.beeper.chat_names == ["舊版聊天室"]
    assert settings.beeper.pairing_phrase == "#舊版配對5827"
    assert "allowed_chat_ids" not in settings.beeper.model_dump()
