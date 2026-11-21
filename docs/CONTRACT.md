# CONTRACT v1.12 (2026-11-22)

The binding interface specification for KhataVaani. Changes go through the tech lead.
Where this file disagrees with an older note, this file wins.
Sources: the pitch deck, the hackathon brief (rubric summarised in docs/ARCHITECTURE.md), our research notes,
and Gnani's own docs (docs.gnani.ai, read 2026-11-21).

## 0. Scope for the 24-hour build

| Priority | What |
|---|---|
| P0 | Exact amounts in any spoken form; credit vs payment direction; relative dates; spoken correction and undo; same-name question; spoken answers; push-to-talk streaming through Gnani Prisma v3.0 and Timbre v3.0 over WebSocket; AI disclosure in the first turn; barge-in; encrypted data at rest; per-turn latency readout; README |
| P1 | Clarification answers for every question type; new-customer and tag learning; payment_total and top_dues queries; TTS cache; session resume; access code; data purge command; latency harness |
| P2 (only if P0 and P1 are green) | Hands-free mode (server VAD); dual-decode number check; reminders (opt-in, SMS; 3.8); offline app shell; Kannada lexicon; Playwright e2e |
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
            for a question about a query: {"reason", "action": "query", "query": {...}, "candidates"}
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
- An entry whose amount phrase is invalid or not a whole rupee amount (`Ramesh ka saade do sau udhaar`) →
  needs_clarification `missing_amount`. An amount of zero → rejected `invalid_number`.

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
A clause boundary needs no punctuation: Gnani writes `Ramesh ka teen sau chalis udhar kal do sau diya tha.` without a
comma. A second amount with its own date word or verb starts a new clause. Two names with one amount
(`Ramesh ka 100 udhaar aur Sunita ko udhaar`) → needs_clarification `missing_amount`; one amount is never spread over
two customers.

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

The same-name rule covers queries: `Ramesh ka total` with two customers named Ramesh → needs_clarification `same_name`;
the answer returns the query with `customer_id`.

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
- Tag matching is loose: `wala / wale / wali / vale` are one word, words are compared by `phonetic_key`, and a spoken tag
  matches a stored tag when all of its content words appear in it (`chai` matches `chai wale`).
- A name with a particle and nothing else (`Ramesh ka`, `Ramesh ne`) → rejected `not_ledger`.

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

### 1.11 Text as it really arrives (Gnani transcripts captured on 2026-11-21)
`format=transliterate` returns sentence case with a full stop, sometimes commas, and spelling that changes between
utterances:
- `Ramesh ka teen sau chalis udhar kal do sau diya tha.`
- `Sunita ne deedh sau rupaye diye.`
- `Ramesh ka three forty udhaar likh do.`
- `Nahi, chaar sau tees.`

Give every keyword the same spelling tolerance as number words (`udhar / udhaar / udhari`, `deedh / dedh / derh`,
`chalis / chaalis`, `diya / diye / diyaa`). Ignore filler words anywhere in a sentence: `haan` (when more words follow),
`to / toh`, `achha / accha`, `arre`, `bhai / bhaiya`, `suno`, `dekho`, `zara`, `please`, `ji`, `ok`, and a leading
`theek hai`.

### 1.12 Rules added after the first review (they override anything above that disagrees)

Context and targets
- `ctx.last_events`: every event saved by the session's previous saving utterance, oldest first, each with its `id`.
  `ctx.last_event` is the last of them.
- An amend result carries `target: "last"` or `target: {"event_id": id}`.
- `nahi, 430` amends the event when `last_events` holds one event (or is absent). With two or more, `340 nahi 430` amends
  the one event whose amount is named; anything else → needs_clarification `unclear_correction` with those events as
  `candidates` and the question `Kaunsi entry: ₹340 udhaar ya ₹200 jama?`. The answer may be the old amount,
  `udhaar` / `jama`, or `pehli` / `doosri`.

Names
- The word or run of words directly before a particle (`ne`, `ko`, `ka`, `ke`, `ki`, `se`, `pe`, `par`) is the customer
  name, even when it is a kinship word, an honorific, a filler, a time word or a keyword (`Chacha ne 500 diye`,
  `Abhi ko 200 udhaar`, `Diya ko 200 udhaar`). Next to another name a kinship word or honorific is still dropped
  (`Sharma ji` → `sharma`); alone it is the key (`chacha`).
- Two name words in a row are one name, with a space in the key (`Ramesh Chopra ko` → `ramesh chopra`). `maine`,
  `mujhe` and `humne` are ignored.
- A clause that has a particle but no name before it never takes the previous customer: needs_clarification
  `missing_customer`.
- Pronouns (`wo`, `uska`, `usko`, `usne`, `inka`, `inko`, `iska`, `unka` and their forms) mean the customer of
  `last_event` under the carry-over rule; without one, `missing_customer`. A pronoun never becomes a customer.
- Fuzzy matching (this replaces "ratio of at least 90"): two names are the same person only when their `phonetic_key`s
  are equal, or when they have the same number of words and, word by word, the same consonants in the same order and
  the same ending (both end in a consonant, or both in the same folded vowel). `rameysh` = `ramesh`; `sunit` ≠ `sunita`,
  `kamal` ≠ `kamala`, `rajan` ≠ `ranjan`, `rakesh sharma` ≠ `ramesh sharma`.
- In a balance query, a name that matches nobody in the roster returns `query.unknown_customer: true`.

Things that are not entries
- `nahi` with nothing to replace after it (`... udhaar nahi hai`, `... nahi dena`, `... nahi diya`) → rejected `negated`.
- A yes/no question (`Kya Ramesh ne 500 diye the?`) and a statement that is not an instruction
  (`Ramesh ka order cancel ho gaya`) → rejected `not_ledger`.
- `dena`, `dena hai`, `dene hain` → needs_clarification `ambiguous_direction`.
- `likh do sau rupaye` can be 200 or 100 → needs_clarification `confusable_number`.
- A second name with no amount of its own (`Ramesh ne 500 diye Sunita bhi`) → needs_clarification `missing_amount`.

Dates and periods
- In `N din pehle` only the single number directly before `din` is the day count; the other numbers are the amount
  (`Ramesh ne teen sau do din pehle diye` = 300, two days ago). More than 60 days → needs_clarification `unclear_date`.
- `Kal kitna udhaar gaya?` → `period: "yesterday"`. `credit_total`, `payment_total` and `daily_summary` accept `today`
  and `yesterday`.

Undo, and "nahi" followed by a sentence
- Undo applies only to a generic phrase (`undo karo`, `pichli entry hata do`) or one that names the customer of the last
  event. Another customer, `pehli`, `dono` or a date (`kal wali`) → needs_clarification `unclear_correction`
  (`Sirf pichli entry hata sakta hoon: Ramesh, ₹340 udhaar. Hata doon?`; `haan` undoes it).
- `Nahi` followed by a query runs the query. `Nahi` followed by a full entry that changes the customer, the amount and
  the kind together → needs_clarification `unclear_correction` (`Pichli entry hata kar yeh likhoon?`; `haan` amends,
  `nahi` appends the new entry and keeps the old one).

Answers to a pending question
- An answer may carry extra words: `Ramesh ne diye` / `Ramesh ko udhaar` (direction), `Ramesh chai wale` /
  `doosra wala` (same name), `200 rupaye udhaar` (amount), `haan likh do` / `nahi 7500` (plausibility; the new amount
  replaces the old one), a kinship word (customer).
- Words that are not a name (`dobara boliye`) never become a customer.
- After two answers in a row that do not resolve the question, the result is rejected `cancelled` and the question is
  dropped. Count them in `pending.attempts`.

### 1.13 Language matching, English sentences, first person and relations (from the first voice test)

Language of the reply
- Every result carries `lang`: `"en"` when the utterance is an English sentence, `"hi"` when it is Hindi, Hinglish or
  Devanagari. It is left out when the utterance cannot tell (a bare number, a bare name), so the session keeps its language.
- A sentence is English when it has English verbs or question words and no Hindi particle or verb
  (`ne`, `ko`, `ka`, `ke`, `ki`, `se`, `hai`, `diya`, `diye`, `udhaar`, `batao` ...). Code-mixed sentences are `"hi"`.

English sentences
| Pattern | Result |
|---|---|
| `X paid N`, `X has paid N`, `X gave N`, `X returned N`, `X deposited N`, `received N from X`, `got N from X`, `collected N from X`, `payment of N from X` | payment |
| `X took N on credit`, `X took goods worth N`, `X bought for N on credit`, `X borrowed N`, `X owes N`, `give N credit to X`, `N credit to X`, `lent N to X`, `add N to X's account`, `put N on X's account` | credit |
| `pay N to X`, `paid N to X`, `debit`, a name and an amount with no verb | ask: ambiguous_direction |
| `no, 430`, `not 340, 430`, `wrong, 430`, `make it 430`, `change it to 430` | amend |
| `undo`, `undo that`, `cancel that`, `cancel the last entry`, `delete the last entry`, `remove the last one` | undo |
| `what is X's balance`, `X's balance`, `X's total`, `how much does X owe`, `how much is due from X` | balance |
| `how much credit today`, `today's credit` / `how much did I receive today`, `today's collection` | credit_total / payment_total |
| `today's summary`, `today's total`, `today's account` / `who owes the most`, `top dues` | daily_summary / top_dues |
| `today`, `yesterday`, `day before yesterday`, `N days ago` | dates |
| `yes`, `yeah`, `correct`, `right`, `sure` / `no`, `cancel` / `first`, `second` / `paid`, `he paid`, `credit`, `took credit` | answers to a pending question |
An imperative verb is never a name: in `Pay five hundred rupees to Ramesh` the customer is Ramesh. `X's` is the name X.

First person (the shopkeeper speaking about himself)
- `maine` / `humne` ... `diya` / `diye` means the shop gave: credit to the named or carried-over customer
  (`Maine Ramesh ko 200 diye` = credit 200; `Maine char sau pachpan rupaye diye` after a Ramesh entry = credit 455 for
  Ramesh; with no customer to carry over → needs_clarification `missing_customer`).
- `maine X se N liye`, `mujhe X ne N diye`, `mujhe N mile` mean the shop received: payment.
- `maine`, `mujhe`, `humne`, `I`, `me`, `we` are never customer names.

Relations
- `X ki biwi / patni / beti / maa / behen`, `X ka beta / bhai / papa`, `X ke papa / bhai`, `X's wife / son / daughter /
  brother / mother / father` name a different person from X. The key is `x ki biwi` and so on, with the relation word
  normalised (`biwi`: bivi, bevi, beevi, patni, wife; `beta`: ladka, son; `beti`: ladki, daughter; `bhai`: brother;
  `behen`: sister; `maa`: mummy, mother; `papa`: pitaji, baap, father). Never answer or save for X himself.
- A full stop inside an utterance is not a boundary by itself: Gnani can write `Ramesh ki bevi. Ka khata?` for one
  spoken sentence.

Spoken numbers: `number_to_words(n, "en")` returns Indian English (`one thousand five hundred`,
`one lakh twenty five thousand`).

More rules from the transcripts of the first voice test
- While a question is pending, an utterance replaces it only when it is a complete entry (customer, amount and
  direction) or a query. Anything else is an answer attempt: an unknown word with an amount (`ami Hazar`), `thik hai`,
  a bare name. It never creates a customer, and two failed attempts cancel the question (section 1.12).
