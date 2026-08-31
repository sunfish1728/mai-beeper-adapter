from __future__ import annotations

from typing import Any, ClassVar

from maibot_sdk import Field, PluginConfigBase
from pydantic import field_validator, model_validator

GATEWAY_NAME = "beeper_gateway"
BEEPER_ACCOUNT_ID = "beeper-desktop"
BEEPER_CONNECTION_ID = "beeper-desktop"


class PluginSection(PluginConfigBase):
    __ui_label__: ClassVar[str] = "插件設定"
    __ui_order__: ClassVar[int] = 0

    enabled: bool = Field(
        default=False,
        description="填好 Beeper Token 與聊天白名單後再啟用。",
        json_schema_extra={"label": "啟用插件", "order": 0},
    )
    config_version: str = Field(
        default="1.0.0",
        description="設定格式版本。",
        json_schema_extra={"label": "設定版本", "hidden": True, "disabled": True, "order": 99},
    )


class BeeperSection(PluginConfigBase):
    __ui_label__: ClassVar[str] = "Beeper 連線"
    __ui_order__: ClassVar[int] = 1

    base_url: str = Field(
        default="http://127.0.0.1:23373",
        description="Beeper Desktop API 的本機地址，通常不需要修改。",
        json_schema_extra={
            "label": "API 地址",
            "placeholder": "http://127.0.0.1:23373",
            "order": 0,
        },
    )
    access_token: str = Field(
        default="",
        description="在 Beeper Desktop → Settings → Integrations 建立的 Access Token。",
        json_schema_extra={
            "label": "Access Token",
            "input_type": "password",
            "placeholder": "貼上 Beeper Access Token",
            "order": 1,
        },
    )
    chat_names: list[str] = Field(
        default_factory=list,
        description="輸入要連結的 Beeper 聊天室顯示名稱，再到該聊天室傳送配對文字。刪除名稱會立即停止連結。",
        json_schema_extra={
            "label": "Beeper 聊天白名單",
            "placeholder": "每項填入一個聊天室名稱",
            "order": 2,
        },
    )
    pairing_phrase: str = Field(
        default="#MaiBot配對",
        min_length=4,
        max_length=100,
        description="新增名稱後，到同名 Beeper 聊天室傳送這段完整文字，插件就會自動保存 Beeper ID。",
        json_schema_extra={
            "label": "配對文字",
            "placeholder": "例如：#MaiBot配對5827",
            "order": 3,
        },
    )

    @field_validator("base_url", mode="before")
    @classmethod
    def normalize_base_url(cls, value: Any) -> str:
        normalized = str(value or "http://127.0.0.1:23373").strip().rstrip("/")
        return normalized or "http://127.0.0.1:23373"

    @field_validator("chat_names", mode="before")
    @classmethod
    def normalize_chat_names(cls, value: Any) -> list[str]:
        values = value if isinstance(value, list) else ([] if value is None else [value])
        result: list[str] = []
        seen: set[str] = set()
        for item in values:
            name = str(item or "").strip()
            normalized = name.casefold()
            if name and normalized not in seen:
                seen.add(normalized)
                result.append(name)
        return result

    @field_validator("pairing_phrase", mode="before")
    @classmethod
    def normalize_pairing_phrase(cls, value: Any) -> str:
        return str(value or "#MaiBot配對").strip()


class ReliabilitySection(PluginConfigBase):
    __ui_label__: ClassVar[str] = "穩定性設定"
    __ui_order__: ClassVar[int] = 3

    poll_interval_seconds: float = Field(
        default=10.0,
        ge=2.0,
        le=300.0,
        description="定期補抓新訊息的間隔；WebSocket 正常時仍會用它防止漏訊。",
        json_schema_extra={"label": "補抓間隔（秒）", "step": 1, "order": 0},
    )
    request_timeout_seconds: float = Field(
        default=15.0,
        ge=3.0,
        le=120.0,
        description="Beeper API 單次請求的最長等待時間。",
        json_schema_extra={"label": "請求逾時（秒）", "step": 1, "order": 1},
    )
    max_reconnect_delay_seconds: float = Field(
        default=60.0,
        ge=5.0,
        le=300.0,
        description="Beeper 無法連線時，兩次重試之間最多等待多久。",
        json_schema_extra={"label": "最大重連等待（秒）", "step": 5, "order": 2},
    )


class MaiBeeperSettings(PluginConfigBase):
    plugin: PluginSection = Field(default_factory=PluginSection)
    beeper: BeeperSection = Field(default_factory=BeeperSection)
    reliability: ReliabilitySection = Field(default_factory=ReliabilitySection)

    @model_validator(mode="before")
    @classmethod
    def migrate_legacy_discovery_fields(cls, value: Any) -> Any:
        """保留舊版名稱與配對文字，但不再接受手動 Beeper ID。"""

        if not isinstance(value, dict):
            return value
        migrated = dict(value)
        beeper = dict(migrated.get("beeper") or {})
        discovery = migrated.get("discovery")
        if isinstance(discovery, dict):
            if "chat_names" not in beeper and discovery.get("allowed_chat_names") is not None:
                beeper["chat_names"] = discovery.get("allowed_chat_names")
            if "pairing_phrase" not in beeper and discovery.get("pairing_phrase") is not None:
                beeper["pairing_phrase"] = discovery.get("pairing_phrase")
        migrated["beeper"] = beeper
        return migrated
