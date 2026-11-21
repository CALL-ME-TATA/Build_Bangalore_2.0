"""Helpers that start an ASGI app on a free local port inside a running event loop."""
from __future__ import annotations

import asyncio
import socket
from collections.abc import Awaitable, Callable

import uvicorn

from .app import create_app


async def serve_app(app, host: str = "127.0.0.1", lifespan: str = "off") -> tuple[str, Callable[[], Awaitable[None]]]:
    """Serve `app` on a free port of `host`. Returns (base_url, stop); base_url looks like http://127.0.0.1:PORT."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind((host, 0))
    sock.listen(128)
    port = sock.getsockname()[1]
    config = uvicorn.Config(app, log_level="warning", lifespan=lifespan)
    server = uvicorn.Server(config)
    task = asyncio.create_task(server.serve(sockets=[sock]))
    while not server.started:
        if task.done():
            task.result()
            raise RuntimeError("server stopped during start-up")
        await asyncio.sleep(0.01)

    async def stop() -> None:
        server.should_exit = True
        try:
            await asyncio.wait_for(task, timeout=5)
        except asyncio.TimeoutError:
            task.cancel()
        sock.close()

    return f"http://{host}:{port}", stop


async def start_mock(host: str = "127.0.0.1") -> tuple[str, Callable[[], Awaitable[None]]]:
    """Start the mock Gnani server and return (base_url, stop)."""
    return await serve_app(create_app(), host)
