# CONTRACT v1 (2026-11-21)

The binding interface specification for KhataVaani. Changes go through the tech lead.
Where this file disagrees with an older note, this file wins.
Sources: the pitch deck, the hackathon brief (rubric summarised in docs/ARCHITECTURE.md), our research notes,
and Gnani's own docs (docs.gnani.ai, read 2026-11-21).

## 0. Scope for the 24-hour build

| Priority | What |
|---|---|
| P0 | Exact amounts in any spoken form; credit vs payment direction; relative dates; spoken correction and undo; same-name question; spoken answers; push-to-talk streaming through Gnani Prisma v3.0 and Timbre v3.0 over WebSocket; AI disclosure in the first turn; barge-in; encrypted data at rest; per-turn latency readout; README |
| P1 | Clarification answers for every question type; new-customer and tag learning; payment_total and top_dues queries; TTS cache; session resume; access code; data purge command; latency harness |
| P2 (only if P0 and P1 are green) | Hands-free mode (server VAD); dual-decode number check; reminders (opt-in, wa.me link); offline app shell; Kannada lexicon; Playwright e2e |
| Cut | Kafka, SQLCipher (blocked on the dev machine), LLM fallback, on-device ledger and sync |

## 1. Parser (`server/nlu/`, pure Python, no I/O, no network, no database)

```python
# nlu/parser.py
def parse(utterance: str, *, today: date, ctx: dict | None = None) -> dict
# nlu/numbers.py
def parse_number(text: str) -> int | None        # whole rupees, or None if the text is not exactly one number phrase
# nlu/speak.py
def number_to_words(n: int, script: str = "deva") -> str   # "deva" | "roman", 0 <= n <= 9_999_999
# nlu/names.py
def name_key(text: str) -> str        # lowercase Roman key from Roman or Devanagari input
def phonetic_key(key: str) -> str     # folded form, used only for matching, never stored as the name
```

Only the standard library and `rapidfuzz` may be imported. `regex` and `indic_transliteration` are blocked on the dev
machine (Windows Application Control); romanise Devanagari with your own table.

### 1.1 `ctx` (every field optional)
| Field | Shape | Meaning |
|---|---|---|
| `last_event` | `{"kind","customer","customer_id"?,"amount","date","age_s"?}` | Most recent active (not reversed) event of this session |
| `customers` | `[{"id","name","tags":[...],"aliases":[...]?}]` | Known customers. `name` is the lowercase Roman key. Absent means "no roster": return keys only |
| `aliases` | `{alias: key}` | Extra alias map (lowercase) |
| `stt_alternatives` | `[str]` | Other transcripts of the same audio. Gnani returns none; filled only by tests or dual-decode |
| `pending` | object | The `pending` value of the previous `needs_clarification` result |
| `limits` | `{"confirm_above": 50000}` | Amounts above this need a spoken confirmation |

### 1.2 Result
```
status:     "ok" | "needs_clarification" | "rejected"
action:     "append" | "amend" | "undo" | "query"                      (status ok)
events:     [{"kind": "credit"|"payment", "customer": "<key>", "amount": <int rupees>, "date": "YYYY-MM-DD",
              "customer_id"?: str, "new_customer"?: true, "tags"?: [str]}]    (append, amend)
target:     "last"                                                     (amend, undo)
query:      {"type": "balance"|"credit_total"|"payment_total"|"daily_summary"|"top_dues",
             "customer"?: key, "customer_id"?: str, "period"?: "today"}
reason:     needs_clarification: "confusable_number"|"same_name"|"plausibility"|"missing_amount"|"missing_customer"|
                                 "ambiguous_direction"|"unclear_correction"|"unclear_date"
            rejected: "not_ledger"|"future"|"negated"|"no_last_event"|"cancelled"|"invalid_number"
candidates: same_name: [{"id","name","tags"}] ; confusable_number: [int, int]
question:   one short spoken question in Roman Hinglish            (needs_clarification)
pending:    {"reason", "action", "events": [partial or full events], "candidates"?}   (needs_clarification)
```
- `credit` means the customer owes more (udhaar). `payment` means the customer paid.
- Never guess. If any clause of an utterance needs clarification, return `needs_clarification` for the whole utterance and
  save nothing; `pending.events` holds every event so the answer can complete them.
