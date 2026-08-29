from __future__ import annotations

import asyncio
import base64
import json
import mimetypes
import random
from collections.abc import Mapping
from pathlib import Path
from typing import Any, ClassVar
from urllib.parse import unquote, urlparse

from aiohttp import WSMsgType
from maibot_sdk import MaiBotPlugin, MessageGateway, PluginConfigBase

from .client import BeeperAPIError, BeeperClient
from .converter import build_message_dict, make_image_segment, make_voice_segment, should_ignore_message
from .settings import BEEPER_ACCOUNT_ID, BEEPER_CONNECTION_ID, GATEWAY_NAME, MaiBeeperSettings


class MaiBeeperAdapterPlugin(MaiBotPlugin):
    """Beeper Desktop API 的 MaiBot 雙向訊息閘道。"""

    config_model: ClassVar[type[PluginConfigBase] | None] = MaiBeeperSettings

    def __init__(self) -> None:
        super().__init__()
        self._client: BeeperClient | None = None
        self._supervisor_task: asyncio.Task[None] | None = None
        self._websocket_task: asyncio.Task[None] | None = None
        self._stop_event: asyncio.Event | None = None
        self._wake_event: asyncio.Event | None = None
        self._ready = False
        self._chat_cache: dict[str, dict[str, Any]] = {}
        self._resolved_name_chat_ids: set[str] = set()
        self._paired_chat_ids: set[str] = set()
        self._pairing_seen_preview_ids: set[str] = set()
        self._pairing_baseline_ready = False
        self._cursors: dict[str, str] = {}
        self._initialized_chats: set[str] = set()

    async def on_load(self) -> None:
        await self._restart()

    async def on_unload(self) -> None:
        await self._stop()

    async def on_config_update(self, scope: str, config_data: dict[str, Any], version: str) -> None:
        if scope != "self":
            return
        self.set_plugin_config(config_data)
        self.ctx.logger.info("Mai Beeper Adapter 設定已更新%s", f"（{version}）" if version else "")
        await self._restart()

    @MessageGateway(
        name=GATEWAY_NAME,
        route_type="duplex",
        platform="beeper",
        protocol="desktop-api-v1",
        description="Beeper Desktop API 雙向訊息閘道",
    )
    async def handle_beeper_gateway(
        self,
        message: dict[str, Any],
        route: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        del metadata, kwargs
        if not self._ready or self._client is None:
            return {"success": False, "error": "Beeper Desktop 尚未連線"}

        try:
            chat_id = self._outbound_chat_id(message, route or {})
            if not chat_id:
                raise BeeperAPIError("找不到這則回覆所屬的 Beeper 聊天")
            if chat_id not in self._allowed_chat_ids():
                raise BeeperAPIError("目標聊天不在 Beeper 白名單中")
            results = await self._send_outbound(chat_id, message)
            external_ids = [
                str(item.get("pendingMessageID") or item.get("messageID") or item.get("id") or "").strip()
                for item in results
            ]
            external_ids = [item for item in external_ids if item]
            return {
                "success": True,
                "external_message_id": external_ids[-1] if external_ids else "",
                "external_message_ids": external_ids,
            }
        except (BeeperAPIError, ValueError, OSError) as exc:
            self.ctx.logger.warning("Beeper 發送失敗: %s", exc)
            return {"success": False, "error": str(exc)}

    def _settings(self) -> MaiBeeperSettings:
        config = self.config
        if not isinstance(config, MaiBeeperSettings):
            return MaiBeeperSettings.model_validate(self.get_plugin_config_data())
        return config

    def _allowed_chat_ids(self) -> set[str]:
        return (
            set(self._settings().beeper.allowed_chat_ids)
            | self._resolved_name_chat_ids
            | self._paired_chat_ids
        )

    async def _restart(self) -> None:
        await self._stop()
        settings = self._settings()
        if not settings.plugin.enabled:
            await self._set_ready(False, reason="插件未啟用")
            return
        if not settings.beeper.access_token.strip():
            self.ctx.logger.warning("Mai Beeper Adapter 尚未填入 Access Token")
            await self._set_ready(False, reason="缺少 Access Token")
            return

        self._stop_event = asyncio.Event()
        self._wake_event = asyncio.Event()
        self._load_state()
        self._supervisor_task = asyncio.create_task(self._supervise(), name="mai-beeper-supervisor")

    async def _stop(self) -> None:
        if self._stop_event is not None:
            self._stop_event.set()
        tasks = [task for task in (self._websocket_task, self._supervisor_task) if task is not None]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._websocket_task = None
        self._supervisor_task = None
        if self._client is not None:
            await self._client.close()
        self._client = None
        if self._ready:
            await self._set_ready(False, reason="連線已停止")

    async def _supervise(self) -> None:
        delay = 2.0
        while self._stop_event is not None and not self._stop_event.is_set():
            settings = self._settings()
            client = BeeperClient(
                settings.beeper.base_url,
                settings.beeper.access_token,
                settings.reliability.request_timeout_seconds,
            )
            self._client = client
            try:
                info = await client.get_info()
                await self._refresh_chat_cache()
                await self._initialize_new_chats()
                await self._set_ready(True, info=info)
                delay = 2.0
                self._websocket_task = asyncio.create_task(
                    self._websocket_loop(self._websocket_url(info)),
                    name="mai-beeper-websocket",
                )
                await self._poll_loop()
            except asyncio.CancelledError:
                raise
            except BeeperAPIError as exc:
                await self._set_ready(False, reason=str(exc))
                self.ctx.logger.warning("Beeper 連線失敗，稍後重試: %s", exc)
            except Exception as exc:
                await self._set_ready(False, reason="未預期的連線錯誤")
                self.ctx.logger.exception("Mai Beeper Adapter 連線工作發生錯誤: %s", exc)
            finally:
                if self._websocket_task is not None:
                    self._websocket_task.cancel()
                    await asyncio.gather(self._websocket_task, return_exceptions=True)
                    self._websocket_task = None
                await client.close()
                if self._client is client:
                    self._client = None

            if self._stop_event is None or self._stop_event.is_set():
                break
            maximum = settings.reliability.max_reconnect_delay_seconds
            wait_seconds = min(delay, maximum) + random.uniform(0, min(1.0, delay / 4))
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=wait_seconds)
            except TimeoutError:
                pass
            delay = min(delay * 2, maximum)

    async def _poll_loop(self) -> None:
        assert self._stop_event is not None
        assert self._wake_event is not None
        while not self._stop_event.is_set():
            if self._settings().discovery.pairing_enabled:
                try:
                    await self._refresh_chat_cache(scan_pairing=True)
                    await self._initialize_new_chats()
                except BeeperAPIError as exc:
                    self.ctx.logger.warning("Beeper 配對掃描暫時失敗，既有聊天室仍會繼續同步: %s", exc)
            for chat_id in sorted(self._allowed_chat_ids()):
                await self._reconcile_chat(chat_id)
            self._wake_event.clear()
            try:
                await asyncio.wait_for(
                    self._wake_event.wait(),
                    timeout=self._settings().reliability.poll_interval_seconds,
                )
            except TimeoutError:
                pass

    async def _websocket_loop(self, ws_url: str) -> None:
        delay = 2.0
        while self._stop_event is not None and not self._stop_event.is_set() and self._client is not None:
            try:
                websocket = await self._client.connect_websocket(ws_url)
                async with websocket:
                    await websocket.send_json(
                        {
                            "type": "subscriptions.set",
                            "requestID": "mai-beeper-subscription",
                            "chatIDs": ["*"]
                            if self._settings().discovery.pairing_enabled
                            else sorted(self._allowed_chat_ids()),
                        }
                    )
                    delay = 2.0
                    async for incoming in websocket:
                        if incoming.type == WSMsgType.TEXT:
                            try:
                                payload = json.loads(incoming.data)
                            except (TypeError, json.JSONDecodeError):
                                continue
                            if payload.get("type") == "message.upserted":
                                chat_id = str(payload.get("chatID") or "").strip()
                                if chat_id in self._allowed_chat_ids() and self._wake_event is not None:
                                    self._wake_event.set()
                            elif payload.get("type") == "error":
                                self.ctx.logger.warning(
                                    "Beeper WebSocket 訂閱錯誤: %s",
                                    str(payload.get("message") or payload.get("code") or "未知錯誤"),
                                )
                        elif incoming.type in {WSMsgType.CLOSE, WSMsgType.CLOSED, WSMsgType.ERROR}:
                            break
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.ctx.logger.info("Beeper 即時通知暫時中斷，REST 補抓仍在運作: %s", exc)

            if self._stop_event is None or self._stop_event.is_set():
                break
            maximum = self._settings().reliability.max_reconnect_delay_seconds
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=min(delay, maximum))
            except TimeoutError:
                pass
            delay = min(delay * 2, maximum)

    async def _refresh_chat_cache(self, *, scan_pairing: bool = False) -> None:
        if self._client is None:
            return
        payload = await self._client.list_chats()
        items = payload.get("items")
        chats: list[dict[str, Any]] = []
        if isinstance(items, list):
            for item in items:
                if isinstance(item, dict) and item.get("id"):
                    chats.append(item)
                    self._chat_cache[str(item["id"])] = item

        if not self._pairing_baseline_ready:
            self._remember_pairing_previews(chats)
            self._pairing_baseline_ready = True
        elif scan_pairing:
            self._scan_pairing_previews(chats)

        if not scan_pairing:
            await self._resolve_named_chats()

        allowed = sorted(self._allowed_chat_ids())
        if not allowed:
            lines: list[str] = []
            for chat in list(self._chat_cache.values())[:30]:
                lines.append(
                    f"- {chat.get('network') or 'Beeper'} | {chat.get('title') or '(無標題)'} | {chat.get('id')}"
                )
            if lines:
                self.ctx.logger.info(
                    "尚未選擇 Beeper 聊天。可填聊天室名稱、開啟訊息配對，或使用以下 chatID:\n%s",
                    "\n".join(lines),
                )
        else:
            for chat_id in allowed:
                if chat_id not in self._chat_cache:
                    try:
                        self._chat_cache[chat_id] = await self._client.get_chat(chat_id)
                    except BeeperAPIError as exc:
                        self.ctx.logger.warning("無法讀取白名單聊天 %s: %s", chat_id, exc)

    async def _resolve_named_chats(self) -> None:
        if self._client is None:
            return
        resolved: set[str] = set()
        for requested_name in self._settings().discovery.allowed_chat_names:
            try:
                payload = await self._client.search_chats(requested_name, limit=50)
            except BeeperAPIError as exc:
                self.ctx.logger.warning("無法依名稱尋找 Beeper 聊天「%s」: %s", requested_name, exc)
                continue
            items = payload.get("items")
            candidates = [item for item in items if isinstance(item, dict)] if isinstance(items, list) else []
            exact = [
                item
                for item in candidates
                if str(item.get("title") or "").strip().casefold() == requested_name.casefold() and item.get("id")
            ]
            if len(exact) == 1:
                chat = exact[0]
                chat_id = str(chat["id"])
                resolved.add(chat_id)
                self._chat_cache[chat_id] = chat
                self.ctx.logger.info("已依名稱找到 Beeper 聊天: %s", self._chat_label(chat_id))
            elif len(exact) > 1:
                self.ctx.logger.warning("Beeper 有 %d 個同名聊天「%s」，請改用訊息配對", len(exact), requested_name)
            else:
                self.ctx.logger.warning("找不到名稱完全相同的 Beeper 聊天「%s」", requested_name)
        self._resolved_name_chat_ids = resolved

    def _remember_pairing_previews(self, chats: list[dict[str, Any]]) -> None:
        for chat in chats:
            preview = chat.get("preview")
            if isinstance(preview, Mapping):
                message_id = str(preview.get("id") or "").strip()
                if message_id:
                    self._pairing_seen_preview_ids.add(message_id)

    def _scan_pairing_previews(self, chats: list[dict[str, Any]]) -> None:
        phrase = self._settings().discovery.pairing_phrase
        unpairing_phrase = self._settings().discovery.unpairing_phrase
        for chat in chats:
            chat_id = str(chat.get("id") or "").strip()
            preview = chat.get("preview")
            if not chat_id or not isinstance(preview, Mapping):
                continue
            message_id = str(preview.get("id") or "").strip()
            if not message_id or message_id in self._pairing_seen_preview_ids:
                continue
            self._pairing_seen_preview_ids.add(message_id)
            text = str(preview.get("text") or "").strip()
            if text == unpairing_phrase and chat_id in self._paired_chat_ids:
                self._paired_chat_ids.remove(chat_id)
                self._initialized_chats.discard(chat_id)
                self._cursors.pop(chat_id, None)
                self._save_state()
                self.ctx.logger.info("Beeper 訊息取消配對成功: %s", self._chat_label(chat_id))
                continue
            if text != phrase:
                continue
            if chat_id not in self._paired_chat_ids:
                self._paired_chat_ids.add(chat_id)
                self._chat_cache[chat_id] = chat
                self._save_state()
                self.ctx.logger.info("Beeper 訊息配對成功: %s", self._chat_label(chat_id))

    async def _initialize_new_chats(self) -> None:
        if self._client is None:
            return
        changed = False
        for chat_id in sorted(self._allowed_chat_ids()):
            if chat_id in self._initialized_chats:
                continue
            payload = await self._client.list_messages(chat_id, direction="before")
            cursor = str(payload.get("newestCursor") or "").strip()
            if cursor:
                self._cursors[chat_id] = cursor
            self._initialized_chats.add(chat_id)
            changed = True
            self.ctx.logger.info("Beeper 聊天已從目前時間開始監聽: %s", self._chat_label(chat_id))
        if changed:
            self._save_state()

    async def _reconcile_chat(self, chat_id: str) -> None:
        if self._client is None:
            return
        if chat_id not in self._initialized_chats:
            await self._initialize_new_chats()
            return

        cursor = self._cursors.get(chat_id, "")
        direction = "after" if cursor else "before"
        payload = await self._client.list_messages(chat_id, cursor=cursor, direction=direction)
        items = payload.get("items")
        messages = [item for item in items if isinstance(item, dict)] if isinstance(items, list) else []
        messages.sort(key=lambda item: str(item.get("timestamp") or ""))
        for message in messages:
            await self._route_inbound(message)

        newest_cursor = str(payload.get("newestCursor") or "").strip()
        if newest_cursor and newest_cursor != cursor:
            self._cursors[chat_id] = newest_cursor
            self._save_state()

        page_guard = 0
        while cursor and bool(payload.get("hasMore")) and page_guard < 20:
            page_guard += 1
            cursor = self._cursors.get(chat_id, cursor)
            payload = await self._client.list_messages(chat_id, cursor=cursor, direction="after")
            items = payload.get("items")
            messages = [item for item in items if isinstance(item, dict)] if isinstance(items, list) else []
            messages.sort(key=lambda item: str(item.get("timestamp") or ""))
            for message in messages:
                await self._route_inbound(message)
            newest_cursor = str(payload.get("newestCursor") or "").strip()
            if not newest_cursor or newest_cursor == cursor:
                break
            self._cursors[chat_id] = newest_cursor
            self._save_state()

    async def _route_inbound(self, message: dict[str, Any]) -> None:
        allowed = self._allowed_chat_ids()
        if should_ignore_message(message, allowed):
            return
        chat_id = str(message.get("chatID") or "").strip()
        chat = self._chat_cache.get(chat_id)
        if chat is None and self._client is not None:
            try:
                chat = await self._client.get_chat(chat_id)
                self._chat_cache[chat_id] = chat
            except BeeperAPIError:
                chat = {"id": chat_id, "title": chat_id, "type": "single"}

        image_segments: list[dict[str, Any]] = []
        image_failures = 0
        voice_segments: list[dict[str, Any]] = []
        voice_failures = 0
        attachments = message.get("attachments")
        if isinstance(attachments, list):
            for attachment in attachments:
                if not isinstance(attachment, Mapping):
                    continue
                kind = str(attachment.get("type") or "").lower()
                mime_type = str(attachment.get("mimeType") or "").lower()
                is_audio = (
                    kind in {"audio", "voice"}
                    or mime_type.startswith("audio/")
                    or bool(attachment.get("isVoiceNote"))
                )
                if kind == "img":
                    try:
                        image_segments.append(await self._inbound_image_segment(attachment))
                    except (BeeperAPIError, OSError, ValueError) as exc:
                        image_failures += 1
                        self.ctx.logger.warning("Beeper 圖片載入失敗，改用文字提示: %s", exc)
                elif is_audio:
                    try:
                        voice_segments.append(await self._inbound_voice_segment(attachment))
                    except (BeeperAPIError, OSError, ValueError) as exc:
                        voice_failures += 1
                        self.ctx.logger.warning("Beeper 音訊載入失敗，改用文字提示: %s", exc)

        message_dict = build_message_dict(
            message,
            chat or {},
            image_segments,
            image_failures,
            voice_segments,
            voice_failures,
        )
        external_id = f"{chat_id}:{message.get('id')}"
        accepted = await self.ctx.gateway.route_message(
            gateway_name=GATEWAY_NAME,
            message=message_dict,
            route_metadata={
                "self_id": BEEPER_ACCOUNT_ID,
                "connection_id": BEEPER_CONNECTION_ID,
                "chat_id": chat_id,
            },
            external_message_id=external_id,
            dedupe_key=external_id,
        )
        if not accepted:
            self.ctx.logger.debug("MaiBot 未接收 Beeper 訊息: %s", external_id)

    async def _inbound_image_segment(self, attachment: Mapping[str, Any]) -> dict[str, Any]:
        if self._client is None:
            raise BeeperAPIError("Beeper 尚未連線")
        media_url = str(attachment.get("srcURL") or attachment.get("id") or "").strip()
        if not media_url:
            raise BeeperAPIError("圖片缺少下載位置")
        source = media_url
        if media_url.startswith(("mxc://", "localmxc://")):
            source = await self._client.download_asset(media_url)
        data, detected_type = await self._read_media_source(source)
        mime_type = str(attachment.get("mimeType") or detected_type or "image/jpeg").strip()
        file_name = str(attachment.get("fileName") or "image").strip()
        return make_image_segment(data, mime_type, file_name)

    async def _inbound_voice_segment(self, attachment: Mapping[str, Any]) -> dict[str, Any]:
        if self._client is None:
            raise BeeperAPIError("Beeper 尚未連線")
        media_url = str(attachment.get("srcURL") or attachment.get("id") or "").strip()
        if not media_url:
            raise BeeperAPIError("音訊缺少下載位置")
        source = media_url
        if media_url.startswith(("mxc://", "localmxc://")):
            source = await self._client.download_asset(media_url)
        data, detected_type = await self._read_media_source(source, media_label="音訊")
        mime_type = str(attachment.get("mimeType") or detected_type or "audio/ogg").strip()
        file_name = str(attachment.get("fileName") or "voice.ogg").strip()
        duration_value = attachment.get("duration")
        duration = float(duration_value) if isinstance(duration_value, (int, float)) else None
        return make_voice_segment(
            data,
            mime_type,
            file_name,
            is_voice_note=bool(attachment.get("isVoiceNote")),
            duration=duration,
        )

    async def _send_outbound(self, chat_id: str, message: Mapping[str, Any]) -> list[dict[str, Any]]:
        if self._client is None:
            raise BeeperAPIError("Beeper 尚未連線")
        raw_message = message.get("raw_message")
        if not isinstance(raw_message, list):
            raise BeeperAPIError("MaiBot 回覆沒有可傳送的訊息段")

        reply_to = ""
        pending_text: list[str] = []
        results: list[dict[str, Any]] = []
        for item in raw_message:
            if not isinstance(item, Mapping):
                continue
            item_type = str(item.get("type") or "").lower()
            if item_type == "reply":
                data = item.get("data")
                reply_to = str(data.get("target_message_id") if isinstance(data, Mapping) else data or "").strip()
                continue
            if item_type == "text":
                pending_text.append(str(item.get("data") or ""))
                continue
            if item_type not in {"image", "emoji", "voice", "audio"}:
                continue

            is_audio = item_type in {"voice", "audio"}
            media_data, mime_type, file_name = await (
                self._outbound_audio(item) if is_audio else self._outbound_image(item)
            )
            upload = await self._client.upload_file(media_data, file_name, mime_type)
            attachment = {
                "uploadID": str(upload["uploadID"]),
                "fileName": str(upload.get("fileName") or file_name),
                "mimeType": str(upload.get("mimeType") or mime_type),
                "type": "audio" if is_audio else "image",
            }
            if is_audio:
                duration = upload.get("duration")
                if isinstance(duration, (int, float)):
                    attachment["duration"] = duration
            else:
                width = upload.get("width")
                height = upload.get("height")
                if isinstance(width, (int, float)) and isinstance(height, (int, float)):
                    attachment["size"] = {"width": int(width), "height": int(height)}
            results.append(
                await self._client.send_message(
                    chat_id,
                    text="".join(pending_text),
                    attachment=attachment,
                    reply_to_message_id=reply_to,
                )
            )
            pending_text.clear()
            reply_to = ""

        final_text = "".join(pending_text)
        if final_text:
            results.append(
                await self._client.send_message(chat_id, text=final_text, reply_to_message_id=reply_to)
            )
        if not results:
            raise BeeperAPIError("MaiBot 回覆中沒有可傳送的文字、圖片或語音")
        return results

    async def _outbound_image(self, item: Mapping[str, Any]) -> tuple[bytes, str, str]:
        encoded = str(item.get("binary_data_base64") or "").strip()
        data_field = item.get("data")
        mime_type = "image/png"
        file_name = "maibot-image.png"
        source = ""
        if isinstance(data_field, Mapping):
            encoded = encoded or str(data_field.get("binary_data_base64") or data_field.get("base64") or "").strip()
            mime_type = str(data_field.get("mime_type") or data_field.get("mimeType") or mime_type).strip()
            file_name = str(data_field.get("file_name") or data_field.get("fileName") or file_name).strip()
            source = str(data_field.get("file") or data_field.get("path") or data_field.get("url") or "").strip()
        else:
            source = str(data_field or "").strip()
        if encoded.startswith("data:") and ";base64," in encoded:
            header, encoded = encoded.split(",", 1)
            mime_type = header[5:].split(";", 1)[0] or mime_type
        if encoded:
            try:
                return base64.b64decode(encoded, validate=True), mime_type, file_name
            except ValueError as exc:
                raise BeeperAPIError("MaiBot 圖片的 Base64 資料無效") from exc
        if not source:
            raise BeeperAPIError("MaiBot 圖片缺少資料")
        data, detected_type = await self._read_media_source(source)
        mime_type = detected_type or mime_type
        parsed = urlparse(source)
        if parsed.path:
            guessed_name = Path(unquote(parsed.path)).name
            if guessed_name:
                file_name = guessed_name
        return data, mime_type, file_name

    async def _outbound_audio(self, item: Mapping[str, Any]) -> tuple[bytes, str, str]:
        encoded = str(item.get("binary_data_base64") or "").strip()
        data_field = item.get("data")
        mime_type = "audio/wav"
        file_name = "maibot-voice.wav"
        source = ""
        if isinstance(data_field, Mapping):
            encoded = encoded or str(
                data_field.get("binary_data_base64")
                or data_field.get("audio_base64")
                or data_field.get("base64")
                or ""
            ).strip()
            mime_type = str(data_field.get("mime_type") or data_field.get("mimeType") or mime_type).strip()
            file_name = str(data_field.get("file_name") or data_field.get("fileName") or file_name).strip()
            source = str(
                data_field.get("file")
                or data_field.get("path")
                or data_field.get("url")
                or data_field.get("media")
                or ""
            ).strip()
        else:
            source = str(data_field or "").strip()
        if encoded.startswith("data:") and ";base64," in encoded:
            header, encoded = encoded.split(",", 1)
            mime_type = header[5:].split(";", 1)[0] or mime_type
        if encoded:
            try:
                return base64.b64decode(encoded, validate=True), mime_type, file_name
            except ValueError as exc:
                raise BeeperAPIError("MaiBot 語音的 Base64 資料無效") from exc
        if not source:
            raise BeeperAPIError("MaiBot 語音缺少資料")
        data, detected_type = await self._read_media_source(source, media_label="音訊")
        mime_type = detected_type or mime_type
        parsed = urlparse(source)
        if parsed.path:
            guessed_name = Path(unquote(parsed.path)).name
            if guessed_name:
                file_name = guessed_name
        return data, mime_type, file_name

    async def _read_media_source(self, source: str, *, media_label: str = "圖片") -> tuple[bytes, str]:
        parsed = urlparse(source)
        if parsed.scheme in {"http", "https"}:
            if self._client is None:
                raise BeeperAPIError("Beeper 尚未連線")
            return await self._client.fetch_bytes(source)
        path_text = unquote(parsed.path) if parsed.scheme == "file" else source
        if parsed.scheme == "file" and parsed.netloc:
            path_text = f"//{parsed.netloc}{path_text}"
        if len(path_text) >= 3 and path_text[0] == "/" and path_text[2] == ":":
            path_text = path_text[1:]
        path = Path(path_text)
        if not path.is_file():
            raise BeeperAPIError(f"找不到{media_label}檔案")
        if path.stat().st_size > 25 * 1024 * 1024:
            raise BeeperAPIError(f"{media_label}超過 25 MB，已略過")
        return path.read_bytes(), mimetypes.guess_type(path.name)[0] or "application/octet-stream"

    @staticmethod
    def _outbound_chat_id(message: Mapping[str, Any], route: Mapping[str, Any]) -> str:
        message_info = message.get("message_info")
        if not isinstance(message_info, Mapping):
            message_info = {}
        additional = message_info.get("additional_config")
        if not isinstance(additional, Mapping):
            additional = {}
        group = message_info.get("group_info")
        if not isinstance(group, Mapping):
            group = {}
        candidates = (
            additional.get("beeper_chat_id"),
            additional.get("platform_io_target_chat_id"),
            route.get("chat_id"),
            route.get("target_chat_id"),
            group.get("group_id"),
            additional.get("platform_io_target_group_id"),
            additional.get("platform_io_target_user_id"),
        )
        return next((str(value).strip() for value in candidates if str(value or "").strip()), "")

    def _websocket_url(self, info: Mapping[str, Any]) -> str:
        endpoints = info.get("endpoints")
        if isinstance(endpoints, Mapping):
            candidate = str(endpoints.get("ws_events") or "").strip()
            if candidate.startswith(("ws://", "wss://")):
                return candidate
        base_url = self._settings().beeper.base_url
        if base_url.startswith("https://"):
            return f"wss://{base_url.removeprefix('https://')}/v1/ws"
        return f"ws://{base_url.removeprefix('http://')}/v1/ws"

    async def _set_ready(self, ready: bool, *, reason: str = "", info: Mapping[str, Any] | None = None) -> None:
        self._ready = ready
        metadata: dict[str, Any] = {"protocol": "desktop-api-v1"}
        if reason:
            metadata["reason"] = reason
        if info:
            app = info.get("app")
            if isinstance(app, Mapping):
                metadata["beeper_version"] = str(app.get("version") or "")
        try:
            await self.ctx.gateway.update_state(
                gateway_name=GATEWAY_NAME,
                ready=ready,
                platform="beeper",
                account_id=BEEPER_ACCOUNT_ID,
                scope=BEEPER_CONNECTION_ID,
                metadata=metadata,
            )
        except Exception:
            if ready:
                raise

    def _state_path(self) -> Path:
        return Path(self.ctx.paths.data_dir) / "sync_state.json"

    def _load_state(self) -> None:
        self._resolved_name_chat_ids = set()
        self._cursors = {}
        self._initialized_chats = set()
        self._paired_chat_ids = set()
        self._pairing_seen_preview_ids = set()
        self._pairing_baseline_ready = False
        path = self._state_path()
        if not path.is_file():
            return
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            cursors = payload.get("cursors", {})
            initialized = payload.get("initialized_chats", [])
            paired = payload.get("paired_chat_ids", [])
            if isinstance(cursors, dict):
                self._cursors = {
                    str(key): str(value)
                    for key, value in cursors.items()
                    if str(key).strip() and str(value).strip()
                }
            if isinstance(initialized, list):
                self._initialized_chats = {str(item) for item in initialized if str(item).strip()}
            if isinstance(paired, list):
                self._paired_chat_ids = {str(item) for item in paired if str(item).strip()}
        except (OSError, ValueError, TypeError) as exc:
            self.ctx.logger.warning("Beeper 同步狀態無法讀取，將重新建立: %s", exc)

    def _save_state(self) -> None:
        path = self._state_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        payload = {
            "version": 2,
            "cursors": self._cursors,
            "initialized_chats": sorted(self._initialized_chats),
            "paired_chat_ids": sorted(self._paired_chat_ids),
        }
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(path)

    def _chat_label(self, chat_id: str) -> str:
        chat = self._chat_cache.get(chat_id, {})
        title = str(chat.get("title") or "").strip()
        return f"{title} ({chat_id})" if title else chat_id