- A word directly before a unit word (`sau`, `hazaar`, `lakh`, `hundred`, `thousand`) that is not a number is a misheard
  number, never a name: `nahi nahi, saadh sau rupaye` and `Ramesh ke sau sau chalis udhaar` → needs_clarification
  `missing_amount`. Close spellings that can only be one number are accepted (`saatt` = 7).
- A correction that gives only an amount (`nahi nahi, 700 rupaye`) changes the amount and nothing else.
- First-person phrases are never names: `mere paas`, `mere ko`, `mereko`, `mujhko`, `hamare paas`, `mera`, `meri`.
  `sau rupaye aaye mere paas` is a payment of 100 by the carried-over customer.
- Keyword spellings seen live: `wapas / wapis / wapi / vapas`, `khate / khaate / khata`, `biwi / bivi / bevi / bewi`,
  and `sa` for `sau` directly after a number (`paanch sa rupaye` = 500).
- English seen live: `Five hundred in Ramesh's account` and `Paid five hundred rupees to Ramesh` →
  needs_clarification `ambiguous_direction` (customer Ramesh, amount 500); `Give Ramesh five hundred rupees worth of
  product` → credit 500.

### 1.14 Edge-case rules (v1.2; they override anything above that disagrees)

The case ids (A13, H04 ...) point at docs/EDGE_CASES.md, the list these rules were written against.

Context added to `ctx`
| Field | Shape | Meaning |
|---|---|---|
| `customers[i].balance` | int rupees | What the customer owes now (negative = advance) |
| `customers[i].usual` | int rupees | Median of the customer's active credit entries; present only with three or more |
| `last_turn` | `{"action","age_s","customer"?,"customer_id"?}` | The session's previous turn: `append`, `amend`, `undo`, `query`, `question` or `none`. `customer` is set after a query about one customer |
| `limits` | `{"confirm_above":50000,"confirm_below":10,"max_amount":9999999,"carry_s":60,"duplicate_s":30,"confirm_new_customer":false,"strict":false}` | The server sends `confirm_new_customer: true` and `strict: true`; the parser's own defaults are false |
| `confusables` | `{"340":[740]}` | Amounts this shop has corrected before: heard → meant |

Result additions
- needs_clarification reasons `new_customer` and `confirm_entry`. A `confirm_entry` result and its `pending` carry
  `confirm: {"type": "computed"|"settle"|"half"|"writeoff"|"roundoff"|"overpayment"|"duplicate"|"hearsay", "balance"?, "bill"?, "paid"?}`.
  The answers are those of `plausibility` (1.9): yes saves the pending events, no → rejected `cancelled`, a number
  replaces the amount of a single pending event.
- rejected reasons `out_of_scope`, `too_large`, `no_question`.
- Event kind `writeoff`: the customer owes that much less, and it is not a payment.
- Query types `outstanding_total` and `due_since` (with a customer). `period` also takes `this_week`, `last_week`,
  `this_month`, `last_month` (weeks run Monday to Sunday).
- Action `reminder`: `{"status":"ok","action":"reminder","customer","customer_id"?,"amount"?}`. Yes to a pending
  reminder question (`confirm.type: "reminder"`) returns the same action with the pending customer and no `amount`.
- A rejected undo carries `action: "undo"` and a rejected correction `action: "amend"`, so the reply can tell them apart.
- A `missing_amount` question about a quantity (H03) carries `quantity: true`; the reply is `Kitne ka?`.

Numbers
- A13: a digit followed by `k` is thousands (`2k` = 2000, `2.5k` = 2500); `1.5 lakh` = 150000. A decimal that is not a
  whole rupee amount → `missing_amount`. A comma between digits is dropped whatever the grouping (`3,40` = 340, F08).
- A22: `crore` / `karod` = 1,00,00,000. An amount above `limits.max_amount` → rejected `too_large`. No input may raise
  an exception (`999999999999`).
- A15: `minus N`, `-N` → rejected `invalid_number`.
- A17: a word, name or number phrase repeated back to back is said once (`Ramesh Ramesh ka 340 340 udhaar` = Ramesh,
  340). A number phrase followed at once by a longer one that begins with the same words is a restart and the longer
  one wins (`teen sau teen sau chaalis` = 340).
- A18: three or more single-digit words in a row with no unit word are the digits joined (`four three zero`,
  `char teen shunya` = 430). Exactly two (`teen chaar`) → `missing_amount`.
- A11: two single-digit words before `sau` → `confusable_number`, candidates `[d1*100 + d2*10, d2*100]`
  (`teen chaar sau` → `₹340 ya ₹400?`).
- A12: two amounts joined by `ya` / `or` → `confusable_number` with those two candidates.
- A19: an amount that is a key of `ctx.confusables` → `confusable_number` `[amount, first meant value]`.
- A21: an amount of at least 1000 that is 10 times the customer's `usual` or more → `plausibility` (result carries `usual`).
- An amount below `limits.confirm_below` with no currency word (`Ramesh ka teen udhaar`) → `plausibility`.
- A23: `rs`, `rs.`, `rupay`, `rupaye`, `rupaiye`, `rupee(s)`, `₹`, `paise`, `paisa` are currency words. All mean rupees
  (the ledger keeps whole rupees) and none is ever a name.

A number that is not an amount (A16, A24, H03)
- A number followed directly by a measure word or count noun is a quantity: `kilo`, `kg`, `gram`, `litre`, `ml`,
  `packet`, `dozen`, `darjan`, `piece`, `peti`, `bori`, `box`, `bottle`, `pao`, `meter`, `baar`, `log`, `customer`,
  `grahak`, `aadmi`, `item`, `cheez`, `baje`, `number`, `saal`, `mahine`, `hafte`, `ghante`, `minute`, `percent`.
  With a customer and a credit word → `missing_amount` with the question `Kitne ka?` (`Ramesh ko 2 kilo chawal udhaar`).
  Otherwise → rejected `not_ledger` (`teen customer aaye the`). A quantity never becomes an amount.
- Bare `ek` is an amount only with a currency or unit word (`ek rupaya`, `ek sau`). Elsewhere it is the article
  (`ek customer aaya tha` → rejected `not_ledger`).

Direction
- B06: `gave X N on credit`, `gave N to X on credit` → credit.
- B11: `udhaar` with `wapas`, `chukaya`, `chuka diya`, `chukta`, `lautaya` or `vasool` → payment
  (`Ramesh ne 30 udhaar chuka diya`, `Ramesh ka udhaar wapas aaya 20`). With no amount → the settle rule (H04).
- B12: one name with both `ne` and `ko` → `ambiguous_direction` (a `ko` that belongs to a day word, `somvar ko`, does not count).
- B14: one customer as giver (`ne`) and another as receiver (`ko`) in one clause → rejected `out_of_scope`.
- B15: `advance` / `peshgi` is a keyword, never a name. `X ne advance 500 diya`, `X ka 500 advance`,
  `advance 500 diya` (customer carried over or asked) → payment; the overpayment question (H08) is not asked.
- B16: `wapas kiya` without `ne` (`wapas kiya 100`, `X ko 100 wapas kiya`) → `ambiguous_direction`
  (`missing_customer` first when there is no name). `X ne N wapas kiya` stays a payment.
- L04: `likh do`, `likh lo`, `add kar do`, `add karo`, `jod do`, `daal do`, `chadha do`, `note kar lo`, `put`, `note`,
  `add`, `write` are action words. With a named customer and no other direction word → credit (`Ramesh 100 note kar lo`).

Carry-over and context expiry (D06, D07, L01, L02, L03, L06). This replaces the 120-second rule of 1.6.
- Carry-over across turns is only for explicit continuation forms: `aur N ...`, `N aur`, a bare amount with only an
  action word (`200 add kar do`), and pronouns (`usne 200 diye`). Section 1.15 has the full rule.
- Customer and kind come from `last_event` only when `last_turn.action` is `append` or `amend` and
  `last_turn.age_s` ≤ `limits.carry_s`. A form with no direction word takes the kind of the last event
  (`Ramesh ne 100 diye` then `50 add kar do` = payment 50). Without `last_turn` in `ctx`, `last_event.age_s` decides.
- When `last_turn` is a query about one customer and not older than `carry_s`, that customer carries over and the
  kind does not: `ambiguous_direction` (`Sunita ka total?` then `aur 200`).
- Anything else → `missing_customer`; the direction is asked next when the words give none.

Corrections, undo and stopping (D03, D04, D09 to D13)
- After `last_turn.action == "undo"` a correction (`nahi, 430`) → rejected `no_last_event`. An older entry is never
  amended in place of the one that was removed. A second `undo` reverses the previous active entry.
- `nahi, X ka nahi, Y ka N`, `X nahi, Y`, `X ka nahi Y ka` → amend the customer to Y. The amount changes only when a
  different one is said.
- An utterance that ends with `ruko`, `ruk jao`, `ek minute`, `wait`, `stop`, `rehne do`, `chhodo`, `jaane do` or
  `cancel` after other words → rejected `cancelled`; nothing is saved. Alone while a question is pending → rejected
  `cancelled` and the question is dropped. Alone with nothing pending: `cancel` / `cancel karo` is undo (1.6), the
  others → rejected `cancelled`.
- `cancel`, `ok`, `undo` and other words used in both languages carry no `lang`.

Fillers (D15): `uh`, `um`, `umm`, `hmm`, `er`, `aa`, `matlab`, `wo na`, `na`, `yaar`, `like`, `actually`, `basically`
are ignored anywhere and are never part of a name (`uh Ramesh ka matlab 340 udhaar` = Ramesh, credit 340).

Customers (E03 to E12)
- For names, `th` and `t` are the same letter (`Sunitha` = `Sunita`).
- A stored customer name or alias wins wherever a name can stand, even when the word is also a number word, a keyword
  or a filler (`Das ko 500 udhaar` with a customer `das`). Look in the roster first.
- Close names: not the same person by 1.12, but one consonant differs or is missing (`Rakes` / `Rakesh`,
  `Ramesh` / `Rakesh`), or the spoken word is the end of exactly one stored name and has three letters or more
  (`esh` for `Ramesh`, a clipped first syllable).
- An unknown name with `limits.confirm_new_customer` → needs_clarification `new_customer`; `candidates` = up to two
  close customers. Answers: `haan`, `naya`, `banao`, `bana do` → ok with `new_customer: true`; `nahi` alone →
  rejected `cancelled`; `pehla` / `doosra` (`first` / `second`) → the first or second candidate; the close name,
  `wahi` or `purana` → the only candidate; any other name → 1.8 again.
  Without the flag an unknown name is returned as before.
- A known customer's name alone (`Ramesh`) → needs_clarification `missing_amount`; the pending event holds only the
  customer. `340 udhaar` completes it; `total` or `hisaab` answers the balance. An unknown word alone → rejected
  `not_ledger`.
- A `gali ...` tag is shown whole in a same-name question.

Glued tokens (F01 to F05)
- A letters-to-digits boundary always splits (`ko500`, `rs500`, `500rs`).
- A token that is not a known word, a number or a stored name is split only when it can be cut completely into
  [stored or carried name] + [particle `ne|ko|ka|ke|ki|se|pe`] + [number words], any part optional
  (`kofivehundred` → `ko five hundred`, `sunitako` → `sunita ko`, `paanchsau` → `paanch sau`). Longest match first.
- A token that cannot be cut completely stays whole. A stored name is never split (`Konda`). Two complete cuts with
  different meanings → `missing_amount`.

Not entries (G01 to G09, I01 to I03)
- `dena hai`, `dene hain`, `dena padega`, `dunga`, `dega`, `denge`, `de dunga`, `de dega` → rejected `future`. This
  replaces the `ambiguous_direction` rule for `dena hai` in 1.4 and 1.12.
