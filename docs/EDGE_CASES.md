# Edge-case list

The cases KhataVaani is tested against, section by section. Each case has one automated test in
`server/tests/edge/` (the test name carries the case id), or a scripted check for speech, sync and UI cases.
The rules that implement them are in docs/CONTRACT.md (sections 1.14, 2.1, 3.3 and 5.1).
`scripts/edge_report.py` runs the tests and writes the pass/fail table to docs/EDGE_REPORT.md.

Actions used in the "Expected" column
- SAVE: write the ledger event, then speak a short readback.
- ASK: do not save; speak one short question and wait.
- REJECT: do not save; say politely that it is not supported or not understood.
- QUERY: answer from SQL with a fixed template; no ledger write.
- IGNORE: do nothing.
- CONFIRM: needs a spoken yes or no before saving.

Rules every case obeys
1. The parser produces a correct entry or asks. It never saves a wrong entry silently.
2. Amounts, direction and dates come from deterministic code, never from a language model.
3. Money is stored as integers.
4. The ledger is append-only. Undo and corrections add events; nothing is edited or deleted.
5. Dates and times use IST (Asia/Kolkata).
6. Only the final transcript is parsed, never a partial one.
7. Every utterance has a unique id, so a retry never creates a duplicate.
8. Readbacks stay short and do not announce a running balance unless asked.
9. The Gnani API key stays on the server in `.env`. Only synthetic data is used.
10. Spoken amounts are read back as words.

## A. Number parsing
| ID | Input | Expected | Handling |
|---|---|---|---|
| A01 | `teen sau chaalis` | 340 | |
| A02 | `three hundred forty`, `three forty` | 340 | |
| A03 | `dedh sau` | 150 | |
| A04 | `dhai sau` | 250 | |
| A05 | `sawa sau` | 125 | |
| A06 | `saade teen sau` | 350 | |
| A07 | `paanch sau paanch` | 505 | |
| A08 | `do hazaar paanch sau` | 2500 | |
| A09 | `unchaas`, `unsath`, `unnasi` | 49, 59, 79 | `unnasi` (उन्यासी) is 79; 89 is `nawasi`. The first draft of this list said 89 |
| A10 | `pachaas`, `saath`, `pachhattar` | 50, 60, 75 | |
| A11 | `teen chaar sau` | ASK `₹340 ya ₹400?` | |
| A12 | `200 ya 300` | ASK with the two candidates | |
| A13 | `₹2,000`, `2,000`, `2k`, `2.5k` | 2000, 2000, 2000, 2500 | |
| A14 | `5,00,000` | CONFIRM | Above the plausibility limit |
| A15 | `zero`, `0`, `minus 50` | REJECT | |
| A16 | stray `ek` (`ek customer ka`) | not read as amount 1 | |
| A17 | `Ramesh Ramesh ka 340 340 udhaar` | 340, not 340340 | |
| A18 | digits one by one: `four three zero` | 430 | |
| A19 | `fifteen` vs `fifty`, `twelve` vs `twenty` | ASK when the transcript is ambiguous | Asked when a second transcript or the shop's correction history disagrees. Gnani returns one transcript, so otherwise the readback and `nahi, 50` are the guard |
| A20 | Devanagari digits `१२३` and Eastern Arabic digits | read as ASCII digits | |
| A21 | amount 10 times the customer's usual | CONFIRM | |
| A22 | very large amount | CONFIRM or REJECT | Above ₹50,000 is confirmed; above ₹99,99,999 is rejected |
| A23 | `rs`, `rs.`, `rupaye`, `rupay`, `paise`, `₹` | all read as currency words | The ledger keeps whole rupees |
| A24 | `teen` as 3 or as a count | context decides | `teen customer aaye the` is not an entry |

