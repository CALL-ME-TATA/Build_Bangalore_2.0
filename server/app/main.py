"""FastAPI application: /ws/session, the REST endpoints and the static web app.

Run from server/: `python -m uvicorn app.main:app --port 8000`. The ledger opens when the app starts, not at import.
"""
from __future__ import annotations

import hmac
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException, WebSocket
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from .admin import purge as purge_files
from .config import Settings, get_settings
from .crypto import Crypto, load_key
from .gnani.stt import SttClient
from .gnani.tts import TtsClient, _memory_cache as tts_memory_cache
from .ledger import Ledger
from .pipeline import ParseFn, Pipeline
from .replies import NumberToWords
from .session import AppContext, Session

log = logging.getLogger("khata.main")

WEB_DIR = Path(__file__).resolve().parents[2] / "web"
PLACEHOLDER = """<!doctype html><meta charset="utf-8"><title>KhataVaani</title>
<h1>KhataVaani server is running</h1><p>The web app is not installed yet. Session endpoint: /ws/session</p>"""


def create_app(settings: Settings | None = None, *, parse: ParseFn | None = None,
               number_to_words: NumberToWords | None = None, stt_factory=None, tts_factory=None,
               now=None, web_dir: Path | None = None) -> FastAPI:
    """Build the app. Parser, number-to-words, Gnani client factories and the clock can be injected for tests."""
    cfg = settings or get_settings()
    web = web_dir or WEB_DIR
    holder: dict[str, AppContext] = {}

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        ledger = Ledger(cfg.ledger_db, Crypto(load_key(cfg.ledger_key, cfg.key_path)))
        pipeline = Pipeline(ledger, cfg, parse=parse, number_to_words=number_to_words, now=now)
        holder["ctx"] = AppContext(
            settings=cfg, ledger=ledger, pipeline=pipeline,
            stt_factory=stt_factory or (lambda s, kt: SttClient(s, kt)),
            tts_factory=tts_factory or (lambda s: TtsClient(s)))
        app.state.ctx = holder["ctx"]
        try:
            yield
        finally:
            ledger.close()

    app = FastAPI(title="KhataVaani", lifespan=lifespan)

    def ctx() -> AppContext:
        return holder["ctx"]

    @app.get("/api/health")
    async def health():
        return {"ok": True, "stt_model": "prisma-v3.0", "tts_model": "timbre-v3.0"}

    @app.get("/api/ledger")
    async def ledger_view(limit: int = 50):
        c = ctx()
        today = c.pipeline.now().date()
        return {"entries": c.ledger.recent_entries(max(1, min(limit, 500))),
                "totals": {"credit_today": c.ledger.credit_total(today),
                           "payment_today": c.ledger.payment_total(today)}}

    @app.get("/api/customers")
    async def customers():
        return {"customers": ctx().ledger.customer_summaries()}

    @app.get("/api/reminders")
    async def reminders():
        """Pending reminder outbox rows with their wa.me links (opted-in customers only)."""
        return {"reminders": ctx().ledger.outbox("pending")}

    @app.post("/api/reminders/queue")
    async def queue_reminders():
        c = ctx()
        ids = c.ledger.queue_reminders(c.pipeline.now(), c.pipeline.replies.reminder)
        return {"queued": ids}

    @app.post("/api/customers/{customer_id}/reminders")
    async def set_opt_in(customer_id: str, body: dict):
        ok = ctx().ledger.set_reminder_opt_in(customer_id, bool(body.get("opt_in")), body.get("phone"))
        if not ok:
            raise HTTPException(404, "unknown customer")
        return {"ok": True}

    @app.post("/api/admin/purge")
    async def admin_purge(x_admin_token: str | None = Header(default=None)):
        if not cfg.admin_token:
            raise HTTPException(403, "admin purge is disabled")
        if not hmac.compare_digest(x_admin_token or "", cfg.admin_token):
            raise HTTPException(401, "bad admin token")
        c = ctx()
        c.ledger.close()
        removed = purge_files(cfg)
        tts_memory_cache.clear()
        c.ledger.open()
        c.registry.clear()
        return {"ok": True, "removed": removed}

    @app.websocket("/ws/session")
    async def ws_session(ws: WebSocket):
        await Session(ws, ctx()).run()

    @app.get("/", include_in_schema=False)
    async def index():
        page = web / "index.html"
        if page.exists():
            return FileResponse(page)
        return HTMLResponse(PLACEHOLDER)

    app.mount("/", StaticFiles(directory=str(web), check_dir=False), name="web")
    return app


def _build() -> FastAPI:
    logging.basicConfig(level=logging.INFO)
    return create_app()


app = _build()