- A conditional (`agar ...`, `if ...`, `... de to ...`) → rejected `future`.
- Hearsay (`bol raha tha`, `keh raha tha`, `kehta hai`, `bata raha tha`, `said`, `was saying`) and a tag question about
  the past (`... diya tha na?`, `... hai na`) → `confirm_entry` type `hearsay` with the entry as heard.
  A plain yes/no question (`Kya Ramesh ne 500 diye the?`) stays rejected `not_ledger`.
- `haan`, `nahi`, `yes`, `no` alone with nothing pending and no `last_event` → rejected `no_question`.
- An amount in a sentence with a question word (`kitna`, `kitne`, `kab`, `how much`) is never an entry:
  `Ramesh ka 340 kitna hua?` → balance query for Ramesh.
- Supplier words (`wholesaler`, `supplier`, `distributor`, `dealer`, `agency`, `company`, `thok wale`, `maal wale`,
  `maal ka paisa`, `mandi`), expense words (`kiraya`, `rent`, `bijli`, `salary`, `tankhwah`, `kharcha`, `petrol`,
  `EMI`, `kist`, `tax`, `recharge`, `bill bhara`) and cash-sale words (`becha`, `bikri`, `cash sale`) →
  rejected `out_of_scope`, unless the word is a stored customer name. `cash` and `nakad` alone are payment words
  (`Ramesh ne 500 nakad diye` is a payment).

Bills and settlements (H01 to H10; they need `customers[i].balance`)
- H01: `bill N1 (hai), N2 diya, baaki udhaar` → `confirm_entry` `computed`: one credit of N1 − N2
  (`confirm.bill`, `confirm.paid`). N2 ≥ N1 → rejected `out_of_scope`. The customer is named, carried over or asked first.
- H02: `N1 udhaar, N2 discount / chhoot / kam` → `confirm_entry` `computed`: one credit of N1 − N2.
- H04, H07: `X ne poora / saara de diya`, `X ka hisaab barabar / saaf / clear / chukta`, `X ne udhaar chuka diya` →
  with a balance above zero, `confirm_entry` `settle`: a payment of the whole balance (`confirm.balance`). Otherwise
  the result is the balance query.
- H05: `X ne aadha de diya` → an even balance above zero: `confirm_entry` `half`, a payment of half. Otherwise
  `missing_amount` with kind `payment`.
- H06: `X ka baaki chhod do`, `maaf kar do`, `write off` → with a balance above zero, `confirm_entry` `writeoff`: one
  `writeoff` event for the whole balance. Otherwise the balance query.
- H08: a payment by a known customer that is more than their balance plus this utterance's credits for them →
  `confirm_entry` `overpayment` (`confirm.balance`). Not asked for a new customer, for `advance`, or when `balance`
  is absent from `ctx`.
- H09: `round off kar do` → when the balance is not a multiple of 10, `confirm_entry` `roundoff`: a `writeoff` of
  balance mod 10. Otherwise `missing_amount` with kind `writeoff`.
- H10: `total N ho gaya`, `ab N baaki`, `kul N` beside an entry states a balance. It is never an entry and never an
  amount candidate (`Ramesh ka 340 udhaar, total 800 ho gaya` = one credit of 340).
- K01: a complete entry equal to one of `last_events` (customer, kind, amount, date) within `limits.duplicate_s` →
  `confirm_entry` `duplicate`. Carry-over forms (`aur 200`) are never asked.

Words the parser does not know (strict mode)
- With `limits.strict`, an utterance is saved without a question only when the parser knows every word in it:
  digits and number words, currency words, particles, direction, date and action words, fillers, common function
  words of Hindi and English, and the words of stored customer names, aliases and tags.
- When an `append` or `amend` result would be saved and the utterance holds a word outside that vocabulary, the
  result becomes `confirm_entry` with `confirm: {"type": "unsure", "words": [...]}` and the parsed events as
  pending. Yes saves them, no cancels.
- The gate is the last step: every rule above decides first (a quantity is still `Kitne ka?`, a supplier is still
  `out_of_scope`, an unknown name still gets the `new_customer` question and counts as explained once it is asked).
  Queries, undo and answers to a pending question are not gated.
- So an unexpected sentence can end in a question or a refusal, and never in a silent save. What is left is a
  sentence whose every word is known but means something else, and speech-to-text hearing one valid word as another;
  the readback and `nahi` cover those.

Queries and reminders (J06, J07, J09, Q08)
- `is hafte`, `pichle hafte`, `is mahine`, `pichle mahine`, `this / last week`, `this / last month` set `period` for
  `credit_total`, `payment_total` and `daily_summary` (`Is mahine ka total` → `daily_summary`, `this_month`).
  A period the parser does not know (`pichle saal`) → `unclear_date`. A query never falls back to today.
- `X ka kab se baaki hai` → `due_since`. `Total udhaar kitna hai`, `kul baaki`, `sab ka total`, `total outstanding`
  with no customer and no day word → `outstanding_total`.
- `X ko reminder bhejo / bhej do`, `send X a reminder (for N)`, `remind X` → action `reminder`.

### 1.15 Rules from the second review (v1.3; they override anything above that disagrees)

The test of every rule here: an entry is saved without a question only when the words leave one reading, and a
question that leads to a save always states the customer, the amount and the direction.

Answers to a pending question
- An answer that holds an undo or stop word (`cancel`, `hata do`, `mita do`, `delete`, `undo`, `rehne do`, `mat likho`)
  is no, whatever else it holds (`ok cancel karo`, `haan hata do`). Only the undo-check question
  (`... Hata doon?`) reads `hata do` as yes.
- A negated or two-name answer never picks the name that was denied: `X nahi Y` → Y; `X nahi`, `X ya Y`, `X aur Y` → a
  failed attempt. The same for tags (`chai wale nahi`).
- Two amounts in an answer (`300 ya 400`, `teen chaar sau`, `likh do sau`) → `confusable_number` with both, as in a
  fresh sentence. An answer that carries an amount different from the pending one, where no amount was asked for
  (`chai wale ko 300` to a same-name question about 200) → a failed attempt.
- Strict mode follows the entry through every question: when the first utterance held unknown words, the entry is
  saved only after an `unsure` confirmation that states it, even if another question (new customer, date, customer)
  was asked and answered first.

Corrections, undo and delete requests
- An undo word together with an amount or a full entry (`Ramesh ka 340 udhaar hata do`, `340 wali entry hata do`,
  `cancel Ramesh ko 500 udhaar`) is never an append. It gets the undo-check question, which always names the real
  last entry, so a yes can never remove a different one.
- A correction or a bare `cancel` / `hata do` is applied only when `last_turn.action` is `append` or `amend`. After a
  question (answered, dropped or expired), a query, a rejection or an undo, a correction is rejected `no_last_event`
  and a bare `cancel` / `hata do` / `undo karo` gets the undo-check question naming the entry; an older entry is
  never changed silently.
- A correction that changes nothing (`nahi 340` on a 340 entry) → needs_clarification `unclear_correction`.
- A write-off is a last event like any other: `undo karo` reverses it and `nahi, 100` amends it.

Carry-over
- Across turns, the customer of the last event is taken only by an explicit continuation form: `aur N ...`, `N aur`,
  a bare amount with only an action word (`200 add kar do`), or a pronoun. Any other new turn with an amount and no
  name (`500 udhaar`, `200 jama`, `kal 500 le gaya`, `300 payment aaya`, `200 diya`) → `missing_customer`; the answers
  `wahi`, `usi ka`, `same` pick the customer of the last event.
- Inside one utterance a later clause with no name still takes the customer of the clause before it
  (`Ramesh ka 340 udhaar, kal 200 diya tha`).
- A single word at the start of a clause, directly before the amount, is the customer name even when it is a kinship
  word, an honorific or also a common word (`Chacha 200 le gaye`, `Seth 500 le gaya`, `Diya 200 le gayi`). It is
  never dropped in favour of the carried-over customer.

Numbers that are not amounts
- A number directly before a goods noun with no currency word is a count (`12 ande`, `50 bidi`, `10 cigarette`,
  `12 Maggi`, `12 eggs`): with a customer and a credit word → `Kitne ka?`. A count beside an amount
  (`20 rupaye ke 3 packet`, `2 baar 100`) → `confirm_entry` `unsure`.
- `saath` / `sath` is 60 only inside a number phrase or directly before a currency word. Elsewhere it means "with"
  and is not a number; Devanagari `साथ` is never a number (`साठ` is 60). A bare Roman `saath` in the amount position →
  `plausibility`.
- Words that change an amount are never harmless: `aadha`, `double`, `zyada`, `kam`, `se zyada`, `nahi to`,
  `lagbhag`, `around`, `about` beside an amount → `confirm_entry` `unsure`.

Questions, negations and guesses
- A sentence that ends in `kya`, in `?`, or in `right` / `na`, or starts with an English question word or auxiliary
  (`has`, `is`, `did`, `does`), and would otherwise be an entry → `confirm_entry` `hearsay`. It is never saved directly.
- `na` directly before a verb is a negation (`500 na diye`, `na likhna`) → rejected `negated`. English `did not`,
  `didn't`, `not paid`, `has not`, `never` → rejected `negated`; such a sentence is never a correction.
- `bina N diye` (without paying) → rejected `negated`. `hoga`, `shayad`, `maybe`, `probably` → `confirm_entry` `hearsay`.
- A stative sentence (`Ramesh ka 500 udhaar hai`, `... tha`, `Ramesh pe 500 udhaar hai`) → `confirm_entry` `hearsay`.

Direction
- English: `took N from X` → payment (as `X se N liye`). The shop paying or owing the customer (`I paid X N`,
  `paid X N`, `X was paid N`, `X got N`, `X received N`, `I owe X N`, `I borrowed N from X`, `X lent me N`) →
  rejected `out_of_scope`. `X and Y paid N` → `missing_amount`.
- Goods returned (`... ka maal lautaya`, `saaman wapas kiya`) and goods bought from the customer
  (`X se N ka saaman liya`) → `ambiguous_direction`.

Dates and time words
- `subah`, `dopahar`, `shaam`, `raat` directly before `ko` are time words and are ignored
  (`Ramesh ne raat ko 500 diye` = payment 500 today). Before another particle or at the start of a clause the
  same word can be a name (`Sham ne 200 diye`).
- `N hafte / mahine / saal pehle` → `unclear_date`; a date never falls back to today.

Other
- `yaad` is not a reminder word. A token is split into particle and number (`ko` + `char`) only when the sentence
  then has a stored or carried customer; otherwise it stays whole and is a name (`Kochar ko 500 udhaar`).

Names that speech-to-text repeats, splits or joins (from a real voice session; they need `ctx.customers`)
- A name written twice in two spellings is one name: when every spoken name word is the same person (1.12) as one
  and the same stored customer, the words collapse to that customer (`Ramish Ramesh ne 5 diye` → Ramesh). A real
  two-word name (`Ramesh Chopra`) and two different stored customers are never collapsed.
- A name written in two pieces, or two pieces written as one: when the spoken words joined together are the same
  person as exactly one stored name joined together, it is that customer (`Diwa Kar` → stored `divakar`;
  `Mohanlal` → stored `mohan lal`). With two stored customers that fit, nothing is picked and the new-customer
  question decides.
- In the close-name comparison (1.14, E09) `sh`, `ch`, `th`, `kh`, `gh`, `ph`, `bh`, `dh` and `jh` each count as one
  consonant, and a differing first consonant counts like any other (`Jamesh` offers Ramesh, `Tanishke` offers
  Tanishk).

