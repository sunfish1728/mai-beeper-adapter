from __future__ import annotations

import base64
from collections.abc import Mapping
from datetime import datetime
from typing import Any

from .settings import BEEPER_ACCOUNT_ID, BEEPER_CONNECTION_ID


def _timestamp_seconds(value: Any) -> str:
    if isinstance(value, (int, float)):
        numeric = float(value)
        if numeric > 10_000_000_000:
            numeric /= 1000.0
        return str(numeric)
    text = str(value or "").strip()
    if text:
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
            return str(parsed.timestamp())
        except ValueError:
            pass
    return str(datetime.now().timestamp())


def should_ignore_message(message: Mapping[str, Any], allowed_chat_ids: set[str]) -> bool:
    chat_id = str(message.get("chatID") or "").strip()
    return (
        not chat_id
        or chat_id not in allowed_chat_ids
        or bool(message.get("isSender"))
        or bool(message.get("isDeleted"))
        or bool(message.get("isHidden"))
        or not str(message.get("id") or "").strip()
    )


def attachment_label(attachment: Mapping[str, Any]) -> str:
    file_name = str(attachment.get("fileName") or "").strip()
    kind = str(attachment.get("type") or "file").strip().lower()
    labels = {
        "audio": "音訊",
        "voice": "語音",
        "video": "影片",
        "unknown": "附件",
        "file": "檔案",
    }
    label = labels.get(kind, "附件")
    return f"[{label}: {file_name}]" if file_name else f"[{label}]"


def build_message_dict(
    message: Mapping[str, Any],
    chat: Mapping[str, Any],
    image_segments: list[dict[str, Any]],
    image_failures: int = 0,
    voice_segments: list[dict[str, Any]] | None = None,
    voice_failures: int = 0,
) -> dict[str, Any]:
    message_id = str(message.get("id") or "").strip()
    chat_id = str(message.get("chatID") or chat.get("id") or "").strip()
    sender_id = str(message.get("senderID") or "unknown").strip() or "unknown"
    sender_name = str(message.get("senderName") or sender_id).strip() or sender_id
    account_id = str(message.get("accountID") or chat.get("accountID") or "").strip()
    chat_type = str(chat.get("type") or "single").strip().lower()
    chat_title = str(chat.get("title") or chat_id).strip() or chat_id
    text = str(message.get("text") or "")
    raw_message: list[dict[str, Any]] = []

    linked_id = str(message.get("linkedMessageID") or "").strip()
    if linked_id:
        raw_message.append({"type": "reply", "data": {"target_message_id": linked_id}})
    if text:
        raw_message.append({"type": "text", "data": text})
    raw_message.extend(image_segments)
    voice_segments = voice_segments or []
    raw_message.extend(voice_segments)
    voice_successes = len(voice_segments)

    plain_parts = [text] if text else []
    attachments = message.get("attachments")
    if isinstance(attachments, list):
        for attachment in attachments:
            if not isinstance(attachment, Mapping):
                continue
            kind = str(attachment.get("type") or "").lower()
            if kind == "img" and image_failures <= 0:
                continue
            if kind == "img":
                failure_label = "[圖片載入失敗]"
                plain_parts.append(failure_label)
                raw_message.append({"type": "text", "data": failure_label})
                image_failures -= 1
            elif _is_audio_attachment(attachment) and voice_successes > 0:
                plain_parts.append(attachment_label(attachment))
                voice_successes -= 1
                continue
            elif _is_audio_attachment(attachment) and voice_failures > 0:
                failure_label = "[音訊載入失敗]"
                plain_parts.append(failure_label)
                raw_message.append({"type": "text", "data": failure_label})
                voice_failures -= 1
            else:
                label = attachment_label(attachment)
                plain_parts.append(label)
                raw_message.append({"type": "text", "data": label})

    if not raw_message:
        raw_message.append({"type": "text", "data": "[不支援的訊息]"})
        plain_parts.append("[不支援的訊息]")

    additional_config = {
        "self_id": BEEPER_ACCOUNT_ID,
        "platform_io_account_id": BEEPER_ACCOUNT_ID,
        "platform_io_scope": BEEPER_CONNECTION_ID,
        "beeper_chat_id": chat_id,
        "beeper_account_id": account_id,
        "beeper_network": str(chat.get("network") or "").strip(),
        "beeper_chat_type": chat_type,
        "platform_io_target_chat_id": chat_id,
    }
    message_info: dict[str, Any] = {
        "user_info": {
            "user_id": sender_id,
            "user_nickname": sender_name,
            "user_cardname": None,
        },
        "additional_config": additional_config,
    }
    if chat_type == "group":
        message_info["group_info"] = {"group_id": chat_id, "group_name": chat_title}
        additional_config["platform_io_target_group_id"] = chat_id
    else:
        additional_config["platform_io_target_user_id"] = chat_id

    plain_text = "\n".join(part for part in plain_parts if part).strip()
    return {
        "message_id": message_id,
        "timestamp": _timestamp_seconds(message.get("timestamp")),
        "platform": "beeper",
        "message_info": message_info,
        "raw_message": raw_message,
        "is_mentioned": False,
        "is_at": False,
        "is_emoji": False,
        "is_picture": bool(image_segments),
        "is_command": text.lstrip().startswith("/"),
        "is_notify": False,
        "session_id": "",
        "processed_plain_text": plain_text,
    }


def make_image_segment(data: bytes, mime_type: str, file_name: str = "") -> dict[str, Any]:
    return {
        "type": "image",
        "data": {"mime_type": mime_type, "file_name": file_name},
        "binary_data_base64": base64.b64encode(data).decode("ascii"),
    }


def make_voice_segment(
    data: bytes,
    mime_type: str,
    file_name: str = "",
    *,
    is_voice_note: bool = False,
    duration: float | None = None,
) -> dict[str, Any]:
    segment_data: dict[str, Any] = {
        "mime_type": mime_type,
        "file_name": file_name,
        "is_voice_note": is_voice_note,
    }
    if duration is not None:
        segment_data["duration"] = duration
    return {
        "type": "voice",
        "data": segment_data,
        "binary_data_base64": base64.b64encode(data).decode("ascii"),
    }


def _is_audio_attachment(attachment: Mapping[str, Any]) -> bool:
    kind = str(attachment.get("type") or "").strip().lower()
    mime_type = str(attachment.get("mimeType") or attachment.get("mime_type") or "").strip().lower()
    return kind in {"audio", "voice"} or mime_type.startswith("audio/") or bool(attachment.get("isVoiceNote"))