## B. Direction (credit or payment)
| ID | Input | Expected | Handling |
|---|---|---|---|
| B01 | `Sunita ko 500 diya` | SAVE credit 500 | The shop gave |
| B02 | `Sunita ne 500 diya` | SAVE payment 500 | The customer gave |
| B03 | `Ramesh ka 340 udhaar` | credit | |
| B04 | `Ramesh ne 200 payment diya`, `200 mila` | payment | |
| B05 | `Sunita paid 500`, `received 500 from Sunita` | payment | |
| B06 | `gave Sunita 500 on credit`, `Sunita owes 500` | credit | |
| B07 | `500 diya` (no name) | ASK who | |
| B08 | `Sunita ka 500` (no direction) | ASK | |
| B09 | `Sunita ne nahi diya` | REJECT | Negation blocks an entry |
| B10 | `Sunita ko 500 nahi dena hai` | no entry | |
| B11 | `udhaar wapas`, `udhaar chuka diya` | payment | |
| B12 | `ne` and `ko` dropped or swapped | ASK | |
| B13 | `500 Sunita ko diya` | credit | |
| B14 | `Ramesh ne Sunita ko 100 diya` | REJECT | Two customers in one clause |
| B15 | `advance 500 diya` | SAVE as advance | A payment; the balance may go below zero |
| B16 | `wapas kiya 100` | ASK | Direction unclear |

## C. Dates and time
| ID | Input | Expected | Handling |
|---|---|---|---|
| C01 | `kal 200 diya tha` | payment dated yesterday | |
| C02 | `parso 100 udhaar` | credit dated two days ago | |
| C03 | `kal dunga`, `kal dega` | no save | A promise |
| C04 | `pichle hafte`, `Monday ko`, `1 tarikh ko` | ASK | Asks which day |
| C05 | server clock in UTC, shop in IST, after 6:30 PM | correct IST date | |
| C06 | command at 00:05 | the shop-day rule applies | A shop day is the calendar day in IST |
| C07 | `parso` on the 1st of a month or year | correct date | |
| C08 | past-dated entry on screen | ordered by event date; audit by creation time | `GET /api/ledger?order=date` or `created` |
| C09 | phone clock wrong | server time decides; device time kept separately | `device_ts` on the utterance record |

## D. Compound sentences, corrections and undo
| ID | Input | Expected | Handling |
|---|---|---|---|
| D01 | `Ramesh ka 340 udhaar, kal 200 diya tha` | SAVE two events: +340 today, −200 yesterday | |
| D02 | `nahi, 430` after an entry | amend the last active entry to 430 | |
| D03 | `nahi, 430` with no earlier entry | REJECT `Pehle koi entry nahi hai.` | |
| D04 | `nahi, Ramesh ka nahi, Sunita ka 200` | corrects the customer, not the amount | |
| D05 | `nahi, 430` after a sentence that made two entries | ASK which entry | |
| D06 | `aur 200` after an entry | same customer and direction | |
| D07 | `aur 200` after a query | ASK direction | |
| D08 | `undo karo` | adds a reversal event | |
| D09 | `undo karo` with nothing to undo | REJECT `Undo karne ke liye kuch nahi hai.` | |
| D10 | `undo karo` twice | the second undo reverses the previous active entry; nothing is reversed twice | |
| D11 | correction after the entry was undone | blocked | Corrections reach active entries only |
| D12 | `340... nahi 430... ruko` | `ruko` stops it; nothing saved | |
| D13 | `cancel`, `chhodo`, `rehne do` | clears the open question | |
| D14 | `Ramesh ka 340 udhaar aur Sunita ka 200 payment` | SAVE two entries | Split on `aur` only when each side has an amount |
| D15 | fillers `uh`, `matlab`, `wo na`, `bhai` | ignored | |
| D16 | `Ramesh ka 340, nahi 430` | final amount 430 | |

## E. Customers and names
| ID | Case | Expected | Handling |
|---|---|---|---|
| E01 | two customers named Ramesh | ASK `Kaunse Ramesh?` | |
| E02 | answer `chai wale`, `pehla wala`, or silence | resolved by tag or order; silence drops the question | The question expires after 60 seconds |
| E03 | spelling drift: Sunita, Suneeta, Sunitha | same customer | |
| E04 | name not close enough to any customer | ASK | |
| E05 | similar names: Ramesh and Rakesh | ASK when close | |
| E06 | names that are common words (Kiran, Ganga, Raja, Sagar) | the stored customer wins | |
| E07 | names that are number words or particles | not broken up | Roster first (`Das`) |
| E08 | `Sharma ji`, `Ramesh bhaiya`, `Sunita aunty` | honorific dropped before matching | |
| E09 | name not in the ledger | ASK before creating | `CONFIRM_NEW_CUSTOMER`, on by default |
| E10 | alias `Shivu` | resolves to the customer | |
| E11 | tag `Ramesh chai wale` | resolves by tag | |
| E12 | name alone: `Ramesh` | ASK `Ramesh ka kya likhun?` | |
| E13 | merge `Ramesh` and `Ramesh bhai` | a merge event, not an edit | Not built. Honorific stripping, phonetic matching and the new-customer question prevent the duplicate instead |
| E14 | customer with no entries | `Koi hisaab nahi hai` | |
| E15 | 500 or more customers | exact match first, fuzzy on a small set | Timed in a test |
| E16 | two shops on one device | data scoped by shop | Not built. One database file is one shop |