### 1.16 Rules from the third review (v1.4; they override anything above that disagrees)

Questions state what will be saved
- `pending.index` is the event a question is about. The server builds the question from that event, never from the
  first event in the list.
- Each distinct unknown name in an utterance gets one `new_customer` question, and one yes never opens two
  accounts (`Vikram ko 500 udhaar aur Sunit ne 200 diye` asks about Vikram, then about Sunit with Sunita offered).
  The same name in several events is asked about once (`Mohan ka 340 udhaar, kal 200 diya tha` → one question,
  `haan`, both entries saved).
- When the pending result holds two or more events and a question about a missing or ambiguous field was asked
  (direction, amount, customer, date, which customer, two amounts), or an answer changed a field, the save is
  preceded by `confirm_entry` type `review`, whose question lists every entry (`2 entry likhun: Ramesh ke ₹500
  udhaar, Sunita se ₹200 jama?`). Yes saves, no cancels. New-customer questions alone do not need it: every entry
  was complete in the utterance, and the saved reply lists them.
- A new-customer question raised by a correction says that an entry is being changed (`confirm.type: "amend"`,
  below); it never replaces an entry after a bare yes to "naya grahak hai?".

Numbers that are dates, times or balances
- `N <month name>`, `N/N`, `N-N-N` and a year (`2026 mein`) are dates → `unclear_date`; `N:N`, `N baje` are times and
  are ignored. None is ever an amount or a name (`Ramesh ko 21 November ko 500 udhaar`).
- `N baaki hai / hain / tha`, `baaki N` beside an entry states a balance (as H10) and is never an entry
  (`Ramesh ne 200 diye 300 baaki hai` = one payment of 200).
- `X ke N mein se M aa gaye / diye` → payment M; N is the total and is ignored.
- `N rupaye M paise` is not a whole-rupee amount → `missing_amount`.
- A comma or full stop inside a number phrase does not split it (`teen sau, chalis` = 340).

Number words and names
- A word that continues a number phrase is part of the number even when it is also a stored name
  (`teen sau das` = 310 with a customer "Mohan Das"). The name reading applies only where a name can stand: at the
  start of a clause or directly before a particle.
- Words that are never a new customer name: the function words in the `nevername` list of `vocab/keywords.json`
  (`badal`, `badlo`, `sirf`, `lekin`, `jisme`, `usme`, `isme`, `hi`, `edit`, `amount`, `correction` ...), `entry`, and
  month and weekday names. Other vocabulary words (`karo`, `karke`, `kiya`, `kam`, `change`, `byaj`, `interest`) are
  a name only directly before a particle (rule 1.12: `Abhi ko 200 udhaar`, `Diya ko 200 udhaar`), where the
  new-customer question still asks first; anywhere else they are never a name (`change karke 430 kar do`). An
  utterance with no usable name never produces a question about an empty name.
- Name matching also folds a final `y` and `i` (`पिंकी` = `pinky`) and `x` with `ksh` (`Laxmi` = `Lakshmi`).

Corrections phrased as instructions
- `usko / uska / isko N kar do`, `N karo`, `wo galat tha, N likho`, `N likhna tha`, `sorry N likho`,
  `change karke N kar do` right after an entry are corrections, never a second entry: `confirm_entry` type `amend`
  with `confirm: {"type": "amend", "old": 340, "new": 430}`; yes amends the entry. A plain correction right after
  the entry (`nahi, 430`, `galat, 430`, `wrong, 430`) stays a direct amend (1.6).
- A correction after a turn that was not an entry (a question, a query, a rejection, a silence) is no longer rejected
  outright: when the session still has a last active entry it gets the same `amend` confirmation naming that entry.
  After an undo it is still rejected `no_last_event`.
- A correction that changes nothing, or `amount galat hai` with no new amount → `unclear_correction` with the
  unclear-correction wording (`Sahi amount boliye, ya hata do boliye.`), never the replace wording.
- The over-payment check on an amend leaves out the entry being replaced.

Reductions and mixed sentences
- `write off`, `maaf`, `chhod do`, `discount`, `chhoot`, `kam kar do` with one amount (`Ramesh ka 200 maaf kar do`,
  `Ramesh ko 50 ka discount diya`) → `confirm_entry` type `writeoff` for that amount. Never a credit.
- Three amounts where the first minus the second is the third (`340 ka saaman liya, 300 diye, 40 udhaar likh do`) →
  `confirm_entry` `computed`: one credit of the third amount.
- A credit clause followed by a payment cue with no amount of its own (`500 ka saaman liya aur payment kar diya`,
  `500 udhaar diya tha wo aa gaya`, `... usne de diye`) is never saved as the credit alone → `ambiguous_direction`.
- `de do`, `de dena` (an instruction to give) → `ambiguous_direction`. `X ko N advance diya` → `ambiguous_direction`.
- An entry and a query in one sentence (`Ramesh ne 200 diye ab kitna baaki hai`) → `confirm_entry` `hearsay` for the
  entry; the entry is never dropped silently.
- `X ko kitna dena hai`, `X se kitna lena hai` → balance query.
- Payments said with `mil gaye`, `aa gaye`, `Google Pay / PhonePe / Paytm / UPI kiya`, `transfer kiya`, `bheje`,
  `bhej diye` → payment.
- One customer paying for another (`Sunita ne Ramesh ke 200 diye`) → rejected `out_of_scope`; the parser does not
  guess whose account moves.

Answers
- A direction word in an answer is honoured through `nahi` and `to` (`nahi 300 jama` to a credit confirmation is a
  conflict, so a failed attempt; it never saves the pending kind). Same-name answers get the same conflict check.
- `usko / unko / inko diye` → credit; `usne / unhone / inhone diye` → payment.
- Also accepted: `haan udhaar`, `le gayi`, `liye`, `udhaar N` and `jama N` when N is the pending amount,
  `jama nahi udhaar` (the word after `nahi` wins); `likh do` as yes to a "likhun?" question; `kal ka`, `aaj hi` as
  date answers; `mat banao`, `nahi banana` as no to the new-customer question. A date word in a customer answer is
  kept (`Ramesh ka kal ka`).
- The duplicate question takes only yes or no; a number is a failed attempt.
- Same-name and which-entry questions name what they are about: the clause's amount for a same-name question in a
  two-clause sentence, and the customer for each entry in a which-entry question.

### 1.17 Questions in sentences with several entries (v1.5; they override anything above that disagrees)

One question, one entry
- Every question about one event of several carries `pending.index` for that event. This includes `plausibility`, the
  small-amount check and `confirm_entry` types `overpayment`, `settle`, `half`, `writeoff` and `roundoff`. The parser's
  `question` and the server's reply use that event's customer and amount and that customer's balance; a reply never
  pairs one customer's name with another customer's balance or amount. `Ramesh ne 500 diye aur Mohan ne 200 diye`
  with Mohan owing 140 → `confirm_entry` `overpayment`, `index: 1`, `confirm.balance: 140`,
  `Mohan ke sirf ₹140 baaki hain. ₹200 hi likhun?`.
- Each event is checked on its own and a yes answers only the question that was asked. The amount checks
  (plausibility, small amount) run first, in event order, then the over-payment and other one-entry confirmations,
  in event order. When a later event also needs a confirmation it is asked next; the entries are saved when no
  event is left to confirm.
  `Ramesh ka 99000 udhaar aur Mohan ka 88000 udhaar` → `₹99,000, pakka?`, `haan`, `₹88,000, pakka?`, `haan`, saved.
  `Ramesh ne 2000 diye aur Mohan ne 200 diye` with both above their balance asks about Ramesh, then about Mohan.
  A no to any of them cancels the whole utterance. An amount is still never asked about twice.

Balance instructions and reductions stay in their clause
- `poora de diya`, `aadha de diya`, `baaki maaf kar do`, `round off kar do` and a reduction with an amount
  (`200 maaf kar do`) belong to the clause they are spoken in. Their customer is that clause's customer, and an amount
  is never taken from another clause. No other entry of the utterance is changed or dropped.
- In an utterance with other entries a balance instruction is not worked out from the balance. Its event keeps its
  own customer and kind (`payment` for `poora` / `aadha`, `writeoff` for `maaf` / `chhod do` / `round off`) and has no
  amount → needs_clarification `missing_amount` with its `index`; the other entries stay in the pending result.
  `Ramesh ka 200 udhaar aur Mohan ka baaki maaf kar do` → events [credit 200 for Ramesh, writeoff for Mohan with no
  amount], `index: 1`; it never becomes a write-off of 200 for Ramesh.
- A reduction with its own amount in its own clause (`Ramesh ka 200 udhaar aur Mohan ke 50 maaf kar do`) is a
  `writeoff` event of that amount for that clause's customer: `confirm_entry` `writeoff` with its `index`; the other
  entry stays in the pending result.

What was said is kept
- An utterance with exactly one amount and one direction never produces a pending event without that amount.
- Two names with one amount and one direction word, where the amount cannot be given to one of them
  (`Ramesh ka khata, Sunita ko 1500 udhaar`; `Maya, Shivakumar ko 1500 udhaar`, where a stray word was heard as a
  name; `Ramesh aur Sunita ko 500 udhaar`) → needs_clarification `missing_customer`. The pending event keeps the
  amount, the date and the kind when the words give one, and has no customer. The answer is a name; 1.8 and the
  new-customer question apply, and a missing direction is asked after it.
- `Ramesh ka 100 udhaar aur Sunita ko udhaar` (two direction words, one amount) stays `missing_amount` with
  `index: 1`, and `Ramesh ne 500 diye Sunita bhi` stays `missing_amount` (1.4, 1.15).

### 1.18 Rules from the fourth review (v1.6; they override anything above that disagrees)

Purchases, cash on the spot and repayments
- A purchase with one amount and a word that says the money was handed over is a cash sale: rejected
  `out_of_scope`, never a credit. Purchase words: `N ka saaman / maal liya`, `le gaya`, `saaman diya`, `bought`,
  `purchased`. Handed-over words, in the same clause or a later one with no amount of its own: `paise de diye`,
  `usne de diye`, `de gaya`, `payment ho gaya / de diya / kar diya`, `cash / nakad / UPI / Paytm / PhonePe / online`
  with or without a verb (`cash mein liya`, `nakad liya`), `paise le liye`, `hisaab barabar`, `in cash`, `and paid`.
  `Ramesh ne 200 ka saaman liya paise de diye` and `Ramesh bought goods for 200 in cash` save nothing.
- A credit said in the past with a word that says it came back (`N udhaar diye the, aaj de gaya`,
  `N udhaar diya tha wo aa gaya`) → `ambiguous_direction` (1.16), never the credit alone.
- `udhaar` together with a verb of the customer giving and no `ko` (`X udhaar ke N de gaya`, `X N udhaar de gaya`,
  `X udhaar N de gaya`, `udhaar ke N X de gaya`) → `ambiguous_direction`. `X ko N udhaar de diya` stays a credit.
- A purchase amount, a paid amount and a word for the rest (`N ka saaman liya M diye baaki udhaar`,
  `... baaki likh do`, `N ka saaman le gaya M de gaya baaki udhaar`) → `confirm_entry` `computed`: one credit of
  N - M, as H01 does with the word `bill`. `N ka saaman liya M baaki hai` → `confirm_entry` `computed`: one credit
  of M.
- `computed` needs those words: an amount with a bill or purchase word, an amount with a paying word, and a word
  for the rest or the credit. Any other three amounts stay three amounts and are asked about
  (`500 ka note diya, 200 kaate, 300 wapas kiye`; `300 udhaar, 100 chawal ka aur 200 aate ka`).
