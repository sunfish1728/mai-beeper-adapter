from __future__ import annotations

import base64

from mai_beeper_adapter.converter import build_message_dict, make_image_segment, should_ignore_message


def sample_message(**updates):
    message = {
        "id": "msg-1",
        "accountID": "whatsapp-account",
        "chatID": "chat-1",
        "senderID": "user-1",
        "senderName": "小明",
        "timestamp": "2026-08-28T12:00:00Z",
        "text": "你好",
        "isSender": False,
        "isDeleted": False,
        "isHidden": False,
        "attachments": [],
    }
    message.update(updates)
    return message


def test_filter_ignores_self_deleted_hidden_unlisted_and_invalid_messages() -> None:
    allowed = {"chat-1"}
    assert should_ignore_message(sample_message(), allowed) is False
    assert should_ignore_message(sample_message(isSender=True), allowed) is True
    assert should_ignore_message(sample_message(isDeleted=True), allowed) is True
    assert should_ignore_message(sample_message(isHidden=True), allowed) is True
    assert should_ignore_message(sample_message(chatID="chat-2"), allowed) is True
    assert should_ignore_message(sample_message(id=""), allowed) is True


def test_group_message_mapping_preserves_beeper_chat_target() -> None:
    result = build_message_dict(
        sample_message(linkedMessageID="old-msg"),
        {"id": "chat-1", "title": "測試群", "type": "group", "network": "WhatsApp"},
        [],
    )
    info = result["message_info"]
    assert result["platform"] == "beeper"
    assert info["user_info"]["user_id"] == "user-1"
    assert info["group_info"] == {"group_id": "chat-1", "group_name": "測試群"}
    assert info["additional_config"]["beeper_chat_id"] == "chat-1"
    assert info["additional_config"]["self_id"] == "beeper-desktop"
    assert info["additional_config"]["beeper_account_id"] == "whatsapp-account"
    assert info["additional_config"]["platform_io_target_group_id"] == "chat-1"
    assert result["raw_message"][0] == {"type": "reply", "data": {"target_message_id": "old-msg"}}


def test_private_message_uses_chat_id_not_sender_as_reply_target() -> None:
    result = build_message_dict(
        sample_message(),
        {"id": "chat-1", "title": "小明", "type": "single", "network": "Signal"},
        [],
    )
    additional = result["message_info"]["additional_config"]
    assert "group_info" not in result["message_info"]
    assert additional["platform_io_target_user_id"] == "chat-1"
    assert additional["platform_io_target_user_id"] != "user-1"


def test_image_and_unsupported_attachment_conversion() -> None:
    image = make_image_segment(b"png-data", "image/png", "photo.png")
    result = build_message_dict(
        sample_message(
            text="",
            attachments=[
                {"type": "img", "fileName": "photo.png"},
                {"type": "audio", "fileName": "voice.ogg"},
            ],
        ),
        {"id": "chat-1", "title": "小明", "type": "single"},
        [image],
    )
    assert result["is_picture"] is True
    assert base64.b64decode(result["raw_message"][0]["binary_data_base64"]) == b"png-data"
    assert result["raw_message"][1] == {"type": "text", "data": "[音訊: voice.ogg]"}
    assert "[音訊: voice.ogg]" in result["processed_plain_text"]


def test_failed_image_becomes_text_instead_of_dropping_message() -> None:
    result = build_message_dict(
        sample_message(text="", attachments=[{"type": "img", "fileName": "bad.jpg"}]),
        {"id": "chat-1", "type": "single"},
        [],
        image_failures=1,
    )
    assert result["raw_message"] == [{"type": "text", "data": "[圖片載入失敗]"}]
    assert "[圖片載入失敗]" in result["processed_plain_text"]