- A missing field in a pending event is simply absent (`amount` for missing_amount, `customer` for missing_customer,
  `kind` for ambiguous_direction).
- Extra keys are allowed. Golden tests match `expect` as a subset.

### 1.3 Numbers (rubric: "amounts right in any form")
`parse_number` and the parser must accept all of these, in Roman, Devanagari or mixed script:
- Digits: `340`, `1,500`, `1,25,000`, `₹340`, `Rs 340`, `Rs. 340`, `340/-`, `340 rupaye`, Devanagari digits `३४०`.
- Hindi words 1 to 9,99,999 with unit words sau / hazaar / lakh, in the oracle spelling and its variants
  (ee/i, aa/a, chh/ch, v/w, doubled consonants, nasalisation, trailing h, the r-flap written d or r), the pitch spelling
  (`chaalis`), and the eight older oracle spellings (`unatees`, `unataalees`, `pachhattar`, `satattar`, `athattar`,
  `unnyaasi`, `athaasi`, `nawaasi`). Bare `sau` = 100, bare `hazaar` = 1000. `N sau` with N from 11 to 99 = N x 100
  (`pandrah sau` = 1500).
- Fractions: `sawa` (+1/4, number optional), `saade` (+1/2, needs a number of 3 or more), `paune` (-1/4, number optional),
  `dedh` (1.5, no number), `dhai` (2.5, no number), each followed by sau / hazaar / lakh. Anything that is not a whole
  rupee amount, or an invalid combination (`saade do sau`, `dedh teen sau`, `saade teen` alone), returns None.
- English: `three hundred forty`, `three hundred and forty`, `three forty` and `three-forty` (digit then a two-digit
  number = hundreds), `fifteen hundred`, `one thousand five hundred`, `two fifty`, `one lakh`.
- Build the variant lookup from rules and assert at import or test time that no variant string maps to two numbers.
  Do not fold `th` to `t`, `ei` to `i`, or drop a trailing `i`: `saath` (60) / `saat` (7), `teis` (23) / `tees` (30),
  `pachaas` (50) / `pachaasi` (85) must stay distinct.

### 1.4 Direction (shopkeeper's point of view)
| Pattern | Kind |
|---|---|
| `X ne N diya / diye / de diya`; `X N de gaya`; `X se N mila / mile / liya / aaya`; `X ka N aaya` | payment |
| `N payment mila / aaya / received`; `X ne N payment kiya`; `X ne N jama kiya / karaya`; `X ke jama N likh do` | payment |
| `X ne N chukaya / chuka diya`; `X ne N wapas kiya / diya`; `X ne N UPI / online / cash kiya`; `X ke khate se N kaat do` | payment |
| English `X paid N`, `X gave N`, `received N from X` | payment |
| A bare `N diya / diye (tha)` with no ne/ko, when the customer is carried over (see 1.6) | payment |
| `X ka N udhaar`; `X ko N udhaar (diya)`; `X pe N udhaar`; `X ko N diya / diye / de diya` | credit |
| `X ne N udhaar liya`; `X N (ka saaman) le gaya / le liya`; `X ne N ka saaman liya` | credit |
| `X ke naam N likh do`; `X ke khate mein N likh do / add karo / daal do / chadha do`; `X N likh do` | credit |
| English `X took N (on credit)`, `X owes N` | credit |
| `X ne N udhaar diya`; `X ko N wapas diya`; `X ko N payment kiya`; bare English `credit` / `debit`; `X ko N dene hain`; `X ka N baaki hai`; a name and an amount with no direction word | ask: ambiguous_direction |
| Negated (`nahi diya`, `nahi aaya`) or future (`dega`, `dunga`, `denge`, `aayega`) | rejected: negated / future |

Compound sentences split on `,`, `aur`, `phir`, `and` when both sides carry an amount. The customer carries forward to a
later clause without a name. The kind never carries forward; each clause decides its own.

### 1.5 Dates
`aaj` = today. `kal` = yesterday and `parso` / `parson` = two days ago (a ledger records the past; a future verb is rejected).
`N din pehle` = N days ago. No date word = today. `subah / shaam / raat` are ignored. `narson`, weekday names,
`pichle hafte`, `tarikh` → needs_clarification `unclear_date` (P1; never silently default these to today).

