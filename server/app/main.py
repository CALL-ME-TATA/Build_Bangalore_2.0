"""FastAPI application: /ws/session, the REST endpoints and the static web app.

Run from server/: `python -m uvicorn app.main:app --port 8000`. The ledger opens when the app starts, not at import.
"""
from __future__ import annotations

import asyncio
import hmac
import logging
import os
import time
from contextlib import asynccontextmanager
from dataclasses import fields
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import Depends, FastAPI, Header, HTTPException, Request, WebSocket
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from . import auth as auth_mod
from .admin import purge as purge_files
from .config import Settings, get_settings
from .crypto import Crypto, load_key
from .gnani.stt import SttClient
from .gnani.tts import TtsClient
from .gnani.tts import _memory_cache as tts_memory_cache
from .ledger import Ledger, in_quiet_hours
from .llm import from_settings as from_llm_settings
from .logsafe import NoDebug, StripQuery
from .pipeline import ParseFn, Pipeline, default_parse, warm_default_parser
from .replies import NumberToWords, Replier, fixed_replies
from .session import AppContext, Session

log = logging.getLogger("khata.main")

REPO = Path(__file__).resolve().parents[2]
WEB_DIR = REPO / "web"
DIST_DIR = REPO / "frontend" / "dist"
PLACEHOLDER = """<!doctype html><meta charset="utf-8"><title>KhataVaani</title>
<h1>KhataVaani server is running</h1><p>The web app is not installed yet. Session endpoint: /ws/session</p>"""


def pick_web_dir(settings: Settings) -> Path:
    """WEB_DIR when set; else frontend/dist when it holds a build (index.html); else web/."""
    if settings.web_dir:
        p = Path(settings.web_dir)
        return p if p.is_absolute() else REPO / p
    if (DIST_DIR / "index.html").exists():
        return DIST_DIR
    return WEB_DIR


async def prewarm(settings: Settings, replier: Replier, tts_factory) -> int:
    """Synthesise the fixed replies of both languages into the audio cache when their audio is missing.

    Returns how many replies were synthesised. Failures are logged by type only and stop the run."""
    tts = tts_factory(settings)
    done = 0
    try:
        for lang in ("hi", "en"):
            for reply in fixed_replies(replier.with_lang(lang)):
                if tts.cached(reply.speak, lang) is not None:
                    continue
                async for _ in tts.synth(reply.speak, persist=True, lang=lang):
                    pass
                done += 1
    except Exception as exc:
        log.warning("tts prewarm stopped: %s", type(exc).__name__)
    finally:
        await tts.close()
    return done


def prewarm_enabled(settings: Settings) -> bool:
    """On when a key is set and TTS_PREWARM is on. Inside a test run only when the test sets TTS_PREWARM itself."""
    in_test = "PYTEST_CURRENT_TEST" in os.environ
    return bool(settings.tts_prewarm and settings.gnani_api_key and (not in_test or settings.tts_prewarm_explicit))


_NO_DEBUG = NoDebug()
_STRIP_QUERY = StripQuery()
FRAME_LOGGERS = ("websockets", "websockets.client", "websockets.server", "websockets.protocol", "uvicorn.error")


def quiet_library_loggers() -> None:
    """Keep customer names, transcripts and amounts out of library logs (P05).

    The websockets library logs upgrade headers (the STT keyterms hold customer names) and every frame at DEBUG
    level, and uvicorn routes the browser socket's frames (transcripts, replies) through `uvicorn.error`. Those
    loggers are set to WARNING and get a filter that drops DEBUG records even when someone lowers the level."""
    for name in FRAME_LOGGERS:
        logger = logging.getLogger(name)
        if name != "uvicorn.error":
            logger.setLevel(logging.WARNING)
        if _NO_DEBUG not in logger.filters:
            logger.addFilter(_NO_DEBUG)
    # The page URL can carry the access code as `?code=`: access records never show a query string.
    access = logging.getLogger("uvicorn.access")
    if _STRIP_QUERY not in access.filters:
        access.addFilter(_STRIP_QUERY)


def origin_allowed(origin: str | None, host: str | None, extra: str = "") -> bool:
    """Browser origins allowed on /ws/session: the page's own host, localhost, and ALLOWED_ORIGINS.

    A client that sends no Origin header is not a browser page and is allowed (the access code still applies)."""
    if not origin:
        return True
    parsed = urlsplit(origin)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return False
    if host and parsed.netloc.lower() == host.lower():
        return True
    if parsed.hostname in ("localhost", "127.0.0.1", "::1"):
        return True
    allowed = {o.strip().rstrip("/").lower() for o in extra.split(",") if o.strip()}
    return origin.rstrip("/").lower() in allowed