## F. Glued tokens and normalisation
| ID | Input | Expected | Handling |
|---|---|---|---|
| F01 | `sunita kofivehundred diya` | `sunita ko five hundred diya`, credit 500 | |
| F02 | `ko500`, `nefivehundred` | letters and digits split | |
| F03 | a token that cannot be cut completely | left unchanged | |
| F04 | customer `Konda` | not split into `ko` + `nda` | |
| F05 | two possible cuts | ASK | |
| F06 | ALL CAPS or odd casing | lower-cased | |
| F07 | Devanagari or Roman for the same word | both accepted | `उधार`, `udhar`, `udhaar` |
| F08 | `Ramesh, ka 340.` and `3,40` | cleaned before parsing | |

## G. What is not a command
| ID | Input | Expected | Handling |
|---|---|---|---|
| G01 | `Ramesh ko 500 dena hai` | no save | Plan or promise |
| G02 | `Agar Sunita 200 de to...` | no save | Conditional |
| G03 | `Kal Ramesh ne 300 diya tha na?` | QUERY or ASK | Asks before saving |
| G04 | `Ramesh bol raha tha 340 udhaar` | no save | Hearsay: asks before saving |
| G05 | `Ramesh ka toh 10 lakh udhaar hai!` | CONFIRM | Plausibility |
| G06 | `haan` or `nahi` with no open question | ASK `Kis baare mein?` | |
| G07 | an unrelated sentence as the answer to a question | not taken as the answer | Two failed answers drop the question |
| G08 | question left open, then a full new command | the question is dropped; the command runs | |
| G09 | `Ramesh ka 340 kitna hua?` | QUERY | The question word wins |
| G10 | `Aaj kitna udhaar gaya?` | QUERY | |
| G11 | `Ramesh ka total?` | QUERY, never an entry | |

## H. Bills, items and part payments
| ID | Input | Expected | Handling |
|---|---|---|---|
| H01 | `Bill 450 hai, 200 diya, baaki udhaar` | CONFIRM credit 250 | |
| H02 | `Ramesh ka 500 udhaar, 100 discount` | CONFIRM credit 400 | |
| H03 | `2 kilo chawal udhaar` | ASK `Kitne ka?` | A price is never invented |
| H04 | `Sunita ne poora de diya` | CONFIRM payment of the whole balance | |
| H05 | `Aadha de diya` | ASK, or offer half the balance | |
| H06 | `Ramesh ka baaki chhod do`, `maaf kar do` | CONFIRM, then a write-off event | Not a payment |
| H07 | `hisaab barabar` | CONFIRM before settling | |
| H08 | payment larger than the balance | ASK `Sirf 340 baaki hain, 1000 hi?` | |
| H09 | `round off kar do` | adjustment event or ASK | |
| H10 | `340 udhaar, total 800 ho gaya` | 800 is a balance, not an entry | |

## I. Out of scope
| ID | Input | Expected | Handling |
|---|---|---|---|
| I01 | `Wholesaler ko 5000 diya` | REJECT politely | Supplier payments are not customer credit |
| I02 | `Dukaan ka kiraya 8000` | REJECT `Yeh udhaar entry nahi hai` | Expense |
| I03 | `Cash mein 300 becha` | REJECT | Cash sale |