### 1.6 Corrections, undo and carry-over (need `ctx.last_event`)
| Utterance | Result |
|---|---|
| `nahi, 430`; `galat, 430`; `340 nahi, 430` | amend: `events` = the last event with the new amount |
| `Ramesh nahi, Suresh` | amend: the last event with the new customer |
| `undo karo`; `cancel karo`; `hata do`; `mita do`; `delete karo`; `pichli / pichla / last entry hatao` | undo, `target: "last"` |
| `nahi` / `galat` / `nahi nahi` alone (no pending question) | needs_clarification `unclear_correction` |
| `aur 200` | append: same customer and same kind as the last event, dated today |
| `aur 200 payment mila`; `kal 200 diya tha` | append: customer from the last event, kind from the words (bare diya = payment) |
Without `last_event`: corrections and undo → rejected `no_last_event`; carry-over forms → `missing_customer`.
If `last_event.age_s` is present and above 120, the customer does not carry over (ask `missing_customer`); amend and undo still work.

### 1.7 Queries (no amount in the utterance)
| Type | Examples |
|---|---|
| `balance` + customer | `Ramesh ka total?`, `Ramesh ka kitna baaki hai`, `Ramesh ka hisaab`, `Ramesh ka balance` |
| `credit_total`, period today | `Aaj kitna udhaar gaya?`, `Aaj ka udhaar` |
| `payment_total`, period today | `Aaj kitna aaya?`, `Aaj kitna jama hua` |
| `daily_summary`, period today | `Aaj ka hisaab batao`, `Aaj ka total` (no customer name) |
| `top_dues` | `Sabse zyada udhaar kiska hai`, `Kis kis ka baaki hai` |

### 1.8 Customers
- Key: lowercase Roman. Honorifics and kinship words that are separate tokens are dropped (`ji`, `bhai`, `bhaiya`, `saab`,
  `didi`, `uncle`, `aunty`, `seth` ...). `wale / wala / wali` phrases and `gali ...` phrases become tags
  (`Ramesh chai wale` → key `ramesh`, tag `chai wale`).
- From Devanagari: delete the final inherent vowel and write long vowels single (रमेश → `ramesh`, सुनीता → `sunita`).
- Matching uses `phonetic_key` (ee/ii→i, oo/uu→u, aa→a, w→v, doubled letters collapsed; `th`, `dh`, `sh` kept).
- With `ctx.customers`: alias match, then exact key match, then exactly one phonetic or fuzzy match (rapidfuzz ratio of
  phonetic keys at least 90) → that customer, with `customer` = its stored name and `customer_id`. No match → a new
  customer: `customer` = the spoken key, `new_customer: true`. Two or more customers with the same name → the spoken
  tag picks one, otherwise needs_clarification `same_name` with `candidates`.
- A spoken tag for a single matching customer who has no tags is returned in `tags` (the backend stores it). A spoken tag
  that contradicts the tags of the only matching customer means a new customer with that tag.

### 1.9 Answers to a pending question (`ctx.pending` present)
| pending.reason | Answer | Result |
|---|---|---|
| `plausibility` | `haan`, `ha`, `ji`, `pakka`, `sahi`, `theek`, `yes` | ok with the pending events |
| `plausibility` | `nahi`, `galat`, `cancel` | rejected `cancelled` |
| `plausibility`, `confusable_number`, `missing_amount` | a number phrase | ok with that amount (plausibility is not asked twice for a confirmed number) |
| `confusable_number` | `pehla` / `doosra`, or `haan` (= the first candidate) | ok with that candidate |
| `same_name` | a tag (`chai wale`), `pehla` / `doosra`, `pehle wale` | ok with that candidate's `customer_id` |
| `missing_customer` | a name | ok with that customer (1.8 applies) |
| `ambiguous_direction` | `udhaar`, `credit`, `ko diya` / `payment`, `jama`, `mila`, `ne diye` | ok with that kind |
| `unclear_correction` | a number → amend ; `hata do` → undo | as shown |
An utterance that is itself a complete ledger sentence or query is parsed fresh and the pending question is dropped.