- A payment and "drop the rest" for the same customer (`X ne N diye baaki chhod do`, `... aur baaki maaf kar do`):
  with a balance B above N → two events, payment N and writeoff B - N, behind `confirm_entry` `review`. With no
  balance in `ctx`, or B not above N → the payment and a writeoff with no amount (`missing_amount`, its index).
  `baaki M chhod do` gives the writeoff its own amount M. The paid amount is never the write-off amount.

Words that name the account are not a direction
- `X ke naam`, `X ke naam pe / se / ka` and `X ke khate mein` name the account. They mean a credit only when the
  clause has no direction word. A payment word in the clause wins (`jama`, `payment`, `aaye`, `aaya`, `mile`,
  `mila`, `kaat do`, `received`): `Ramesh ke naam 200 jama karo`, `Ramesh ke khate mein 200 payment likh do` →
  payment. A credit word and a payment word together → `ambiguous_direction`.

A stray word is not a customer
- A new customer name stands only directly before a name particle, in English as the subject directly before the
  verb or after `to` / `from` / `for`, or as the first word or words of a clause directly before the amount.
  Anywhere else an unknown word is an unknown word: in strict mode the entry gets the `unsure` confirmation, and
  the word never becomes a customer (`200 udhaar rakha`, `100 kam karo`, `paid 200 out of 500`, `300 by UPI`,
  `he took another 100`, `300 chutte wapas diye`).
- When the name words start with a stored customer's name and go on with a word that is not part of a stored name
  or tag (`Ramesh Chopra ko 200 udhaar`, `Ramesh wants 200 on credit`), the new-customer question offers the stored
  customer (`Ramesh Chopra naya grahak hai, ya Ramesh?`).
- Common English adverbs and auxiliaries are fillers (`also`, `finally`, `already`, `just`, `again`, `has`, `have`,
  `had`), and `given`, `purchased`, `cleared`, `collected` are verbs: `Ramesh also paid 200` and
  `Ramesh has given 200` are payments by Ramesh.
- A close name (1.14, E09) and the stored-name case above always ask, whatever `limits.confirm_new_customer` says.
  With that switch off and strict mode on, a name that is not in the roster is accepted without a question only
  directly before a particle with every other word known.
- Never a name: English pronouns and function words (`I`, `me`, `my`, `he`, `she`, `his`, `her`, `they`, `it`,
  `another`, `out`, `by`, `in`, `of`, `open`, `create`, `go ahead`), `ise`, `isse`, `inhe`, `unhe`, `use`, `sabko`,
  `sab`, `kisi`, `koi`, `jo`. English `he` / `she` / `they` / `his` / `her` carry over like the Hindi pronouns
  (`he paid 200` after an entry for Ramesh).
- An adverb before `se` is a filler and the word is never a name: `jaldi se`, `yaad se`, `dhyan se`, `aaram se`,
  `galti se`.
- A goods word (the `goods_words` list: `chawal`, `aata`, `doodh`, `ande` ...) is never a customer name, also
  directly before a particle (`100 chawal ka aur 200 aate ka`).
- `his` / `her` / `uski` / `uska` followed by a relation word (`his wife paid 200`) is never a new customer: with
  a carried customer it is that customer's relation (1.13), otherwise `missing_customer`.
- A close name (1.14, E09) differs from the stored name in one consonant and in nothing else: after the 1.12
  folding the vowels are the same in the same places, or the two differ only by a final vowel (`Jamesh` and
  `Ramesh`, `Rakes` and `Rakesh`, `Kamala` and `Kamal` are close; `Mohan` and `Imran` are not).

Answers
- Yes with an address word or a filler is yes: `haan bhai`, `haan bhaiya`, `haan sir`, `haan madam`, `haan beta`,
  `theek hai bhai`, `hau`, `yeah open it`, `go ahead`, `create`, `khol do`. In an answer to the new-customer
  question only a stored name, the offered name or a name directly before a particle is another name.
- A new-customer question that offers a close customer is an either-or question. `naya` / `banao` / `new` opens
  the new account; the offered name, `wahi`, `purana` or `pehla` picks the stored customer. A bare yes is not an
  answer: a failed attempt, asked again.
- A date word beside a direction answer is kept (`kal udhaar`, `udhaar kal ka` → the credit, dated yesterday). An
  answer to an open question is read as a query only when it is a complete query.
- In a which-entry question the customer's name picks the entry (`Mohan`, `Mohan wali`).
- `aur` with an amount after an entry (`uska 5 rupaye aur likh do`) is a new entry for that customer, never an
  amend.
- To `Pichli entry hata kar ... likhoon?` a no cancels: nothing is saved and the old entry stays. The question
  names the new entry (5.1).
- An utterance that is refused when it is parsed on its own (`negated`, `future`, `out_of_scope`, `too_large`,
  `invalid_number`) is never an answer to an open question, whatever number or name it holds. The refusal is the
  result and nothing is saved: with `₹75,000, pakka?` open, `Ramesh ka 200 udhaar nahi hai` saves nothing, and
  with `₹340 ya ₹400?` open, `Ramesh ne 200 ka saaman liya paise de diye` saves nothing. A `negated` utterance
  cancels an open yes-or-no question. After any other refusal the open question is closed as well and the entry
  has to be said again.
- With `limits.noisy` (3.5) a correction that would be applied is confirmed with the `amend` confirmation (old and
  new amount), not with the entry wording.
- Same-name answers: ordinals follow the order the question was spoken in (the order of `candidates`), for two
  customers as for three: `pehla`, `pehle wale` and `pehla wala` are the first one spoken, whatever its tag.
  The customer with no tag is spoken and answered as `bina tag wale`. `teesra` is accepted when three were
  offered, and an answer that fits none of the offered customers is a failed attempt. After the answer the
  instruction that raised the question goes on (`Suresh ne poora de diya` → which Suresh → the settle confirmation).

Corrections said as a restatement
- Right after an entry these correct it and are never a second entry: `X ka N likhna tha` and `X ka N udhaar tha`
  for the same customer and kind, and with no name `N kar do`, `N karo`, `N kar dijiye`, `amount N karo`,
  `sorry N`, `actually N`, `it was N`, `I meant N` → `confirm_entry` `amend`. They never ask `Kiska khata?`.

Not that entry
- `X ka udhaar N ho gaya` states a balance → the balance query. `X ka N udhaar batao` → the balance query.
- `X se N vasool karne hain`, `N lene hain`, `N lena hai` → rejected `future`.
- A negation after the verb (`likhna mat`, `mat likhna`, `na likhna`) → rejected `negated`.
- A question clause or a stative past clause inside a longer utterance (`... diye the kya aur ...`,
  `... udhaar likha tha`) → `confirm_entry` `hearsay` for the whole utterance.
- Given and taken back (`200 diye the wo wapas le gaya`) → `ambiguous_direction`.
- `kal` with an instruction for later and no past verb (`likh dena kal`) → `unclear_date`.

Dates and numbers
- `last night`, `kal raat`, `yesterday evening` → yesterday. `this morning`, `aaj subah` → today. Any other
  `last ...` phrase → `unclear_date`.
- A date word before the first name applies to every clause that has no date word of its own
  (`kal Ramesh ne 200 diye the aur Mohan ne bhi 100 diye the` → both yesterday).
- A number up to 31 directly before `ko` and beside an amount is a day of the month → `unclear_date`
  (`Ramesh ne 15 ko 200 diye`).
- `sath sau` / `saath sau` → `confusable_number` with 700 and 6,000.

Guards
- Over-payment adds up the payments of one customer in the utterance before it compares with the balance
  (`Mohan ne 100 diye aur 100 diye` with 140 due asks).
- A reduction with an amount above the balance → `confirm_entry` `writeoff` with `confirm.balance`, and the
  question states the balance (5.1). For a customer who owes nothing → the balance query.
- The duplicate question is asked every time the same entry is repeated inside the window, also the third time,
  and for an event of a longer utterance that repeats the last saved entry.

English
- An utterance whose words, apart from names and numbers, are English carries `lang: "en"`
  (`Ramesh bought items worth 250 on credit`, `Ramesh paid 200 this morning`).
- `paid in full`, `paid everything`, `paid the full amount`, `cleared everything` → settle (H04);
  `write off X's balance` → write-off (H06). `X paid N not M` with no earlier entry → `confirm_entry` `hearsay`
  for N.

### 1.19 A question is never an entry (v1.12; overrides anything above that disagrees)

Found by running hard sentences with the LLM fallback on (2026-11-22): two questions became entries.
`Pichli baar Mohan ne kitna diya tha aur kab?` became a payment with a missing amount, and the answer `300` saved
a ₹300 payment without a read-back. `Meri kul udhaari kitni hai, aur usme se kitna 30 din se purana hai?` became a
₹30 credit with a missing customer.

- A sentence that asks something never becomes an entry or a pending entry (no `missing_amount`,
  `missing_customer`, `ambiguous_direction`, `unclear_date` or `confirm_entry` question about an entry). A sentence
  asks something when it has a question word (`kitna`, `kitni`, `kitne`, `kab`, `kaun`, `kaunse`, `kisne`, `kisko`,
  `kiska`, `kya`, `kaise`, `kahan`, `kyun`, `list`, `batao`, `bataiye`, `dikhao`, `how much`, `when`, `who`,
  `which`, `what`) or ends in `?`, and it has no complete entry (customer, amount and direction all spoken).
  - When it matches a query of 1.7 or 1.14 it is that query (`Meri kul udhaari kitni hai` → the outstanding total;
    `Suresh ka kitna baaki hai?` → the balance, with the same-name question when needed).
  - Otherwise it is rejected `not_ledger`: nothing is asked about an entry and nothing is saved.
  - A complete entry that happens to hold a question word stays an entry under the usual rules (it is confirmed
    when strict mode or another rule asks).
  - A sentence that is only a choice between two amounts and ends in `?` without a question word
    (`teen sau chaalis ya saat sau chaalis?`) is the shopkeeper's own doubt, not a question to the app: it keeps the
    confusable-number question of 1.14 A12, and the entry is read back before it is saved.
- A number spoken directly before a time unit is never an amount: `din`, `dino`, `dinon`, `hafta`, `hafte`,
  `haftay`, `mahina`, `mahine`, `saal`, `ghanta`, `ghante`, `minute`, `minat`, `baje`, `tarikh`, `day`, `days`,
  `week`, `weeks`, `month`, `months`, `year`, `years`, `hour`, `hours` (`30 din se purana`, `do hafte`, `5 baje`).
  Relative dates (`3 din pehle`) keep working as dates.
- An amount, customer or direction given in answer to a question that the first sentence raised is read back for a
  yes (`confirm_entry`) before anything is saved whenever that first sentence held a question word. This is a second
  guard behind the first rule.

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

### 2.1 Ledger additions (v1.2)
- Write-off: column `events.adjustment TEXT` (NULL or `'writeoff'`), added with `ALTER TABLE` when it is missing. A
  write-off is stored as `kind='payment'` with `adjustment='writeoff'`, so the balance arithmetic is unchanged. It is
  left out of payment totals and summaries, and the API reports its `kind` as `"writeoff"`.
- Idempotency (K01, O02, O05): the client may send `utt_id` with a turn. It becomes the utterance id, and the
  utterance row is written in the same transaction as the turn's events. A turn whose `utt_id` was already processed
  writes nothing and gets the first result again with `"duplicate": true`. The id is bound to the sentence, not to the
  session (a queued sentence may be resent after a page reload): the same id with a different sentence gets an
  `error` message with code `utt_id_reused`, and nothing is saved.