## J. Queries and voice insights
| ID | Input | Expected | Handling |
|---|---|---|---|
| J01 | `Ramesh ka total?` | spoken balance | |
| J02 | `Aaj kitna udhaar gaya?` | today's credit total | |
| J03 | `Aaj ka hisaab batao` | spoken daily summary, under 2 seconds | |
| J04 | `Kis kis ka baaki hai?` | speaks the top three, shows the rest | |
| J05 | `Sabse zyada udhaar kiska hai?` | fixed template | |
| J06 | `Is mahine ka total`, `pichle hafte` | date range with IST boundaries | |
| J07 | `Ramesh ka kab se baaki hai?` | date of the oldest unpaid credit | |
| J08 | customer with 200 entries | one sentence, plus the screen | |
| J09 | `Total udhaar kitna hai` | picks a default and says which | Total outstanding across customers |
| J10 | balance exactly zero | `settled`, not `owes 0` | |

## K. Ledger integrity
| ID | Case | Expected | Handling |
|---|---|---|---|
| K01 | same utterance saved twice (double tap, retry) | rejected by the idempotency key; balance unchanged | `utt_id`; a repeated sentence within 30 s is also asked about |
| K02 | floats in money | never; integers only | |
| K03 | customer "deleted" but has events | archive, never hard-delete | There is no delete; a trigger blocks it |
| K04 | concurrent writes | no `database is locked` | |
| K05 | 10,000 or more events | indexed; queries within the latency target | |
| K06 | past-dated event inserted later | display by event date; audit by creation time | |
| K07 | undo or correction pointing at an unknown event | rejected cleanly | |

## L. Session state
| ID | Case | Expected | Handling |
|---|---|---|---|
| L01 | `200 add kar do` right after `Ramesh ka 340 udhaar` | Ramesh, credit | |
| L02 | `200 add kar do` after 60 seconds or another context | ASK customer and direction | |
| L03 | `200 add kar do` with no recent customer | ASK | |
| L04 | `add kar do`, `likh do`, `daal do`, `chadha do`, `put`, `note` | all action words | |
| L05 | page refreshed mid-conversation | open question cleared; safe state | |
| L06 | `Sunita ka total?` then `aur 200` | ASK direction | |

## M. Speech-to-text behaviour
| ID | Case | Expected | Handling |
|---|---|---|---|
| M01 | empty transcript | no entry; `Samajh nahi aaya, dobara boliye` | |
| M02 | button held, silence | no entry; `Kuch sunai nahi diya` | |
| M03 | recording under about 0.5 s | ignored | |
| M04 | first word clipped (`esh ka 340`) | pre-buffer | The microphone stays open and 300 ms before the press is sent |
| M05 | last digit clipped on early release | 300 ms tail after release | |
| M06 | partial transcripts (34, 340, 3400) | only the final one is parsed | |
| M07 | very long utterance | cut with a message | 30 seconds |
| M08 | WebSocket drops mid-stream | reconnects; no duplicate entry | |
| M09 | speech-to-text timeout | fallback message; text input offered | |
| M10 | two overlapping requests | the second is handled once the first is settled | |
| M11 | nonsense or another language | REJECT politely | |
| M12 | very low confidence | ASK | Gnani returns no confidence score |
| M13 | background speaker says a number | push-to-talk, readback and undo catch it | By design |
| M14 | noise: traffic, cooker, mixer, crowd | measured; amounts correct or ASK | `scripts/replay_audio.py` |
| M15 | whisper, shouting, clipping, far microphone | measured | Needs recordings |
| M16 | accents, older speaker, different voices | measured | Needs recordings |
| M17 | `Ramesh ka three forty udhaar` | 340, credit | |
| M18 | `Sunita ne five hundred diya` | payment 500 | |
| M19 | `paisa`, `paise`, `rupaye`, `rs`, `₹` | all recognised | |

Accuracy figures reported by the replay script: exact amount, direction, customer match, silent wrong saves
(must be 0), correction rate, and the time of each stage.