### 1.10 Guards
- Plausibility: any amount above `limits.confirm_above` (default 50,000) → needs_clarification `plausibility`.
- Confusable number: when an entry in `stt_alternatives` parses to the same structure with a different amount →
  needs_clarification `confusable_number`, `candidates` = [amount, other amount].
- Not a ledger sentence → rejected `not_ledger`.

## 2. Ledger (`server/app/ledger.py`), SQLite with field-level AES-256-GCM

SQLCipher cannot load on the dev machine, so encryption is applied in the application with `cryptography` (AESGCM).

```sql
customers(id TEXT PRIMARY KEY, ident BLOB NOT NULL, reminders_opt_in INTEGER NOT NULL DEFAULT 0, created_ts TEXT NOT NULL);
  -- ident = encrypt(JSON {"key","display","aliases":[...],"tags":[...],"phone":null})
events(id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL,
       kind TEXT NOT NULL CHECK (kind IN ('credit','payment','reversal')),
       customer_id TEXT NOT NULL REFERENCES customers(id),
       amount_paise INTEGER NOT NULL CHECK (amount_paise > 0), effective_date TEXT NOT NULL,
       utterance_id TEXT, supersedes_id INTEGER REFERENCES events(id), replaces_id INTEGER REFERENCES events(id),
       session_id TEXT, trace_id TEXT);
utterances(id TEXT PRIMARY KEY, ts TEXT NOT NULL, session_id TEXT, body BLOB NOT NULL);
  -- body = encrypt(JSON {"transcript","status","reply_text","timings"})
```
- Encrypted: every name, alias, tag, phone, transcript and reply text. Plain: ids, kinds, amounts, dates (so totals are
  SQL). Blob = 12-byte random nonce + ciphertext and tag; associated data = `"<table>:<row id>"`.
- Key: env `LEDGER_KEY` (base64, 32 bytes). If unset, the app creates `data/ledger.key` on first run and logs a warning.
- Append-only: triggers abort every UPDATE and DELETE on `events` and `utterances`. Purging means deleting the database
  file (`python -m app.admin purge`), never deleting rows.
- Amount: parser rupees x 100 = `amount_paise`.
- Reversal: `kind='reversal'`, `supersedes_id` = the cancelled event, same customer and amount.
- Active event: a credit or payment with no reversal pointing at it. Balance = sum(active credits) - sum(active payments).
- Undo = one reversal of the last active event. A second undo reverses the one before it.
- Amend = reversal of the last active event + a new event with `replaces_id` = the old id, in one transaction.
- One utterance = one transaction: all of its events are saved, or none.
- WAL mode. Database path: env `LEDGER_DB` (default `data/khata.db`). Customer rows are few: load and decrypt them into
  memory for matching.

## 3. Session API (browser ↔ server)

HTTP: `GET /` serves `web/` (static, no build step). `GET /api/health`. `GET /api/ledger?limit=50` → `{"entries":[...],
"totals":{"credit_today","payment_today"}}`. `GET /api/customers` → `{"customers":[{"id","display","tags","balance",
"reminders_opt_in"}]}`. `POST /api/admin/purge` with header `X-Admin-Token` (disabled when `ADMIN_TOKEN` is unset).

WebSocket `/ws/session`. Text frames are JSON; binary frames are audio. The server assigns every `turn_id`.

Client → server
| Message | Meaning |
|---|---|
| `{"type":"hello","lang":"hi","resume"?: session_id,"access_code"?: str}` | Sent after the user's first tap. Starts the greeting turn |
| `{"type":"start","mode":"ptt"}` | Push-to-talk pressed. Also barge-in: cancels any reply still playing |
| binary | PCM signed 16-bit little-endian, mono, 16 kHz, any chunk size |
| `{"type":"end"}` | Push-to-talk released |
| `{"type":"text","text":"..."}` | Typed or test input; same pipeline without speech recognition |
| `{"type":"cancel"}` | Stop speaking now |
| `{"type":"ping","t":n}` | Answered with `pong` |