- The utterance record also keeps `device_ts`, the client's own clock reading, when the client sends one (C09). Every
  `ts` in the ledger is the server's clock in `SHOP_TZ`. A shop day is the calendar day in `SHOP_TZ` (C05, C06).
- `confusions(heard INTEGER, meant INTEGER, n INTEGER, last_ts TEXT, PRIMARY KEY(heard, meant))`: one count each time
  an amend changes only the amount. Pairs seen twice or more are sent to the parser as `ctx.confusables`.
- Customers are never deleted: a trigger aborts `DELETE` on `customers` (K03). The only deletion is the purge of the
  whole database.
- `consent_log(id, ts, customer_id, opt_in)` is append-only. Opting out also removes that customer's pending rows from
  the reminder outbox (Q05).
- Reminders: the message is rebuilt from the balance when the outbox is read, and a customer who no longer owes is
  dropped (Q04). The text is short and names no items (Q03), in the customer's language `ident.lang` (Q07). Outside
  09:00 to 20:00 shop time nothing is queued or returned: `{"reminders": [], "quiet_hours": true}` (Q06).
- `GET /api/ledger?order=created|date`: `created` (default) is newest first by creation, the audit order; `date` is by
  effective date, then creation, for display (C08, K06). `&customer_id=` limits it to one customer.
- Queries: totals over a date range for the periods of 1.14; `outstanding_total` (the sum of the positive balances and
  how many customers owe); `due_since` (payments and write-offs settle the oldest credits first; the date of the
  oldest credit not fully settled).
- `customers_for_parser()` adds `balance` and `usual`.
- Target sizes: 10,000 events and 1,000 customers. Building the parser context and answering any query stay under
  50 ms; customer rows are decrypted once and cached (K05, E15).
- Concurrent writers never see `database is locked`: one write lock per process and a busy timeout (K04).

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
| `{"type":"transcript","turn_id","text","segment","final"}` | `text` is always the whole turn so far (finished segments plus the current partial), so the client replaces what it shows. `final: true` only on the last one |
| `{"type":"result","turn_id","trace_id","status","action","reason"?,"entries":[...],"reply_text","question"?}` | What was understood and saved. `action` is also `"greeting"` or `"none"` |
| `{"type":"audio_start","turn_id","sample_rate":24000,"encoding":"pcm_s16le","channels":1}` then binary frames then `{"type":"audio_end","turn_id","cancelled"?}` | The spoken reply |
| `{"type":"timing","turn_id","trace_id","ms":{"stt_final","parse","db","tts_first_chunk","end_to_first_audio","gnani_stt_latency"}}` | Per-hop timings |
| `{"type":"error","turn_id"?,"code","message"}` | |

Entry shape: `{"id","kind","customer":{"id","display","tags"},"amount","date","ts","reversed","reversal_of","replaces"}`
(`replaces`, v1.8: the id of the entry this one corrected, or null; see 3.6).
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

### 3.1 Rules added after the first review
- Disclosure: a session counts as disclosed only when the greeting audio has been sent to its end without being
  cancelled. Until then every spoken reply starts with the disclosure sentence. The web app also keeps the talk button
  disabled until the greeting ends.
- The parser context carries `last_events` (section 1.12). An amend with `target.event_id` reverses that event if it is
  still active and belongs to this session; otherwise the reply is `Pichli entry nahi mili.`
- A new customer with several events in one utterance is announced once. A balance query with
  `query.unknown_customer` answers `{name} ka khata nahi mila.` Totals and the daily summary accept `period: "yesterday"`
  (`Kal ₹{amt} udhaar gaya.`).
- Only replies without a customer name or an amount are cached on disk (greeting, fixed questions, rejections).
- When `ACCESS_CODE` is set, the REST endpoints need it as well (header `X-Access-Code` or `?code=`).
- A relative `LEDGER_DB` is resolved against the repository root, so there is one data folder whatever the working
  directory.
- Speech-to-text turn boundaries: events of an utterance opened before the current `start` are ignored; if the upstream
  socket closes while an utterance is open, the turn fails with an error reply and nothing is saved.
- Text-to-speech: if the socket dies before `start`, reconnect and retry once; the socket is re-opened in the background
  whenever it closes; a cancelled reply never blocks the next turn; `audio_end` is always sent.

### 3.2 Reply language (from the first voice test)
- The session has a language, `hi` or `en`. `hello.lang` sets it (the start screen has one button per language) and
  chooses the language of the greeting. Every parser result with `lang` switches it; a result without `lang` keeps it,
  and so does an answer to an open question ("udhaar" in an English session stays English).
- Every reply exists in both languages. English replies are spoken with TTS `language: "en-IN"` and amounts from
  `number_to_words(n, "en")` followed by `rupees`; Hinglish replies stay as in section 5.
- `result` carries `lang` so the page can switch its labels.

| Moment | English reply_text |
|---|---|
| Disclosure (greeting) | `Hello! I am KhataVaani, an AI assistant.` |
| Credit / payment | `Added ₹{amt} credit for {name}.` / `Received ₹{amt} from {name}.` |
| Past date | `Received ₹{amt} from {name}, dated yesterday.` / `Added ₹{amt} credit for {name}, dated yesterday.` |
| Several entries | `{n} entries: ₹{amt} credit for {name}, and ₹{amt} received yesterday.` |
| New customer prefix | `New account for {name}.` |
| Amend / undo | `Corrected: {name}, ₹{amt} {credit\|payment}.` / `Removed the last entry: {name}, ₹{amt} {credit\|payment}.` |
| Nothing to undo or amend | `No previous entry found.` |
| Confusable number / same name | `₹{a} or ₹{b}?` / `Which {name}: {tag1} or {tag2}?` |
| Missing amount / customer | `How many rupees?` / `Whose account?` |
| Direction | `Did {name} pay, or did {name} take credit?` |
| Plausibility | `₹{amt}, are you sure?` |
| Unclear correction / date | `Say the right amount, or say remove it.` / `Which day? Say today, yesterday or the day before.` |
| Which entry / undo check / replace | `Which entry: ₹{a} credit or ₹{b} payment?` / `I can only remove the last entry: {name}, ₹{amt} {kind}. Remove it?` / `Replace the last entry with this one?` |
| Cancelled / rejected | `Okay, nothing was saved.` / `Sorry, I did not understand. Please say it again.` |
| Balance | `{name} owes ₹{amt}.` / `{name} owes nothing.` / `{name} has paid ₹{amt} extra.` |
| Unknown customer | `No account found for {name}.` |
| Credit total / payment total | `Today ₹{amt} was given on credit.` / `Today ₹{amt} was received.` (zero: `No credit given today.` / `Nothing received today.`) |
| Daily summary | `Today: ₹{c} credit, ₹{p} received. Highest due: {name}, ₹{amt}.` / `No entries yet today.` |
| Top dues | `Highest dues: {n1} ₹{a1}, {n2} ₹{a2}, {n3} ₹{a3}.` / `Nobody owes anything.` |
| Upstream failure | `Network problem, please say it again.` |

### 3.3 Session additions (v1.2)

Messages
| Message | Added field | Meaning |
|---|---|---|
| `hello` | `private`?: bool | Private mode (N08, P06), default false |
| `hello` | `keep_pending`?: bool | With `resume`: keep the open question. Sent only by an automatic reconnect inside a loaded page |
| `text`, `start` | `utt_id`?: string up to 64 characters | The client's id for the turn (idempotency key) |
| `text`, `end` | `client_ts`?: string | The device clock, stored as `device_ts` |
| `{"type":"settings","private":bool}` | new message | Changes private mode inside a session |
| `ready` | `last_turn_id`, `last_result`? | On resume: the last turn and its `result`, so a client that lost the socket can show what happened |
| `result` | `query`? | `{"type","period"?,"customer_id"?}` for a query turn, so the page can show more than was spoken (J04) |
| `result` | `balances`? | `[{"customer_id","display","balance"}]` for the customers a saving turn touched. Shown on screen, never spoken |
| `result` | `candidates`?, `confirm`? | The choices of a question and the `confirm` object of 1.14. `candidates` is `[int, int]` for `confusable_number`, `[{"id","display","tags"}]` for `same_name` and `new_customer`, and `[{"id","kind","amount","customer"}]` (ledger entries) for `unclear_correction` |
| `result` | `duplicate`?: true | The turn repeated an `utt_id`; nothing new was saved. The message is the first result unchanged apart from this flag |

Rules
- A saved entry is read back as what was just entered and nothing else (N08). Balances are spoken only as the answer
  to a question. In private mode the answers to `balance`, `top_dues`, `outstanding_total`, `due_since` and
  `daily_summary` are not spoken: the voice says `Jawab screen par hai.` and `reply_text` holds the answer.
- The parser context gets `last_turn`, `customers[i].balance`, `customers[i].usual`, `confusables` and `limits` with
  `confirm_new_customer` from env `CONFIRM_NEW_CUSTOMER` (default on).
- An open question expires 60 seconds after it was asked (E02). `hello` with `resume` drops it unless `keep_pending`
  is true (L05).
- Recordings (M01 to M03, M07, M09): audio shorter than 0.5 s → `action: "none"`, nothing spoken. A longer recording
  with no speech detected → the silence reply is spoken. Speech with an empty transcript → the rejected reply. A turn
  cut at 30 s → the too-long reply and nothing saved. No final transcript 5 s after `end` → the upstream-failure
  reply and nothing saved (the speech-to-text client still gives up 2.5 s after `commit`, section 4; 5 s is the outer limit).
- `cancel` while a recording is open (after `start`, before `end`) ends that turn like a recording shorter than 0.5 s:
  the audio is discarded, nothing is parsed, and the turn closes with `result` `action: "none"` and no speech.
- The page starts a new session on every page load (no `resume`), so the greeting and the AI disclosure are heard
  again. `resume` is for an automatic reconnect inside a loaded page.
- No message is sent when a question expires; the page closes its question sheet on the same 60-second timer.
- While a question is open, a turn that is not an answer because nothing usable was heard (silence, an empty
  transcript, a recording that was too long, a speech-service failure) keeps the question open and returns it
  again: `result` with status `needs_clarification`, the same reason, candidates and confirm, and a reply that puts
  the short notice before the question (`Kuch sunai nahi diya. Ramesh ke ₹250 udhaar likhun?`). A recording
  shorter than 0.5 s and a `cancel` change nothing and the page keeps its question sheet.
- A repeated `utt_id` whose first result was a question that is no longer the open one is answered with a
  rejected result (`reason: "cancelled"`, the cancelled reply); a replay never puts an old question back on screen.
- A `start` that arrives while an earlier turn is still open: if that turn's entry is already saved the save stands
  and only its speech is cancelled; if not, the earlier turn is dropped. A turn is never saved twice (M10).
- Action `reminder` (Q08): the server checks opt-in, quiet hours and the real balance. A spoken amount that differs
  from the balance → a question (`confirm_entry` shape, `confirm.type: "reminder"`); yes queues a reminder for the real
  balance.
- Server logs never hold a transcript, a name or an amount (P05), nor the access code: library loggers are kept quiet
  and the query string is removed from access-log lines.
- `/ws/session` accepts a browser only from the page's own host, from localhost, or from an origin listed in env
  `ALLOWED_ORIGINS`.
- In private mode a question that states a balance is spoken as `Screen par dekhiye. Haan ya nahi boliye.`; the
  full question stays in `reply_text`.