def create_app(settings: Settings | None = None, *, parse: ParseFn | None = None,
               number_to_words: NumberToWords | None = None, stt_factory=None, tts_factory=None,
               now=None, web_dir: Path | None = None) -> FastAPI:
    """Build the app. Parser, number-to-words, Gnani client factories and the clock can be injected for tests."""
    cfg = settings or get_settings()
    quiet_library_loggers()
    web = web_dir or pick_web_dir(cfg)
    holder: dict[str, AppContext] = {}

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        quiet_library_loggers()  # again after the server has applied its own logging config
        if settings is None:
            # Settings read from the environment are read again at start-up, so an app object built at import
            # time serves with the environment of the moment it starts (the route handlers share `cfg`).
            fresh = get_settings()
            for f in fields(cfg):
                setattr(cfg, f.name, getattr(fresh, f.name))
        ledger = Ledger(cfg.db_path, Crypto(load_key(cfg.ledger_key, cfg.key_path)))
        llm_parse = from_llm_settings(default_parse, cfg) if parse is None else None
        pipeline = Pipeline(ledger, cfg, parse=parse or llm_parse, number_to_words=number_to_words, now=now)
        if parse is None:
            warm_default_parser()  # the vocabulary loads lazily; load it before the first turn
        holder["ctx"] = AppContext(
            settings=cfg, ledger=ledger, pipeline=pipeline,
            stt_factory=stt_factory or (lambda s, kt: SttClient(s, kt)),
            tts_factory=tts_factory or (lambda s: TtsClient(s)))
        app.state.ctx = holder["ctx"]
        warm_task = None
        if prewarm_enabled(cfg):
            warm_task = asyncio.create_task(prewarm(cfg, pipeline.replies, holder["ctx"].tts_factory))
        try:
            yield
        finally:
            if warm_task is not None and not warm_task.done():
                warm_task.cancel()
            ledger.close()

    app = FastAPI(title="KhataVaani", lifespan=lifespan)

    def ctx() -> AppContext:
        return holder["ctx"]

    def session_secret() -> bytes:
        if "secret" not in holder:
            holder["secret"] = auth_mod.load_secret(cfg.session_secret, cfg.session_key_path)  # type: ignore[assignment]
        return holder["secret"]  # type: ignore[return-value]

    def signed_in(cookies) -> dict | None:
        return auth_mod.verify(cookies.get(auth_mod.SESSION_COOKIE), session_secret())

    def redirect_uri(request: Request) -> str:
        base = cfg.public_url or str(request.base_url).rstrip("/")
        return base + auth_mod.CALLBACK_PATH

    async def require_access(request: Request, x_access_code: str | None = Header(default=None)) -> None:
        """With Google sign-in on, REST data endpoints need a signed-in, allowed user. When ACCESS_CODE is set,
        they also need it as X-Access-Code or ?code=."""
        if cfg.auth_enabled and signed_in(request.cookies) is None:
            raise HTTPException(401, "sign in required")
        if not cfg.access_code:
            return
        given = x_access_code or request.query_params.get("code") or ""
        if not hmac.compare_digest(given, cfg.access_code):
            raise HTTPException(401, "access code required")

    guarded = [Depends(require_access)]

    # ---- Google sign-in ---------------------------------------------------------------------------------------
    @app.get("/api/auth/me")
    async def auth_me(request: Request):
        user = signed_in(request.cookies) if cfg.auth_enabled else None
        return {"enabled": cfg.auth_enabled,
                "user": {k: user.get(k) for k in ("email", "name", "picture")} if user else None}

    @app.get("/api/auth/google/login")
    async def auth_login(request: Request):
        if not cfg.auth_enabled:
            raise HTTPException(404, "Google sign-in is not configured")
        state = auth_mod.new_state()
        resp = RedirectResponse(auth_mod.login_url(cfg.google_client_id, redirect_uri(request), state), 302)
        resp.set_cookie(auth_mod.STATE_COOKIE, auth_mod.sign({"s": state, "exp": time.time() + auth_mod.STATE_TTL_S},
                                                             session_secret()),
                        max_age=auth_mod.STATE_TTL_S, httponly=True, samesite="lax",
                        secure=redirect_uri(request).startswith("https://"), path="/api/auth")
        return resp

    @app.get("/api/auth/google/callback")
    async def auth_callback(request: Request, code: str = "", state: str = "", error: str = ""):
        if not cfg.auth_enabled:
            raise HTTPException(404, "Google sign-in is not configured")
        saved = auth_mod.verify(request.cookies.get(auth_mod.STATE_COOKIE), session_secret())
        if error or not code or not saved or not hmac.compare_digest(str(saved.get("s", "")), state):
            return RedirectResponse("/#/welcome?login=failed", 302)  # cancelled, replayed or forged
        try:
            info = await auth_mod.exchange(code, redirect_uri(request), cfg.google_client_id, cfg.google_client_secret)
        except Exception as exc:  # Google unreachable or the code was rejected
            log.warning("google sign-in failed: %s", type(exc).__name__)
            return RedirectResponse("/#/welcome?login=failed", 302)
        email = str(info.get("email") or "")
        if not info.get("email_verified") or not auth_mod.allowed(email, cfg.allowed_emails):
            resp = RedirectResponse("/#/welcome?login=not_allowed", 302)
            resp.delete_cookie(auth_mod.STATE_COOKIE, path="/api/auth")
            return resp
        user = {"email": email, "name": str(info.get("name") or ""), "picture": str(info.get("picture") or ""),
                "exp": time.time() + auth_mod.SESSION_TTL_S}
        resp = RedirectResponse("/#/", 302)
        resp.set_cookie(auth_mod.SESSION_COOKIE, auth_mod.sign(user, session_secret()), max_age=auth_mod.SESSION_TTL_S,
                        httponly=True, samesite="lax", secure=redirect_uri(request).startswith("https://"), path="/")
        resp.delete_cookie(auth_mod.STATE_COOKIE, path="/api/auth")
        return resp

    @app.post("/api/auth/logout")
    async def auth_logout():
        resp = JSONResponse({"ok": True})
        resp.delete_cookie(auth_mod.SESSION_COOKIE, path="/")
        return resp

    @app.get("/api/health")
    async def health():
        return {"ok": True, "stt_model": "prisma-v3.0", "tts_model": "timbre-v3.0"}

    @app.get("/api/ledger", dependencies=guarded)
    async def ledger_view(limit: int = 50, order: str = "created", customer_id: str | None = None):
        """Entries newest first: `order=created` (audit order, default) or `order=date` (effective date)."""
        c = ctx()
        today = c.pipeline.now().date()
        if order not in ("created", "date"):
            raise HTTPException(400, "order must be created or date")
        return {"entries": c.ledger.recent_entries(max(1, min(limit, 500)), order=order, customer_id=customer_id),
                "totals": {"credit_today": c.ledger.credit_total(today),
                           "payment_today": c.ledger.payment_total(today)}}

    @app.get("/api/metrics", dependencies=guarded)
    async def metrics():
        return ctx().ledger.metrics()

    @app.get("/api/customers", dependencies=guarded)
    async def customers():
        return {"customers": ctx().ledger.customer_summaries()}

    def reminder_text(name: str, amount: int, lang: str) -> str:
        return ctx().pipeline.replies.with_lang(lang).reminder_message(name, amount)

    @app.get("/api/reminders", dependencies=guarded)
    async def reminders():
        """Pending reminders, rebuilt from the current balance, with their wa.me links (opted-in customers only)."""
        c = ctx()
        now = c.pipeline.now()
        if in_quiet_hours(now):
            return {"reminders": [], "quiet_hours": True}
        return {"reminders": c.ledger.outbox(now, reminder_text), "quiet_hours": False}

    @app.post("/api/reminders/queue", dependencies=guarded)
    async def queue_reminders():
        c = ctx()
        now = c.pipeline.now()
        if in_quiet_hours(now):
            return {"queued": [], "quiet_hours": True}
        return {"queued": c.ledger.queue_reminders(now), "quiet_hours": False}

    @app.post("/api/customers/{customer_id}/reminders", dependencies=guarded)
    async def set_opt_in(customer_id: str, body: dict):
        c = ctx()
        lang = body.get("lang")
        if lang is not None and lang not in ("hi", "en"):
            raise HTTPException(400, "lang must be hi or en")
        ok = c.ledger.set_reminder_opt_in(customer_id, bool(body.get("opt_in")), body.get("phone"),
                                          now=c.pipeline.now())
        if not ok:
            raise HTTPException(404, "unknown customer")
        if lang is not None:
            c.ledger.update_customer(customer_id, lang=lang)
        return {"ok": True}

    @app.post("/api/customers/{customer_id}", dependencies=guarded)
    async def update_customer(customer_id: str, body: dict):
        """Set the optional pronunciation `say` (spoken in place of the display name) or the reminder `lang`."""
        say = body.get("say")
        lang = body.get("lang")
        if say is not None and (not isinstance(say, str) or len(say) > 80):
            raise HTTPException(400, "say must be a short string")
        if lang is not None and lang not in ("hi", "en"):
            raise HTTPException(400, "lang must be hi or en")
        if not ctx().ledger.update_customer(customer_id, say=say, lang=lang):
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
        try:
            removed = purge_files(cfg)
        except OSError as exc:
            raise HTTPException(500, f"purge failed: {type(exc).__name__}") from exc
        finally:
            c.ledger.open()
        tts_memory_cache.clear()
        c.registry.clear()
        return {"ok": True, "removed": removed}

    @app.websocket("/ws/session")
    async def ws_session(ws: WebSocket):
        if not origin_allowed(ws.headers.get("origin"), ws.headers.get("host"), cfg.allowed_origins):
            await ws.close(code=1008)  # refused before the handshake completes (HTTP 403)
            return
        if cfg.auth_enabled and signed_in(ws.cookies) is None:
            await ws.close(code=1008)  # not signed in with an allowed Google account
            return
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