Server → client
| Message | Meaning |
|---|---|
| `{"type":"ready","session_id"}` | Reply to hello |
| `{"type":"state","turn_id","state":"listening"\|"hearing"\|"transcribing"\|"thinking"\|"speaking"\|"idle"}` | `hearing` and `transcribing` come from Gnani's `speech_start` and `processing` |
| `{"type":"transcript","turn_id","text","segment","final"}` | One per Gnani segment; the last has `final: true` and the full joined text |
| `{"type":"result","turn_id","trace_id","status","action","reason"?,"entries":[...],"reply_text","question"?}` | What was understood and saved. `action` is also `"greeting"` or `"none"` |
| `{"type":"audio_start","turn_id","sample_rate":24000,"encoding":"pcm_s16le","channels":1}` then binary frames then `{"type":"audio_end","turn_id","cancelled"?}` | The spoken reply |
| `{"type":"timing","turn_id","trace_id","ms":{"stt_final","parse","db","tts_first_chunk","end_to_first_audio","gnani_stt_latency"}}` | Per-hop timings |
| `{"type":"error","turn_id"?,"code","message"}` | |

Entry shape: `{"id","kind","customer":{"id","display","tags"},"amount","date","ts","reversed","reversal_of"}`.
Every amount in this API (`amount`, `balance`, `totals`) is whole rupees as an integer. Reversal rows are not listed as
entries; they only set `reversed` on the entry they cancel (`reversal_of` is null in `result`).

Rules
- AI disclosure: the greeting turn speaks the disclosure. If a session's first spoken reply is anything else, the server
  prepends the disclosure sentence. Every session's first spoken reply therefore contains it.
- Barge-in: on `start` or `cancel` the server stops sending audio for older turns, sends `audio_end` with
  `"cancelled": true`, and drops the Gnani TTS request. The client stops playback at once and ignores messages for a
  `turn_id` older than its current one.
- Nothing is spoken before the database transaction commits.
- `end_to_first_audio` = from the server receiving `end` (or `text`) to sending the first reply audio frame. The client
  also measures release → first sample played and shows both.
- A turn with no speech detected ends with `result` `action: "none"` and no audio.
- The server ends a turn by itself after 30 s of audio.
- `turn_id` is an integer: 0 for the greeting, then increasing by one per turn within a session. Every `audio_end`
  carries it, cancelled or not.
- `result.entries` lists every ledger entry the turn touched, in its final state: the new entries for an append; the old
  entry (`reversed: true`) followed by the new entry for an amend; the old entry (`reversed: true`) for an undo; an empty
  list for a query, a question, the greeting or a rejection.
- `hello` with `resume` for a session held in memory (5 minutes after its socket closed) keeps that session's state,
  answers `ready` with the same `session_id`, and does not replay the greeting.

## 4. Gnani API Platform (`server/app/gnani/`), verified against docs.gnani.ai

Use the `websockets` library directly. The SDK is not used: it cannot send `commit`.

Speech-to-text, Prisma v3.0 (required by the hackathon rules)
- URL `wss://api.vachana.ai/stt/v3/stream`. Upgrade headers: `x-api-key-id`, `model: prisma-v3.0`, `language_code`,
  `format`, `x-sample-rate: 16000`, `keyterms` (JSON array, non-ASCII escaped, at most 200), `x-idle-timeout-sec`.
  Older header spellings (`lang_code`, `x-model`, `x-format`) are also accepted by Gnani.
- Audio: binary frames of exactly 1,024 bytes (512 samples, 32 ms) at real-time cadence. Re-frame the browser audio; pad
  the last frame with zeros.
- Client control frame `{"type":"commit"}` closes the open utterance at once. Send it on `end`.
- Server messages: `connected` (`config`, `request_id`), `speech_start` (`utterance_id`), `processing`,
  `transcript` (`text`, `audio_duration_ms`, `segment_id`, `segment_index`, `latency`, `utterance_id`, `is_final` always
  true, `detected_language_code` except in transliterate), `error` (`message`). There are no partial transcripts, no
  confidence scores and no alternatives.
- A turn's text = all `transcript` texts between `start` and the reply to `commit`, joined with a space. After `commit`,
  wait for a transcript only if an utterance is open (a `speech_start` or `processing` without its `transcript`);
  give up after 2.5 s.
- Defaults: `format=transliterate` (whole transcript in Latin letters, numbers as words, so one parser path),
  `language_code=hi-IN`. Both are env settings; the first live test decides the final values.