- At start-up the fixed replies (greeting, questions, rejections, in both languages) are synthesised into the cache in
  the background when a key is set and the audio is missing. Env `TTS_PREWARM` (default 1) (N07).
- `GET /api/metrics`: turns, saves, questions, rejections, corrections (amends), undos and the confusion pairs since
  the database was created; no names.

### 3.4 Typed-sentence queue (v1.6)
- The page holds its queue of typed sentences while any question is open, whoever raised it. A queued sentence is
  never sent as the answer to a question.
- A queued sentence whose replay comes back rejected `cancelled` (its question is no longer the open one) is sent
  once more under a new `utt_id`.
- A same-name question with three customers has three buttons; the third sends `teesra`.

### 3.5 Noise handling (v1.7)

The speech service transcribes people talking in the background as well as the person holding the phone
(`Ramesh ka teen sau chalis udhaar, Mohan ka?`). Steady noise does little harm; other voices do. The server
therefore measures every spoken turn, turns down what is clearly not the speaker, and asks before saving when it
cannot tell the two apart. Code: `server/app/audio.py`, pure Python, one instance per turn.

Measuring (per frame of 1,024 bytes = 32 ms)
- The level of a frame is 10·log10 of its mean square. The speaker level is a peak follower that falls by 0.06 dB
  per frame. While the turn runs, the background level is the upper quartile of the first 8 frames (the pre-roll,
  recorded before the button was pressed); the gate below uses that.
- At the end of the turn `separation_db` = speaker level − the lower of two background levels: that pre-roll level,
  and the level that a quarter of the turn's frames are below (the 25th percentile). The second one keeps a
  speaker who starts talking as they press from counting as background: measured on recorded clips, a clean or
  lightly noisy turn is then never below 20 dB, with or without a lead-in.
- A turn is `noisy` when it has at least 16 frames and `separation_db` is below `NOISE_CONFIRM_DB` (default 14).

Turning the background down (the foreground gate)
- A frame is near when it is at least 8 dB above the background level and at most 14 dB below the speaker level.
  The gate opens after 2 near frames in a row and closes after 16 frames (512 ms) with no near frame. The 8 frames
  (256 ms) before an opening count as inside. To make that possible the stream to the speech service runs 8 frames
  behind and is flushed at the end of the turn, so the end of the turn is not delayed.
- Frames outside the gate are sent at a quarter of their amplitude (12 dB lower), never removed: a wrong decision
  makes a word quieter, it cannot delete it.
- The gate fails open. When the separation at the first opening is below `NOISE_TRIM_DB` (default 16), or the gate
  has not opened 48 frames (about 1.5 s) into the turn, every later frame passes unchanged. With `NOISE_TRIM=0`
  nothing is ever turned down; the measuring still runs.

Being careful
- A noisy turn reaches the parser with `limits.noisy: true`. An append or amend that would be saved is then
  confirmed first, exactly as strict mode does for a word it does not know: `confirm_entry` with
  `confirm: {"type":"unsure","words":[],"noise":true}` and the usual question (`Ramesh ke ₹340 udhaar likhun?`).
  Queries, undo and answers to an open question are not gated. Typed turns are never noisy.
- `timing` carries `"noise": {"separation_db": 23.5, "noisy": false, "turned_down_ms": 420}` for spoken turns, and
  `/api/metrics` counts noisy turns.
- The page shows "Shor zyada hai" beside the reply of a noisy turn and the separation in the latency panel.

Configuration: `NOISE_TRIM` (`1`), `NOISE_TRIM_DB` (`16`), `NOISE_CONFIRM_DB` (`14`; `0` switches the
confirmation off).

### 3.6 Editing on the khata screens (v1.8)

The shopkeeper can change by hand what was written by voice, on the customer screen. The ledger stays append-only
(2): a change is an amend (a reversal plus a new event with `replaces_id`), a removal is a reversal, and both stay
visible in the history. Customer details are the one record changed in place, as tags and the reminder opt-in
already are.

REST. Every call has the same guard as `/api/ledger` (Google sign-in when it is on, `ACCESS_CODE` when it is set).
Bodies are JSON. Amounts are whole rupees; dates are `YYYY-MM-DD` shop days.

| Call | Body | Does |
|---|---|---|
| `POST /api/entries` | `{"customer_id","kind","amount","date"?,"if_balance"?}` | Appends one entry; `date` defaults to today. With `if_balance`, refuses with 409 `balance_changed` when the customer's balance is no longer that figure (the screen was out of date) |
| `POST /api/entries/{id}/amend` | any of `{"kind","amount","date","customer_id"}` | Reverses the entry and saves the changed copy with `replaces_id` = id, in one transaction. A field left out keeps its value |
| `POST /api/entries/{id}/remove` | none | Reverses that one entry |
| `POST /api/customers/{id}` | adds `"display"?`, `"tags"?`, `"phone"?` to `say` and `lang` | Renames the customer, replaces the tags, sets or clears the phone number |

Answers
- Entry calls: 200 `{"ok": true, "entries": [...], "balances": [{"customer_id","display","balance"}]}`. `entries`
  has the shape of `/api/ledger`: the entry reversed first (if any), then the entry saved (if any). `balances` covers
  every customer the call touched.
- Customer call: 200 `{"ok": true, "customer": {...}}` with the shape of one `/api/customers` item.
- `GET /api/customers` items gain `"phone_hint"`: the last four digits of the stored number as `"•••• 3210"`, or
  null. The full number is never sent to the page.
- Errors carry a code in `detail`. 400: `bad_kind` (not credit, payment or writeoff), `bad_amount` (not a whole
  number from 1 to `MAX_AMOUNT`), `bad_date` (not a date, after today in shop time, or before 2000-01-01),
  `nothing_changed` (an amend equal to the entry, or no field given), `bad_name`, `bad_tag`, `bad_phone`. 404:
  `unknown_entry`, `unknown_customer`. 409: `not_active` (the entry was already removed or changed, or it is a
  reversal), `name_taken` (another customer has that name or alias), `balance_changed`.

Rules
- `kind` is `credit`, `payment` or `writeoff`; a write-off is stored as in 2.1. Reversal rows are never edited.
- Events written here have `session_id` `"portal"`, no `utterance_id` and a new `trace_id`. They write no utterance
  row, so `/api/metrics` does not count them as turns, and an amend here never counts a confusion pair (2.1): nothing
  was misheard.
- Names: the display name becomes the key the parser matches: Devanagari romanised, lower case, single spaces, 2 to
  40 characters, only letters, spaces, `.`, `'` and `-`. The old key is kept as an alias, so the old name still finds
  the customer by voice. A name that the number reader reads as a number, or whose every word is a keyword the parser
  never takes as a name (`nevername`), is refused `bad_name`. Tags: up to 3, each made the same way, at most 24
  characters (`bad_tag`). Phone: an Indian mobile number (10 digits, with or without 91, +91 or 0) or null to clear it
  (`bad_phone`); the reminder opt-in does not change.
- Every `/api/ledger` entry carries `"replaces"`: the id of the entry it corrected, or null. The customer screen
  pairs a correction with the entry it replaced by that id; null means the entry corrected nothing. Only an entry
  without the field (an older server) is paired by position.

Voice sessions stay safe
- After an append or amend the session remembers the ids of the events it saved. If any of them is no longer active
  when the next turn's context is built (changed or removed on the khata screen in the meantime), `last_turn` becomes
  `none` before the parser runs, as after any turn that saved nothing. A spoken correction then gets the question
  that names the entry it would change (`Ramesh ki ₹340 udhaar entry ₹250 kar doon?`, 1.16) and saves nothing until
  a yes, or is rejected `no_last_event` when the session has no active entry left; a bare `hata do` gets the
  undo-check question that names the entry (1.15). An older entry is never changed silently.
- An open question is left as it is. An amend it leads to whose target is no longer active saves nothing
  (`entry_not_found`), as before.

The page (`frontend/`)
- Customer screen: an edit button beside the name opens "Grahak badlein" (name, tag, phone). Tapping the balance
  opens "Baaki badlein": the new balance; the difference is written as one entry (higher: `credit`; lower: the
  shopkeeper chooses Jama `payment` or Maaf `writeoff`) and sent with `if_balance`. "Nayi entry" above the history
  adds an entry by hand.
- Each active row of the history opens "Entry badlein": amount, Udhaar / Jama / Maaf, date (not after today) and the
  customer. "Entry hatayein" asks once more and says that the entry stays visible, struck through.
- In the scripted mock mode the controls work against the mock ledger. Offline, and on the synthetic list, they are
  disabled with a short reason. After a change every khata query is refreshed.
- Every visible text has a Hinglish and an English form. No pressure or threat language.

### 3.7 Copy of every shop's ledger in Supabase (v1.9)

Code: `server/app/cloud_sync.py`, tables: `server/app/supabase_schema.sql`. On when `SUPABASE_URL` and
`SUPABASE_SECRET_KEY` (or the legacy `SUPABASE_SERVICE_ROLE_KEY`) are set.
- Once at start-up and then every `CLOUD_SYNC_INTERVAL_S` (default 300, at least 30) the server pushes each shop's
  SQLite ledger to the Supabase project through its REST API, in a worker thread, through a read-only connection
  per ledger. A turn is never held up and the app's write lock is never taken.
- Shops: `default` (the ledger at `LEDGER_DB`) and every signed-in account's ledger under `data/users/<id>/`, the
  folder name being the account's hashed id. No email address is sent.
- Tables `khata_customers`, `khata_events`, `khata_utterances`, `khata_consent_log`, `khata_confusions`, each keyed
  by `shop` plus the local key. Rows are copied as stored: `ident` and `body` are the AES-256-GCM blobs in base64
  (same nonce, ciphertext and associated data, so the shop can restore them with its key); amounts, kinds and dates
  are plain. Row level security is on with no policy, so only the secret key reaches them.
- events, utterances and consent_log are append-only and pushed from where the cloud copy ends (largest id; for
  utterances, latest `ts`, sending the rows at that time again). customers and confusions change in place and are
  upserted in full. The reminder outbox is not copied. The copy is one-way: nothing is read back.
- Missing tables: with `SUPABASE_ACCESS_TOKEN` (a personal access token) the server runs supabase_schema.sql
  through the Supabase Management API; without it the log says to run that file once in the SQL editor.
- Failures are logged with the HTTP status and error code and retried at the next round. The key, the token and
  row contents are never logged. `python -m app.cloud_sync` (from `server/`) pushes once by hand.
- The secret key goes in the `apikey` header only; a legacy `eyJ...` key also as `Authorization: Bearer`.

### 3.8 Reminder SMS through Twilio (v1.10)

Code: `server/app/sms.py` (Twilio Messages API over httpx, no Twilio library) and `server/app/notify_worker.py` (the
Kafka consumer). On when `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN` and `TWILIO_MESSAGING_SERVICE_SID` (or
`TWILIO_FROM`) are set and Kafka is on.
- The "Send reminder" button calls `POST /api/customers/{id}/remind`: it queues a reminder for that one customer
  only (opted in, owing, inside 09:00 to 20:00) and publishes `reminder_queued`. Answer `{"queued": id|null,
  "quiet_hours": bool, "sms": bool}`; 404 `unknown_customer`. `POST /api/reminders/queue` (every opted-in customer
  at once) is not used by the page. A reminder asked for by voice publishes the same event after its yes.
