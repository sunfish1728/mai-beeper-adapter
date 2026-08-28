from __future__ import annotations

import pytest
from aiohttp import web

from mai_beeper_adapter.client import BeeperAPIError, BeeperClient


@pytest.fixture
async def api_server(unused_tcp_port: int):
    requests = []

    async def info(request: web.Request) -> web.Response:
        requests.append(request)
        if request.headers.get("Authorization") != "Bearer good-token":
            return web.json_response({"error": "unauthorized"}, status=401)
        return web.json_response(
            {
                "app": {"name": "Beeper", "version": "4.2.808"},
                "endpoints": {"ws_events": f"ws://127.0.0.1:{unused_tcp_port}/v1/ws"},
            }
        )

    async def messages(request: web.Request) -> web.Response:
        requests.append(request)
        return web.json_response({"items": [], "hasMore": False, "newestCursor": "cursor-1"})

    async def search_chats(request: web.Request) -> web.Response:
        requests.append(request)
        return web.json_response({"items": [{"id": "chat-1", "title": request.query.get("query")}], "hasMore": False})

    app = web.Application()
    app.router.add_get("/v1/info", info)
    app.router.add_get("/v1/chats/search", search_chats)
    app.router.add_get("/v1/chats/{chat_id}/messages", messages)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", unused_tcp_port)
    await site.start()
    try:
        yield f"http://127.0.0.1:{unused_tcp_port}", requests
    finally:
        await runner.cleanup()


@pytest.mark.asyncio
async def test_client_auth_and_message_query_shape(api_server) -> None:
    base_url, requests = api_server
    client = BeeperClient(base_url, "good-token", 3)
    try:
        info = await client.get_info()
        assert info["app"]["name"] == "Beeper"
        result = await client.list_messages("!room:example", cursor="opaque", direction="after")
        assert result["newestCursor"] == "cursor-1"
        message_request = requests[-1]
        assert message_request.match_info["chat_id"] == "!room:example"
        assert message_request.query == {"direction": "after", "cursor": "opaque"}
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_client_replaces_auth_error_with_clear_message(api_server) -> None:
    base_url, _ = api_server
    client = BeeperClient(base_url, "bad-token", 3)
    try:
        with pytest.raises(BeeperAPIError, match="Access Token 無效") as caught:
            await client.get_info()
        assert caught.value.status == 401
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_client_searches_chat_titles_with_bounded_result(api_server) -> None:
    base_url, requests = api_server
    client = BeeperClient(base_url, "good-token", 3)
    try:
        result = await client.search_chats("家人群組", limit=20)
        assert result["items"][0]["id"] == "chat-1"
        search_request = requests[-1]
        assert search_request.query == {
            "query": "家人群組",
            "scope": "titles",
            "type": "any",
            "limit": "20",
        }
    finally:
        await client.close()