- `keyterms`: customer names plus ledger words (`udhaar`, `jama`, `rupaye`, `hazaar`, `dedh`, `dhai`, `saade`, `sawa`, `paune`).
- Limits: 15 minutes per session (close code 1001), idle timeout 60 s by default (5 to 900), bad header → `error` then
  close 1008, bad key → HTTP 401. Keep one STT socket per browser session, opened on the first `start`, reused while
  turns continue, closed after 45 idle seconds.

Text-to-speech, Timbre v3.0 (required)
- URL `wss://api.vachana.ai/api/v1/tts`. Upgrade header `X-API-Key-ID`.
- One JSON request per reply: `{"text","voice","model":"timbre-v3.0","language":"hi-IN","speed":1.0,
  "audio_config":{"sample_rate":24000,"num_channels":1,"sample_width":2,"encoding":"linear_pcm","container":"raw"}}`.
- Server messages: `{"type":"start","request_id"}`, `{"type":"audio","data":{"chunk_index","audio":"<base64>","is_final":false}}`,
  `{"type":"complete","data":{"is_final":true}}`, `{"type":"error","message"}`. The socket stays open for the next request.
- Keep one TTS socket per browser session, opened at `hello` and re-opened in the background whenever it closes, so a
  reply never waits for a handshake. To cancel a reply, close the socket. If a chunk starts with `RIFF`, strip the WAV header.
