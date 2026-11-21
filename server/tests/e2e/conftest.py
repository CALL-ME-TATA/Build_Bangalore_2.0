"""Fixtures for the end-to-end tests: a running mock Gnani server and helpers to script it."""
from __future__ import annotations

import httpx
import pytest_asyncio

from mock_gnani.testing import start_mock


class MockHandle:
    def __init__(self, base_url: str) -> None:
        self.base_url = base_url
        self.ws_url = "ws" + base_url[4:]
        self._http = httpx.AsyncClient(base_url=base_url)

    async def reset(self) -> None:
        await self._http.post("/__mock/reset")

    async def script(self, **body) -> None:
        r = await self._http.post("/__mock/script", json=body)
        r.raise_for_status()

    async def log(self) -> dict:
        r = await self._http.get("/__mock/log")
        return r.json()

    async def aclose(self) -> None:
        await self._http.aclose()


@pytest_asyncio.fixture
async def mock():
    base_url, stop = await start_mock()
    handle = MockHandle(base_url)
    try:
        yield handle
    finally:
        await handle.aclose()
        await stop()