## N. Text-to-speech and readback
| ID | Case | Expected | Handling |
|---|---|---|---|
| N01 | amounts such as 430, 1,250, 5,00,000 | spoken as words | |
| N02 | customer name mispronounced | per-customer pronunciation spelling | Optional `say` field on the customer |
| N03 | long replies | about ten words | Counted in a test |
| N04 | text-to-speech fails | text on screen and a short beep | |
| N05 | microphone open while audio plays | muted or echo-cancelled | Push-to-talk; pressing stops the playback |
| N06 | reply language | matches the last utterance | |
| N07 | greeting and fixed phrases | generated ahead and cached | |
| N08 | privacy at a public counter | readback says only what was entered | Balances on request; private mode keeps them on screen |
| N09 | AI disclosure | first turn of every session | |
| N10 | large amounts | second readback as a cross-check | Words in speech, digits on screen |

## O. Offline and sync
| ID | Case | Expected | Handling |
|---|---|---|---|
| O01 | voice without internet | stated plainly | Speech needs a connection; typed sentences queue and send later |
| O02 | same entry queued and sent twice | deduplicated by utterance id | |
| O03 | two phones, one ledger | merged by event id, ordered by time | The server holds the only ledger |
| O04 | undo sent before its entry | queued until the target arrives | The queue keeps order |
| O05 | sync fails halfway | atomic events, safe retry | |
| O06 | storage encryption | stated clearly | Server: AES-256-GCM per field. Browser cache: WebCrypto over IndexedDB |

## P. Security and privacy
| ID | Case | Expected | Handling |
|---|---|---|---|
| P01 | API key in frontend code or git history | never | Server-side only; history scanned before each push |
| P02 | anyone can edit the khata | PIN or login | `ACCESS_CODE` |
| P03 | SQL injection through a name | parameterised queries only | |
| P04 | prompt injection | transcript is data only | There is no language model |
| P05 | names and amounts in logs | synthetic data; no transcripts in logs | |
| P06 | balances asked aloud in public | private mode | |

## Q. Reminders (opt-in)
| ID | Case | Expected | Handling |
|---|---|---|---|
| Q01 | customer has not opted in | never send | |
| Q02 | wrong or unverified phone number | verify through an opt-in confirmation | The number is entered with the customer present; there is no code check |
| Q03 | shared family phone | short, neutral, no item details | |
| Q04 | customer paid in the meantime | balance recomputed before sending | |
| Q05 | customer opts out | honoured at once and logged | |
| Q06 | sending hours | only within set hours | 09:00 to 20:00 IST |
| Q07 | language preference | stored per customer | |
| Q08 | `Send Ramesh a reminder for 850`, real balance 340 | CONFIRM with the real balance | |
| Q09 | tone | polite; no pressure | |
| Q10 | Kafka or WhatsApp sending not built | labelled as such | The app prepares a WhatsApp link; the shopkeeper sends it |

## R. Screen and experience
| ID | Case | Expected | Handling |
|---|---|---|---|
| R01 | microphone permission denied | clear message and text input | |
| R02 | no internet at start | visible `Offline` status | |
| R03 | small screen in sunlight | high contrast, large text | |
| R04 | did the entry save? | clear `Saved` state and a latest-entries list | |
| R05 | accidental press | see M03 | |
| R06 | undo without the microphone | visible Undo button | |
| R07 | tagline "never touch the screen" | reworded to "one press, no typing" | |
| R08 | poor Wi-Fi at the venue | hotspot, recorded backup video, text input | |
| R09 | performance | cached fixed phrases; Gnani limits respected | |
| R10 | tab sent to the background | reconnects on focus | |
| R11 | server restart during a session | reconnects with little state lost | |
| R12 | low battery or memory | state saved after every entry | The ledger is committed before anything is spoken |

## S. Language support
| ID | Case | Expected | Handling |
|---|---|---|---|
| S01 | vocabulary tables | data files, so a language needs no code change | |
| S02 | Kannada or Marathi number words | optional | Not built. The scope is Hindi and English |
| S03 | `Ramesh ji`, `Ramesh sahab` | dropped before matching | |
| S04 | mixed-language sentence | one parser | |

## Order of work when time is short
1. No silent wrong saves. 2. Idempotency key (K01). 3. Context expiry (L02). 4. Integer money (K02).
5. IST dates (C05). 6. Empty and very short recordings (M01 to M03). 7. Bill minus payment (H01).
8. Promises and hypotheticals (G01 to G04). 9. Confirmations for H04, H06, H07, A21. 10. Reminder safety (Q01 to Q05).