- Spoken text is Devanagari with amounts written as words (Gnani's guidance: pass numbers as spoken words).
- Cache reply audio by hash of (text, voice, model, sample rate) in memory and under `data/tts_cache/`.

Mock Gnani (`server/mock_gnani/`, owner qa): one FastAPI app serving both WebSocket paths above with the same messages,
plus `POST /__mock/reset`, `POST /__mock/script` `{"transcripts":[str | [str, ...]],"stt_delay_ms","tts_first_chunk_delay_ms",
"tts_chunk_ms"}` and `GET /__mock/log` → `{"stt_sessions":[{"headers","frames","bad_frames","commits"}],"tts_requests":[...]}`.
Run with `python -m mock_gnani --port 9090` from `server/`. The app reaches it through `GNANI_BASE_URL=http://127.0.0.1:9090`
(`http` → `ws`, `https` → `wss`).

## 5. Replies (`server/app/replies.py`)

Each reply has `reply_text` (Roman Hinglish with `₹` and digits, shown on screen) and `speak_text` (Devanagari, amounts
from `nlu.speak.number_to_words`, sent to TTS). Keep them under about 12 words. No pressure language anywhere.

| Moment | reply_text |
|---|---|
| Disclosure (greeting) | `Namaste! Main KhataVaani hoon, ek AI sahayak.` |
| Credit | `{name} ke khate mein ₹{amt} udhaar likh diya.` |
| Payment | `{name} se ₹{amt} mile, jama kar diya.` |
| Past date | `{name} se kal ke ₹{amt} jama kiye.` / `{name} ke kal ke ₹{amt} udhaar likhe.` (`parso ke` likewise) |
| Several entries | `{n} entry likh di: {name} ke ₹{amt} udhaar, aur kal ke ₹{amt} jama.` |
| New customer prefix | `Naya khata {name}.` |
| Amend | `Theek kar diya: {name}, ₹{amt} {udhaar\|jama}.` |
| Undo | `Pichli entry hata di: {name}, ₹{amt} {udhaar\|jama}.` |
| Nothing to undo or amend | `Pichli entry nahi mili.` |
| Confusable number | `₹{a} ya ₹{b}?` |
| Same name | `Kaunse {name}: {tag1} ya {tag2}?` (a customer without tags is called `pehle wale`) |
| Missing amount / customer | `Kitne rupaye?` / `Kiska khata?` |
| Direction | `{name} ne diye, ya {name} ko udhaar?` |
| Plausibility | `₹{amt}, pakka?` |
| Unclear correction / date | `Sahi amount boliye, ya hata do boliye.` / `Kaunsa din? Aaj, kal ya parso boliye.` |
| Cancelled | `Theek hai, entry nahi ki.` |
| Rejected | `Maaf kijiye, samajh nahi aaya. Dobara boliye.` |
| Balance | `{name} ke ₹{amt} baaki hain.` / `{name} ka kuch baaki nahi.` / `{name} ke ₹{amt} zyada jama hain.` |
| Credit total / payment total | `Aaj ₹{amt} udhaar gaya.` / `Aaj ₹{amt} jama hue.` (zero: `Aaj koi udhaar nahi gaya.`) |
| Daily summary | `Aaj ₹{c} udhaar gaya, ₹{p} jama hue. Sabse zyada baaki: {name}, ₹{amt}.` / `Aaj abhi tak koi entry nahi.` |
| Top dues (three names) | `Sabse zyada baaki: {n1} ₹{a1}, {n2} ₹{a2}, {n3} ₹{a3}.` / `Kisi ka kuch baaki nahi.` |
| Upstream failure | `Network mein dikkat hai, dobara boliye.` |

## 6. Latency budget (judged metric: end of speech → first agent audio, target under 2000 ms)

| Hop | Target |
|---|---|
| Button release → `end` sent | under 50 ms |
| `end` → final transcript (`commit` + Gnani `latency`) | measure; expect 300 to 600 ms |
| Parse + guard | under 10 ms |
| Database commit + query | under 20 ms |
| TTS request → first audio chunk | measure; socket is already open |
| First chunk → first sample played | under 100 ms |

## 7. Responsible AI rules (breaking one in the live demo zeroes that score) and their tests

| Rule | Test (owner) |
|---|---|
| AI disclosure in the first turn, in the user's language | `test_first_reply_discloses_ai` (backend) |
| No ambiguous entry saved silently | `test_needs_clarification_saves_nothing` (backend); golden cases (qa) |
| Ledger is append-only | `test_events_reject_update_and_delete` (backend) |
| Names and transcripts encrypted at rest | `test_db_file_has_no_plaintext_names` (backend) |
| Data can be deleted after judging | `test_purge_removes_database` (backend) |
| API key only in `.env`, never in the repo or logs | reviewer; `.gitignore` |
| Synthetic data only; no voice cloning; no pressure language; reminders opt-in only | reviewer |

## 8. Configuration (environment variables; `.env` is never committed or printed)

`GNANI_API_KEY`, `GNANI_BASE_URL` (default `https://api.vachana.ai`), `GNANI_STT_FORMAT` (`transliterate`),
`GNANI_STT_LANGUAGE` (`hi-IN`), `GNANI_STT_MIN_SILENCE_MS` (unset = Gnani default), `GNANI_TTS_VOICE` (`Shivani`),
`GNANI_TTS_LANGUAGE` (`hi-IN`), `GNANI_TTS_SAMPLE_RATE` (`24000`), `LEDGER_KEY`, `LEDGER_DB` (`data/khata.db`),
`SHOP_TZ` (`Asia/Kolkata`), `CONFIRM_ABOVE` (`50000`), `ADMIN_TOKEN`, `ACCESS_CODE`, `HOST`, `PORT` (`8000`).
Fixed by the hackathon rules and not configurable: `prisma-v3.0`, `timbre-v3.0`.

## 9. Layout, ownership and working rules

```
server/nlu/         nlu       parser, numbers, speak, names
server/app/         backend   main, config, session, pipeline, replies, ledger, crypto, admin, gnani/{stt,tts}
server/mock_gnani/  qa        mock Gnani server
server/tests/nlu/   nlu       (test_number_forms.py is the spec: add cases, never weaken them)
server/tests/app/   backend
server/tests/oracle/, server/tests/e2e/, server/tests/test_*.py, eval/, scripts/   qa
scripts/live_smoke.py   backend (manual: uses the real API key and credits)
web/                web       static PWA: Preact + htm standalone (vendored), ES modules, CSS, AudioWorklet. No bundler
docs/CONTRACT.md, server/pyproject.toml   tech lead
```
- Run every Python command from `server/` with `../.venv/Scripts/python` (tests: `../.venv/Scripts/python -m pytest`).
- Each module has one owner. A change to another module goes through its owner, with a minimal reproducing case.
- Commits are made at phase boundaries by the tech lead.
- No new dependency without the tech lead: compiled wheels can be blocked on the dev machine.
- Automated tests never call the real Gnani API. They use the mock.
