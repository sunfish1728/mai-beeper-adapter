from __future__ import annotations

from typing import Any
from urllib.parse import quote

from aiohttp import ClientError, ClientSession, ClientTimeout, FormData


class BeeperAPIError(RuntimeError):
    """Beeper Desktop API 回傳錯誤。"""

    def __init__(self, message: str, *, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


class BeeperClient:
    def __init__(self, base_url: str, access_token: str, timeout_seconds: float) -> None:
        self.base_url = base_url.rstrip("/")
        self.access_token = access_token.strip()
        self.timeout_seconds = timeout_seconds
        self.session: ClientSession | None = None

    @property
    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.access_token}"}

    async def start(self) -> None:
        if self.session is None or self.session.closed:
            self.session = ClientSession(
                headers=self.headers,
                timeout=ClientTimeout(total=self.timeout_seconds),
            )

    async def close(self) -> None:
        if self.session is not None and not self.session.closed:
            await self.session.close()
        self.session = None

    async def _json(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        await self.start()
        assert self.session is not None
        url = path if path.startswith(("http://", "https://")) else f"{self.base_url}{path}"
        try:
            async with self.session.request(method, url, **kwargs) as response:
                try:
                    payload = await response.json(content_type=None)
                except Exception:
                    payload = {}
                if response.status >= 400:
                    detail = ""
                    if isinstance(payload, dict):
                        detail = str(payload.get("message") or payload.get("error") or "").strip()
                    if response.status in {401, 403}:
                        detail = "Access Token 無效或沒有權限"
                    raise BeeperAPIError(detail or f"Beeper API 回傳 HTTP {response.status}", status=response.status)
                if not isinstance(payload, dict):
                    raise BeeperAPIError("Beeper API 回傳了無法辨識的資料")
                return payload
        except BeeperAPIError:
            raise
        except TimeoutError as exc:
            raise BeeperAPIError("連線 Beeper API 逾時") from exc
        except ClientError as exc:
            raise BeeperAPIError("無法連線 Beeper Desktop，請確認程式已開啟") from exc

    async def get_info(self) -> dict[str, Any]:
        return await self._json("GET", "/v1/info")

    async def list_chats(self) -> dict[str, Any]:
        return await self._json("GET", "/v1/chats")

    async def search_chats(self, query: str, *, limit: int = 50) -> dict[str, Any]:
        return await self._json(
            "GET",
            "/v1/chats/search",
            params={"query": query, "scope": "titles", "type": "any", "limit": limit},
        )

    async def get_chat(self, chat_id: str) -> dict[str, Any]:
        return await self._json("GET", f"/v1/chats/{quote(chat_id, safe='')}")

    async def list_messages(
        self,
        chat_id: str,
        *,
        cursor: str = "",
        direction: str = "before",
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"direction": direction}
        if cursor:
            params["cursor"] = cursor
        return await self._json(
            "GET",
            f"/v1/chats/{quote(chat_id, safe='')}/messages",
            params=params,
        )

    async def send_message(
        self,
        chat_id: str,
        *,
        text: str = "",
        attachment: dict[str, Any] | None = None,
        reply_to_message_id: str = "",
    ) -> dict[str, Any]:
        body: dict[str, Any] = {}
        if text:
            body["text"] = text
        if attachment:
            body["attachment"] = attachment
        if reply_to_message_id:
            body["replyToMessageID"] = reply_to_message_id
        if not body:
            raise BeeperAPIError("沒有可傳送的文字或圖片")
        return await self._json(
            "POST",
            f"/v1/chats/{quote(chat_id, safe='')}/messages",
            json=body,
        )

    async def upload_file(self, data: bytes, file_name: str, mime_type: str) -> dict[str, Any]:
        await self.start()
        assert self.session is not None
        form = FormData()
        form.add_field("file", data, filename=file_name, content_type=mime_type)
        form.add_field("fileName", file_name)
        form.add_field("mimeType", mime_type)
        payload = await self._json("POST", "/v1/assets/upload", data=form)
        upload_id = str(payload.get("uploadID") or "").strip()
        if not upload_id:
            raise BeeperAPIError(str(payload.get("error") or "Beeper 沒有回傳圖片 uploadID"))
        return payload

    async def download_asset(self, media_url: str) -> str:
        payload = await self._json("POST", "/v1/assets/download", json={"url": media_url})
        source_url = str(payload.get("srcURL") or "").strip()
        if not source_url:
            raise BeeperAPIError(str(payload.get("error") or "Beeper 沒有回傳圖片位置"))
        return source_url

    async def fetch_bytes(self, url: str, *, max_bytes: int = 25 * 1024 * 1024) -> tuple[bytes, str]:
        await self.start()
        assert self.session is not None
        try:
            async with self.session.get(url) as response:
                if response.status >= 400:
                    raise BeeperAPIError(f"下載圖片失敗（HTTP {response.status}）", status=response.status)
                content_length = response.content_length
                if content_length is not None and content_length > max_bytes:
                    raise BeeperAPIError("圖片超過 25 MB，已略過")
                data = await response.content.read(max_bytes + 1)
                if len(data) > max_bytes:
                    raise BeeperAPIError("圖片超過 25 MB，已略過")
                return data, response.headers.get("Content-Type", "application/octet-stream").split(";", 1)[0]
        except BeeperAPIError:
            raise
        except (ClientError, TimeoutError) as exc:
            raise BeeperAPIError("下載圖片失敗") from exc

    async def connect_websocket(self, ws_url: str):
        await self.start()
        assert self.session is not None
        return await self.session.ws_connect(ws_url, heartbeat=30)
