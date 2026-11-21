"""Copy of every shop's ledger in a Supabase project (CONTRACT 3.7).

Once at start-up and then every CLOUD_SYNC_INTERVAL_S (default 300 s), each shop's SQLite ledger is pushed to the
Postgres tables of supabase_schema.sql in the project at SUPABASE_URL, through its REST API with the project's
secret key. Rows are copied as stored: names, tags, phone numbers and transcripts stay AES-256-GCM encrypted
(base64) and the ledger key never leaves this machine; amounts, kinds and dates are plain, as in SQLite. Every row
carries `shop`: "default" for the one-shop ledger, else the signed-in account's hashed id (no email address).

- events, utterances and consent_log are append-only: each push starts where the cloud copy ends.
- customers and confusions change in place: all their rows are upserted every time (a shop has few).
- The copy is one-way; nothing is read back into a ledger. The reminder outbox is not copied (it is rebuilt from
  the balances whenever it is read).
- Each ledger is read through its own read-only connection, so the copy never holds the app's write lock.
- Missing tables are created with SUPABASE_ACCESS_TOKEN through the Supabase Management API; without one, the log
  says to run supabase_schema.sql once in the project's SQL editor.
- Failures are logged with the HTTP status and the answer's error code and retried at the next round. The key and
  row contents are never logged.

Run once by hand (from server/): `python -m app.cloud_sync`.
"""
from __future__ import annotations

import base64
import logging
import sqlite3
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Iterator
from urllib.parse import urlsplit

import httpx

log = logging.getLogger("khata.cloud")

SCHEMA_FILE = Path(__file__).with_name("supabase_schema.sql")
MANAGEMENT_API = "https://api.supabase.com"
DEFAULT_SHOP = "default"
BATCH = 500
TIMEOUT_S = 20.0
_MISSING_TABLE_CODES = {"PGRST205", "42P01"}  # PostgREST: table not in the schema cache; Postgres: no relation


class CloudError(Exception):
    """A refused or failed request. `status` is the HTTP status; `code` the answer's error code, when short."""

    def __init__(self, status: int, code: str = ""):
        super().__init__(f"HTTP {status} {code}".strip())
        self.status, self.code = status, code

    @property
    def missing_table(self) -> bool:
        return self.code in _MISSING_TABLE_CODES


@dataclass
class SyncResult:
    at: str = ""
    ok: bool = True
    rows: dict[str, dict[str, int]] = field(default_factory=dict)  # shop -> table -> rows pushed
    errors: dict[str, str] = field(default_factory=dict)  # shop -> error


def shop_ledgers(default_db: Path, data_dir: Path) -> list[tuple[str, Path]]:
    """(shop, database file) for the one-shop ledger and for every signed-in account's ledger (data_dir/users)."""
    out: list[tuple[str, Path]] = []
    if default_db.exists():
        out.append((DEFAULT_SHOP, default_db))
    users = data_dir / "users"
    if users.is_dir():
        for d in sorted(users.iterdir()):
            if d.is_dir() and (d / "khata.db").exists():
                out.append((d.name, d / "khata.db"))
    return out


def project_ref(url: str) -> str | None:
    """`abcd` for https://abcd.supabase.co; None for a self-hosted address."""
    host = urlsplit(url).hostname or ""
    return host.split(".")[0] if host.endswith(".supabase.co") else None


def _b64(blob: Any) -> str:
    return base64.b64encode(bytes(blob or b"")).decode("ascii")


def _cols(cur: sqlite3.Cursor) -> list[str]:
    return [d[0] for d in cur.description]


