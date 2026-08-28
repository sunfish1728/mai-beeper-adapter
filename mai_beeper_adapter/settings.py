from __future__ import annotations

from typing import Any, ClassVar

from maibot_sdk import Field, PluginConfigBase
from pydantic import field_validator

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
    allowed_chat_ids: list[str] = Field(
        default_factory=list,
        description="只處理這些 Beeper chatID。留空時不會接收任何聊天，日誌會列出近期聊天供複製。",
        json_schema_extra={
            "label": "聊天白名單",
            "placeholder": "每項填入一個 Beeper chatID",
            "order": 2,
        },
    )

    @field_validator("base_url", mode="before")
    @classmethod
    def normalize_base_url(cls, value: Any) -> str:
        normalized = str(value or "http://127.0.0.1:23373").strip().rstrip("/")
        return normalized or "http://127.0.0.1:23373"

    @field_validator("allowed_chat_ids", mode="before")
    @classmethod
    def normalize_chat_ids(cls, value: Any) -> list[str]:
        values = value if isinstance(value, list) else ([] if value is None else [value])
        result: list[str] = []
        seen: set[str] = set()
        for item in values:
            chat_id = str(item or "").strip()
            if chat_id and chat_id not in seen:
                seen.add(chat_id)
                result.append(chat_id)
        return result


class DiscoverySection(PluginConfigBase):
    __ui_label__: ClassVar[str] = "自動取得聊天室"
    __ui_order__: ClassVar[int] = 2

    allowed_chat_names: list[str] = Field(
        default_factory=list,
        description="填入聊天室顯示名稱。只有唯一且名稱完全相同時才會自動採用，避免選錯同名聊天。",
        json_schema_extra={
            "label": "依名稱自動尋找",
            "placeholder": "每項填入一個聊天室名稱",
            "order": 0,
        },
    )
    pairing_enabled: bool = Field(
        default=False,
        description="開啟後，在要綁定的 Beeper 聊天中傳送下方配對文字，插件便會保存該聊天室。",
        json_schema_extra={"label": "啟用訊息配對", "order": 1},
    )
    pairing_phrase: str = Field(
        default="#MaiBot配對",
        min_length=4,
        max_length=100,
        description="必須整則訊息完全相同。建議自行加上幾個數字，避免別人碰巧傳出相同文字。",
        json_schema_extra={
            "label": "配對文字",
            "placeholder": "例如：#MaiBot配對5827",
            "order": 2,
        },
    )
    unpairing_phrase: str = Field(
        default="#MaiBot取消配對",
        min_length=4,
        max_length=100,
        description="配對模式開啟時，在已配對聊天傳送這段完整文字，可移除插件保存的配對。",
        json_schema_extra={
            "label": "取消配對文字",
            "placeholder": "例如：#MaiBot取消配對",
            "order": 3,
        },
    )

    @field_validator("allowed_chat_names", mode="before")
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

    @field_validator("unpairing_phrase", mode="before")
    @classmethod
    def normalize_unpairing_phrase(cls, value: Any) -> str:
        return str(value or "#MaiBot取消配對").strip()


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
    discovery: DiscoverySection = Field(default_factory=DiscoverySection)
    reliability: ReliabilitySection = Field(default_factory=ReliabilitySection)