- The consumer receives ids only. It opens that shop's ledger on the same machine and sends nothing unless: it is
  09:00 to 20:00 shop time; the outbox row is still pending (not sent before, not removed by an opt-out); the
  customer is still opted in, still owes and has a phone number; no reminder was sent to them in the last 24 hours;
  and the number (E.164, `+91` for a 10-digit mobile) is in `TWILIO_ALLOWED_TO` (`*` = any number, empty = none).
- The text is the reminder message of 5.1 (`Namaste {name} ji, aapke khate mein ₹{amount} baaki hain. Suvidha se
  bhej dijiye. Dhanyavaad.`, English when the customer's language is English), from the current balance.
- After Twilio accepts it the row is marked `sent`, so a repeated event sends nothing; a refusal (HTTP status and
  Twilio code in the log) leaves it pending, and the next press sends it.
- Phone numbers, names, message text and the auth token never go into Kafka or the log.
- `REMINDER_ANY_HOUR=1` lifts the 09:00 to 20:00 window (Q06) for queueing, listing and sending, in the server
  and in the consumer. Default off. Opt-in, the allow-list and one SMS per customer per 24 hours still apply.
- SMS is the only channel (v1.11): there is no WhatsApp link. `GET /api/reminders` items carry `"has_phone"`
  (a number is stored) instead of `wa_link`, so the page never receives a customer's full number.

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
- Defaults, confirmed live: `format=transliterate` (whole transcript in Latin letters, numbers as words, so one parser
  path) and `language_code=hi-IN`. Do not use `format=transcribe`: live, it wrote `dedh sau` as 1,500 and `three forty`
  as 3:40. Send one language code: the comma list `hi-IN,en-IN` was closed with code 1008.
- Partial transcripts: the upgrade header `x-partials: true` (absent from the public docs; seen in the `connected`
  config echo and verified live) switches the session to a second vocabulary: `partial_transcript` (`text`,
  `stable_text`, `volatile_text`, `seq`, `utterance_id`) about every 450 ms, `speech_end`, then `final_transcript`
  (the fields of `transcript` plus `prefetched`). The client accepts both vocabularies: `transcript` and
  `final_transcript` are final, `partial_transcript` becomes a `transcript` message with `final: false`, and
  `processing` or `speech_end` means `transcribing`. Env `GNANI_STT_PARTIALS` (default `1`).
- Measured live: the final transcript arrives 210 ms after `commit` with partials on, 270 to 470 ms with them off, and
  1,160 ms when waiting for silence. `processing` is not always sent. Four concurrent sessions were accepted.
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
- Measured live: handshake 280 to 460 ms; on a warm socket the first chunk arrives 130 to 200 ms after the request, as
  base64 JSON chunks of 1.4 to 4 kB with no header. After the documented `complete` the server sends a second `complete`
  (`message` and `request_id`, no `data`), and `start.request_id` names the connection, not the request. So after
  sending a request, discard every message until its `start`.
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
| Several entries | `{n} entry likhi: {name} ke ₹{amt} udhaar, kal ke ₹{amt} jama.` (the customer is named again only when it changes: `2 entry likhi: Ramesh ke ₹340 udhaar, Sunita ke ₹200 jama.`) |
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

### 5.1 Reply additions (v1.2). Each has a Devanagari `speak_text` with amounts in words, and both languages.

| Moment | Hinglish reply_text | English reply_text |
|---|---|---|
| Nothing to amend (D03) | `Pehle koi entry nahi hai.` | `There is no earlier entry.` |
| Nothing to undo (D09) | `Undo karne ke liye kuch nahi hai.` | `There is nothing to undo.` |
| Correction after an undo (D11) | `Woh entry hat chuki hai. Poori entry dobara boliye.` | `That entry was removed. Please say the full entry again.` |
| Rejected `future` (G01, G02, C03) | `Yeh baad ki baat hai, abhi kuch nahi likha.` | `That has not happened yet, so nothing was saved.` |
| Rejected `negated` (B09, B10) | `Theek hai, kuch nahi likha.` | `Okay, nothing was saved.` |
| Rejected `out_of_scope` (I01 to I03, B14) | `Yeh udhaar entry nahi hai, isliye nahi likha.` | `That is not a credit entry, so nothing was saved.` |
| Rejected `too_large` (A22) | `Itni badi rakam nahi likh sakta.` | `That amount is too large to save.` |
| Rejected `no_question` (G06) | `Kis baare mein?` | `About what?` |
| New customer (E09) | `{name} naya grahak hai. Khata banaun?` / `{name} naya grahak hai, ya {close}?` | `{name} is a new customer. Open an account?` / `Is {name} a new customer, or {close}?` |
| Name alone (E12) | `{name} ka kya likhun?` | `What should I note for {name}?` |
| Quantity without a price (H03) | `Kitne ka?` | `For how many rupees?` |
| Confirm `computed`, `hearsay`, `unsure` | `{name} ke ₹{amt} udhaar likhun?` / `{name} se ₹{amt} jama likhun?` (with `kal ke` / `parso ke`) | `Add ₹{amt} credit for {name}?` / `Record ₹{amt} received from {name}?` |
| Confirm `settle` (H04, H07) | `{name} ke ₹{bal} baaki hain. Poore jama likhun?` | `{name} owes ₹{bal}. Record all of it as received?` |
| Confirm `half` (H05) | `Aadha yaani ₹{amt}. {name} se jama likhun?` | `Half is ₹{amt}. Record it as received from {name}?` |
| Confirm `writeoff` (H06) | `{name} ke ₹{bal} baaki hain. Poore maaf karun?` | `{name} owes ₹{bal}. Write all of it off?` |
| Confirm `roundoff` (H09) | `{name} ke ₹{bal} baaki hain. ₹{amt} chhod doon?` | `{name} owes ₹{bal}. Drop ₹{amt}?` |
| Confirm `overpayment` (H08) | `{name} ke sirf ₹{bal} baaki hain. ₹{amt} hi likhun?` / with nothing due: `{name} ka kuch baaki nahi. ₹{amt} advance likhun?` | `{name} owes only ₹{bal}. Record ₹{amt} anyway?` / `{name} owes nothing. Record ₹{amt} as an advance?` |
| Confirm `review` (1.16) | `2 entry likhun: {name} ke ₹{a} udhaar, {name2} se ₹{b} jama?` | `Save 2 entries: ₹{a} credit for {name}, ₹{b} received from {name2}?` |
| Confirm `amend` (1.16) | `{name} ki ₹{old} {udhaar\|jama} entry ₹{new} kar doon?` | `Change {name}'s ₹{old} {credit\|payment} entry to ₹{new}?` |
| Confirm `writeoff` with an amount (1.16) | `{name} ke ₹{amt} maaf karun?` | `Write off ₹{amt} for {name}?` |
| Missing amount, several entries pending (1.17) | `{name} ke kitne rupaye?` | `How many rupees for {name}?` |
| Plausibility, several entries pending (1.17) | `{name} ke ₹{amt}, pakka?` | `₹{amt} for {name}, are you sure?` |
| Missing amount of a write-off (1.18) | `{name} ke kitne rupaye maaf karun?` | `How many rupees to write off for {name}?` |
| Replace check (1.18) | `Pichli entry hata kar {name} ke ₹{amt} {udhaar\|jama} likhoon?` | `Replace the last entry with ₹{amt} {credit\|payment} for {name}?` |
| Write-off above the balance (1.18) | `{name} ke sirf ₹{bal} baaki hain. ₹{amt} maaf karun?` | `{name} owes only ₹{bal}. Write off ₹{amt}?` |
| Same name, three customers (1.18) | `Kaunse {name}: {tag1}, {tag2} ya {tag3}?`; a customer with no tag is `bina tag wale` | `Which {name}: {tag1}, {tag2} or {tag3}?`; `the one with no tag` |
| Confirm `duplicate` (K01) | `Yeh entry abhi likhi hai. Ek aur likhun?` | `I just saved this entry. Save another one?` |
| Write-off saved | `{name} ke ₹{amt} maaf kiye.` | `Wrote off ₹{amt} for {name}.` |
| Silence (M02) | `Kuch sunai nahi diya. Dobara boliye.` | `I could not hear anything. Please say it again.` |
| Too long (M07) | `Bahut lamba ho gaya. Chhote vaakya mein boliye.` | `That was too long. Please use a short sentence.` |
| Private mode | `Jawab screen par hai.` | `The answer is on the screen.` |
| Balance, no entries (E14) | `{name} ka koi hisaab nahi hai.` | `{name} has no entries.` |
| Balance, exactly zero (J10) | `{name} ka hisaab barabar hai.` | `{name}'s account is settled.` |
| Period totals (J06) | `Is hafte ₹{c} udhaar gaya, ₹{p} jama hue.` (`Pichle hafte`, `Is mahine`, `Pichle mahine`) | `This week: ₹{c} credit, ₹{p} received.` |
| Outstanding total (J09) | `Kul baaki ₹{amt} hai, {n} grahakon par.` | `Total outstanding is ₹{amt}, from {n} customers.` |
| Due since (J07) | `{name} ka {d} {month} se baaki hai.` | `{name} has owed since {d} {month}.` |
| Reminder (Q08) | `{name} ka reminder taiyaar hai, screen par dekhiye.` / `{name} ne reminder ke liye haan nahi kaha hai.` / `{name} ka kuch baaki nahi, reminder nahi banaya.` / `{name} ke ₹{bal} baaki hain, ₹{said} nahi. ₹{bal} ka reminder banaun?` / `Reminder subah 9 se raat 8 baje ke beech hi bante hain.` | the same five in English |

The rejected reply `Maaf kijiye, samajh nahi aaya. Dobara boliye.` stays for `not_ledger` and `invalid_number`.
Every reply keeps to about twelve words (N03); a test counts them.

## 6. Latency budget (judged metric: end of speech → first agent audio, target under 2000 ms)

| Hop | Target |
|---|---|
| Button release → `end` sent | under 50 ms |
| `end` → final transcript (`commit` + Gnani `latency`) | 210 to 470 ms measured live |
| Parse + guard | under 10 ms |
| Database commit + query | under 20 ms |
| TTS request → first audio chunk | 130 to 200 ms measured live on a warm socket |
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
`GNANI_STT_LANGUAGE` (`hi-IN`), `GNANI_STT_PARTIALS` (`1`), `GNANI_STT_MIN_SILENCE_MS` (unset = Gnani default), `GNANI_TTS_VOICE` (`Shivani`),
`GNANI_TTS_LANGUAGE` (`hi-IN`), `GNANI_TTS_SAMPLE_RATE` (`24000`), `LEDGER_KEY`, `LEDGER_DB` (`data/khata.db`),
`SHOP_TZ` (`Asia/Kolkata`), `CONFIRM_ABOVE` (`50000`), `CONFIRM_NEW_CUSTOMER` (`1`), `STRICT_SAVE` (`1`), `MAX_AMOUNT` (`9999999`),
`TTS_PREWARM` (`1`), `ADMIN_TOKEN`, `ACCESS_CODE`, `HOST`, `PORT` (`8000`).
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
frontend/           web       React app (Vite, TypeScript, Tailwind); its build output is what the server serves
server/tests/edge/  qa        one automated test per case of docs/EDGE_CASES.md
docs/CONTRACT.md, docs/EDGE_CASES.md, server/pyproject.toml   tech lead
```
- Run every Python command from `server/` with `../.venv/Scripts/python` (tests: `../.venv/Scripts/python -m pytest`).
- Each module has one owner. A change to another module goes through its owner, with a minimal reproducing case.
- Commits are made at phase boundaries by the tech lead.
- No new dependency without the tech lead: compiled wheels can be blocked on the dev machine.
- Automated tests never call the real Gnani API. They use the mock.