class CloudSync:
    def __init__(self, url: str, key: str, *, access_token: str = "", transport: httpx.BaseTransport | None = None,
                 clock: Callable[[], datetime] | None = None, management_url: str = MANAGEMENT_API):
        self.url = url.rstrip("/")
        self.key = key
        self.access_token = access_token
        self.management_url = management_url.rstrip("/")
        self._client = httpx.Client(timeout=TIMEOUT_S, transport=transport)
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self.last: SyncResult | None = None

    def close(self) -> None:
        self._client.close()

    # ---- REST ---------------------------------------------------------------------------------------------------
    def _headers(self) -> dict[str, str]:
        headers = {"apikey": self.key, "Content-Type": "application/json"}
        if self.key.startswith("eyJ"):  # a legacy service_role key is a JWT: it goes as a bearer token too
            headers["Authorization"] = f"Bearer {self.key}"
        return headers

    @staticmethod
    def _check(resp: httpx.Response) -> None:
        if resp.status_code < 300:
            return
        code = ""
        try:
            body = resp.json()
            code = str(body.get("code") or "") if isinstance(body, dict) else ""
        except ValueError:
            pass
        raise CloudError(resp.status_code, code if len(code) <= 16 else "")

    def _max(self, table: str, shop: str, column: str) -> Any:
        """The largest `column` of the shop's rows in the cloud copy, or None when it has none."""
        resp = self._client.get(f"{self.url}/rest/v1/{table}", headers=self._headers(),
                                params={"select": column, "shop": f"eq.{shop}", "order": f"{column}.desc",
                                        "limit": "1"})
        self._check(resp)
        rows = resp.json()
        return rows[0][column] if rows else None

    def _upsert(self, table: str, rows: Iterable[dict], conflict: str) -> int:
        n, batch = 0, []
        for row in rows:
            batch.append(row)
            if len(batch) >= BATCH:
                self._post(table, batch, conflict)
                n, batch = n + len(batch), []
        if batch:
            self._post(table, batch, conflict)
            n += len(batch)
        return n

    def _post(self, table: str, batch: list[dict], conflict: str) -> None:
        resp = self._client.post(f"{self.url}/rest/v1/{table}", params={"on_conflict": conflict},
                                 headers={**self._headers(), "Prefer": "resolution=merge-duplicates,return=minimal"},
                                 json=batch)
        self._check(resp)

    # ---- tables -------------------------------------------------------------------------------------------------
    def ensure_schema(self) -> bool:
        """Create the tables through the Management API. False when that is not possible here."""
        ref = project_ref(self.url)
        if not self.access_token or not ref:
            return False
        resp = self._client.post(f"{self.management_url}/v1/projects/{ref}/database/query",
                                 headers={"Authorization": f"Bearer {self.access_token}",
                                          "Content-Type": "application/json"},
                                 json={"query": SCHEMA_FILE.read_text(encoding="utf-8")})
        self._check(resp)
        log.info("cloud sync: created the khata tables in the Supabase project")
        time.sleep(1.0)  # the REST API reloads its schema cache on the notify at the end of the script
        return True

    # ---- one shop -----------------------------------------------------------------------------------------------
    def push_shop(self, shop: str, db: Path) -> dict[str, int]:
        """Push one ledger. Returns the number of rows sent per table."""
        stamp = self._clock().isoformat()
        con = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True, timeout=10)
        try:
            return self._push(con, shop, stamp)
        finally:
            con.close()

    def _rows(self, con: sqlite3.Connection, sql: str, args: tuple, shape: Callable[[dict], dict]) -> Iterator[dict]:
        cur = con.execute(sql, args)
        cols = _cols(cur)
        while True:
            chunk = cur.fetchmany(BATCH)
            if not chunk:
                return
            for r in chunk:
                yield shape(dict(zip(cols, r)))

    def _push(self, con: sqlite3.Connection, shop: str, stamp: str) -> dict[str, int]:
        sent: dict[str, int] = {}
        sent["customers"] = self._upsert("khata_customers", self._rows(
            con, "SELECT id, ident, reminders_opt_in, created_ts FROM customers ORDER BY created_ts, id", (),
            lambda r: {"shop": shop, "id": r["id"], "ident": _b64(r["ident"]),
                       "reminders_opt_in": bool(r["reminders_opt_in"]), "created_ts": r["created_ts"],
                       "synced_at": stamp}), "shop,id")

        last_event = self._max("khata_events", shop, "id") or 0
        sent["events"] = self._upsert("khata_events", self._rows(
            con, "SELECT * FROM events WHERE id > ? ORDER BY id", (int(last_event),),
            lambda r: {"shop": shop, "id": r["id"], "ts": r["ts"], "kind": r["kind"], "customer_id": r["customer_id"],
                       "amount_paise": r["amount_paise"], "effective_date": r["effective_date"],
                       "utterance_id": r.get("utterance_id"), "supersedes_id": r.get("supersedes_id"),
                       "replaces_id": r.get("replaces_id"), "session_id": r.get("session_id"),
                       "trace_id": r.get("trace_id"), "adjustment": r.get("adjustment"), "synced_at": stamp}),
            "shop,id")

        # Utterance ids are not ordered; their time is. Rows at the last copied time are sent again (an upsert).
        last_ts = self._max("khata_utterances", shop, "ts") or ""
        sent["utterances"] = self._upsert("khata_utterances", self._rows(
            con, "SELECT * FROM utterances WHERE ts >= ? ORDER BY ts, id", (last_ts,),
            lambda r: {"shop": shop, "id": r["id"], "ts": r["ts"], "session_id": r.get("session_id"),
                       "body": _b64(r["body"]), "device_ts": r.get("device_ts"), "status": r.get("status"),
                       "action": r.get("action"),
                       "noisy": None if r.get("noisy") is None else bool(r.get("noisy")), "synced_at": stamp}),
            "shop,id")

        last_consent = self._max("khata_consent_log", shop, "id") or 0
        sent["consent_log"] = self._upsert("khata_consent_log", self._rows(
            con, "SELECT * FROM consent_log WHERE id > ? ORDER BY id", (int(last_consent),),
            lambda r: {"shop": shop, "id": r["id"], "ts": r["ts"], "customer_id": r["customer_id"],
                       "opt_in": bool(r["opt_in"]), "synced_at": stamp}), "shop,id")

        sent["confusions"] = self._upsert("khata_confusions", self._rows(
            con, "SELECT heard, meant, n, last_ts FROM confusions ORDER BY heard, meant", (),
            lambda r: {"shop": shop, "heard": r["heard"], "meant": r["meant"], "n": r["n"], "last_ts": r["last_ts"],
                       "synced_at": stamp}), "shop,heard,meant")
        return sent

    # ---- every shop ---------------------------------------------------------------------------------------------
    def sync_all(self, default_db: Path, data_dir: Path) -> SyncResult:
        """Push every shop's ledger. Never raises: failures are logged and kept in the result."""
        result = SyncResult(at=self._clock().isoformat())
        t0 = time.perf_counter()
        schema_tried = False
        for shop, db in shop_ledgers(default_db, data_dir):
            for attempt in (1, 2):
                try:
                    result.rows[shop] = self.push_shop(shop, db)
                    break
                except CloudError as exc:
                    if exc.missing_table and attempt == 1 and not schema_tried:
                        schema_tried = True
                        try:
                            if self.ensure_schema():
                                continue
                        except (CloudError, httpx.HTTPError) as exc2:
                            log.warning("cloud sync: could not create the tables: %s", _describe(exc2))
                        log.warning("cloud sync: the khata tables are missing in Supabase. Run "
                                    "server/app/supabase_schema.sql once in the project's SQL editor, or set "
                                    "SUPABASE_ACCESS_TOKEN so the server creates them.")
                    result.ok = False
                    result.errors[shop] = _describe(exc)
                    break
                except (httpx.HTTPError, sqlite3.Error, OSError) as exc:
                    result.ok = False
                    result.errors[shop] = _describe(exc)
                    break
        for shop, err in result.errors.items():
            log.warning("cloud sync: shop %s not copied: %s", shop, err)
        total = sum(sum(t.values()) for t in result.rows.values())
        log.info("cloud sync: %d shop(s) copied, %d row(s) sent in %.1f s", len(result.rows), total,
                 time.perf_counter() - t0)
        self.last = result
        return result


def _describe(exc: BaseException) -> str:
    return str(exc) if isinstance(exc, CloudError) else type(exc).__name__


def from_settings(cfg: Any, transport: httpx.BaseTransport | None = None) -> CloudSync | None:
    if not getattr(cfg, "cloud_sync_enabled", False):
        return None
    return CloudSync(cfg.supabase_url, cfg.supabase_secret_key, access_token=cfg.supabase_access_token,
                     transport=transport)


def main() -> int:
    """One push of every shop's ledger, with the settings from the environment and `.env`."""
    from .config import get_settings

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    cfg = get_settings()
    sync = from_settings(cfg)
    if sync is None:
        print("SUPABASE_URL and SUPABASE_SECRET_KEY are not both set", file=sys.stderr)
        return 2
    try:
        result = sync.sync_all(cfg.db_path, cfg.data_dir)
    finally:
        sync.close()
    for shop, rows in result.rows.items():
        print(f"{shop}: " + ", ".join(f"{t} {n}" for t, n in rows.items()))
    return 0 if result.ok else 1


if __name__ == "__main__":
    sys.exit(main())
