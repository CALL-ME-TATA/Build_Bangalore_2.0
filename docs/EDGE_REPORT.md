# Edge-case report

Written by `scripts/edge_report.py` from the tests in `server/tests/edge/`.

262 cases: 237 pass, 0 fail, 25 manual, 0 without a test (770 tests run).

## A. Number parsing

| ID | Case | Result | First failing assertion |
|---|---|---|---|
| A01 | `teen sau chaalis` | pass |  |
| A02 | `three hundred forty`, `three forty` | pass |  |
| A03 | `dedh sau` | pass |  |
| A04 | `dhai sau` | pass |  |
| A05 | `sawa sau` | pass |  |
| A06 | `saade teen sau` | pass |  |
| A07 | `paanch sau paanch` | pass |  |
| A08 | `do hazaar paanch sau` | pass |  |
| A09 | `unchaas`, `unsath`, `unnasi` | pass |  |
| A10 | `pachaas`, `saath`, `pachhattar` | pass |  |
| A11 | `teen chaar sau` | pass |  |
| A12 | `200 ya 300` | pass |  |
| A13 | `₹2,000`, `2,000`, `2k`, `2.5k` | pass |  |
| A14 | `5,00,000` | pass |  |
| A15 | `zero`, `0`, `minus 50` | pass |  |
| A16 | stray `ek` (`ek customer ka`) | pass |  |
| A17 | `Ramesh Ramesh ka 340 340 udhaar` | pass |  |
| A18 | digits one by one: `four three zero` | pass |  |
| A19 | `fifteen` vs `fifty`, `twelve` vs `twenty` | pass |  |
| A20 | Devanagari digits `१२३` and Eastern Arabic digits | pass |  |
| A21 | amount 10 times the customer's usual | pass |  |
| A22 | very large amount | pass |  |
| A23 | `rs`, `rs.`, `rupaye`, `rupay`, `paise`, `₹` | pass |  |
| A24 | `teen` as 3 or as a count | pass |  |

## B. Direction (credit or payment)

| ID | Case | Result | First failing assertion |
|---|---|---|---|
| B01 | `Sunita ko 500 diya` | pass |  |
| B02 | `Sunita ne 500 diya` | pass |  |
| B03 | `Ramesh ka 340 udhaar` | pass |  |
| B04 | `Ramesh ne 200 payment diya`, `200 mila` | pass |  |
| B05 | `Sunita paid 500`, `received 500 from Sunita` | pass |  |
| B06 | `gave Sunita 500 on credit`, `Sunita owes 500` | pass |  |
| B07 | `500 diya` (no name) | pass |  |
| B08 | `Sunita ka 500` (no direction) | pass |  |
| B09 | `Sunita ne nahi diya` | pass |  |
| B10 | `Sunita ko 500 nahi dena hai` | pass |  |
| B11 | `udhaar wapas`, `udhaar chuka diya` | pass |  |
| B12 | `ne` and `ko` dropped or swapped | pass |  |
| B13 | `500 Sunita ko diya` | pass |  |
| B14 | `Ramesh ne Sunita ko 100 diya` | pass |  |
| B15 | `advance 500 diya` | pass |  |
| B16 | `wapas kiya 100` | pass |  |

## C. Dates and time

| ID | Case | Result | First failing assertion |
|---|---|---|---|
| C01 | `kal 200 diya tha` | pass |  |
| C02 | `parso 100 udhaar` | pass |  |
| C03 | `kal dunga`, `kal dega` | pass |  |
| C04 | `pichle hafte`, `Monday ko`, `1 tarikh ko` | pass |  |
| C05 | server clock in UTC, shop in IST, after 6:30 PM | pass |  |
| C06 | command at 00:05 | pass |  |
| C07 | `parso` on the 1st of a month or year | pass |  |
| C08 | past-dated entry on screen | pass |  |
| C09 | phone clock wrong | pass |  |

## D. Compound sentences, corrections and undo

| ID | Case | Result | First failing assertion |
|---|---|---|---|
| D01 | `Ramesh ka 340 udhaar, kal 200 diya tha` | pass |  |
| D02 | `nahi, 430` after an entry | pass |  |
| D03 | `nahi, 430` with no earlier entry | pass |  |
| D04 | `nahi, Ramesh ka nahi, Sunita ka 200` | pass |  |
| D05 | `nahi, 430` after a sentence that made two entries | pass |  |
| D06 | `aur 200` after an entry | pass |  |
| D07 | `aur 200` after a query | pass |  |
| D08 | `undo karo` | pass |  |
| D09 | `undo karo` with nothing to undo | pass |  |
| D10 | `undo karo` twice | pass |  |
| D11 | correction after the entry was undone | pass |  |
| D12 | `340... nahi 430... ruko` | pass |  |
| D13 | `cancel`, `chhodo`, `rehne do` | pass |  |
| D14 | `Ramesh ka 340 udhaar aur Sunita ka 200 payment` | pass |  |
| D15 | fillers `uh`, `matlab`, `wo na`, `bhai` | pass |  |
| D16 | `Ramesh ka 340, nahi 430` | pass |  |

## E. Customers and names

| ID | Case | Result | First failing assertion |
|---|---|---|---|
| E01 | two customers named Ramesh | pass |  |
| E02 | answer `chai wale`, `pehla wala`, or silence | pass |  |
| E03 | spelling drift: Sunita, Suneeta, Sunitha | pass |  |
| E04 | name not close enough to any customer | pass |  |
| E05 | similar names: Ramesh and Rakesh | pass |  |
| E06 | names that are common words (Kiran, Ganga, Raja, Sagar) | pass |  |
| E07 | names that are number words or particles | pass |  |
| E08 | `Sharma ji`, `Ramesh bhaiya`, `Sunita aunty` | pass |  |
| E09 | name not in the ledger | pass |  |
| E10 | alias `Shivu` | pass |  |
| E11 | tag `Ramesh chai wale` | pass |  |
| E12 | name alone: `Ramesh` | pass |  |
| E13 | merge `Ramesh` and `Ramesh bhai` | manual | merge is not built; honorific stripping and the new-customer question (E03, E08, E09) prevent the duplicate |
| E14 | customer with no entries | pass |  |
| E15 | 500 or more customers | pass |  |
| E16 | two shops on one device | manual | not built: one database file is one shop |

## F. Glued tokens and normalisation

| ID | Case | Result | First failing assertion |
|---|---|---|---|
| F01 | `sunita kofivehundred diya` | pass |  |
| F02 | `ko500`, `nefivehundred` | pass |  |
| F03 | a token that cannot be cut completely | pass |  |
| F04 | customer `Konda` | pass |  |
| F05 | two possible cuts | pass |  |
| F06 | ALL CAPS or odd casing | pass |  |
| F07 | Devanagari or Roman for the same word | pass |  |
| F08 | `Ramesh, ka 340.` and `3,40` | pass |  |

## G. What is not a command

| ID | Case | Result | First failing assertion |
|---|---|---|---|
| G01 | `Ramesh ko 500 dena hai` | pass |  |
| G02 | `Agar Sunita 200 de to...` | pass |  |
| G03 | `Kal Ramesh ne 300 diya tha na?` | pass |  |
| G04 | `Ramesh bol raha tha 340 udhaar` | pass |  |
| G05 | `Ramesh ka toh 10 lakh udhaar hai!` | pass |  |
| G06 | `haan` or `nahi` with no open question | pass |  |
| G07 | an unrelated sentence as the answer to a question | pass |  |
| G08 | question left open, then a full new command | pass |  |
| G09 | `Ramesh ka 340 kitna hua?` | pass |  |
| G10 | `Aaj kitna udhaar gaya?` | pass |  |
| G11 | `Ramesh ka total?` | pass |  |

## H. Bills, items and part payments

| ID | Case | Result | First failing assertion |
|---|---|---|---|
| H01 | `Bill 450 hai, 200 diya, baaki udhaar` | pass |  |
| H02 | `Ramesh ka 500 udhaar, 100 discount` | pass |  |
| H03 | `2 kilo chawal udhaar` | pass |  |
| H04 | `Sunita ne poora de diya` | pass |  |
| H05 | `Aadha de diya` | pass |  |
| H06 | `Ramesh ka baaki chhod do`, `maaf kar do` | pass |  |
| H07 | `hisaab barabar` | pass |  |
| H08 | payment larger than the balance | pass |  |
| H09 | `round off kar do` | pass |  |
| H10 | `340 udhaar, total 800 ho gaya` | pass |  |

## I. Out of scope

| ID | Case | Result | First failing assertion |
|---|---|---|---|
| I01 | `Wholesaler ko 5000 diya` | pass |  |
| I02 | `Dukaan ka kiraya 8000` | pass |  |
| I03 | `Cash mein 300 becha` | pass |  |

## J. Queries and voice insights

| ID | Case | Result | First failing assertion |
|---|---|---|---|
| J01 | `Ramesh ka total?` | pass |  |
| J02 | `Aaj kitna udhaar gaya?` | pass |  |
| J03 | `Aaj ka hisaab batao` | pass |  |
| J04 | `Kis kis ka baaki hai?` | pass |  |
| J05 | `Sabse zyada udhaar kiska hai?` | pass |  |
| J06 | `Is mahine ka total`, `pichle hafte` | pass |  |
| J07 | `Ramesh ka kab se baaki hai?` | pass |  |
| J08 | customer with 200 entries | pass |  |
| J09 | `Total udhaar kitna hai` | pass |  |
| J10 | balance exactly zero | pass |  |

## K. Ledger integrity

| ID | Case | Result | First failing assertion |
|---|---|---|---|
| K01 | same utterance saved twice (double tap, retry) | pass |  |
| K02 | floats in money | pass |  |
| K03 | customer "deleted" but has events | pass |  |
| K04 | concurrent writes | pass |  |
| K05 | 10,000 or more events | pass |  |
| K06 | past-dated event inserted later | pass |  |
| K07 | undo or correction pointing at an unknown event | pass |  |

## L. Session state

| ID | Case | Result | First failing assertion |
|---|---|---|---|
| L01 | `200 add kar do` right after `Ramesh ka 340 udhaar` | pass |  |
| L02 | `200 add kar do` after 60 seconds or another context | pass |  |
| L03 | `200 add kar do` with no recent customer | pass |  |
| L04 | `add kar do`, `likh do`, `daal do`, `chadha do`, `put`, `... | pass |  |
| L05 | page refreshed mid-conversation | pass |  |
| L06 | `Sunita ka total?` then `aur 200` | pass |  |

## M. Speech-to-text behaviour

| ID | Case | Result | First failing assertion |
|---|---|---|---|
| M01 | empty transcript | pass |  |
| M02 | button held, silence | pass |  |
| M03 | recording under about 0.5 s | pass |  |
| M04 | first word clipped (`esh ka 340`) | manual | browser pre-buffer (300 ms before the press); needs a microphone |
| M05 | last digit clipped on early release | manual | browser 300 ms tail after release; needs a microphone |
| M06 | partial transcripts (34, 340, 3400) | pass |  |
| M07 | very long utterance | pass |  |
| M08 | WebSocket drops mid-stream | pass |  |
| M09 | speech-to-text timeout | pass |  |
| M10 | two overlapping requests | pass |  |
| M11 | nonsense or another language | pass |  |
| M12 | very low confidence | manual | Gnani returns no confidence score, so there is nothing to test |
| M13 | background speaker says a number | manual | a background speaker is a recording case; push-to-talk, readback and undo are the guard (D08, N08) |
| M14 | noise: traffic, cooker, mixer, crowd | manual | needs recordings: run scripts/replay_audio.py with a noisy manifest |
| M15 | whisper, shouting, clipping, far microphone | manual | needs recordings (whisper, shouting, clipping, far microphone) |
| M16 | accents, older speaker, different voices | manual | needs recordings of other accents and voices |
| M17 | `Ramesh ka three forty udhaar` | pass |  |
| M18 | `Sunita ne five hundred diya` | pass |  |
| M19 | `paisa`, `paise`, `rupaye`, `rs`, `₹` | pass |  |

## N. Text-to-speech and readback

| ID | Case | Result | First failing assertion |
|---|---|---|---|
| N01 | amounts such as 430, 1,250, 5,00,000 | pass |  |
| N02 | customer name mispronounced | manual | the optional per-customer `say` field is not in the contract; check by ear |
| N03 | long replies | pass |  |
| N04 | text-to-speech fails | pass |  |
| N05 | microphone open while audio plays | manual | browser behaviour: pressing the button stops playback and mutes the microphone |
| N06 | reply language | pass |  |
| N07 | greeting and fixed phrases | pass |  |
| N08 | privacy at a public counter | pass |  |
| N09 | AI disclosure | pass |  |
| N10 | large amounts | pass |  |

## O. Offline and sync

| ID | Case | Result | First failing assertion |
|---|---|---|---|
| O01 | voice without internet | manual | browser behaviour: the offline message and the typed-sentence queue |
| O02 | same entry queued and sent twice | pass |  |
| O03 | two phones, one ledger | pass |  |
| O04 | undo sent before its entry | manual | browser queue order; the server only sees the entries in the order they arrive |
| O05 | sync fails halfway | pass |  |
| O06 | storage encryption | pass |  |

## P. Security and privacy

| ID | Case | Result | First failing assertion |
|---|---|---|---|
| P01 | API key in frontend code or git history | pass |  |
| P02 | anyone can edit the khata | pass |  |
| P03 | SQL injection through a name | pass |  |
| P04 | prompt injection | pass |  |
| P05 | names and amounts in logs | pass |  |
| P06 | balances asked aloud in public | pass |  |

## Q. Reminders (opt-in)

| ID | Case | Result | First failing assertion |
|---|---|---|---|
| Q01 | customer has not opted in | pass |  |
| Q02 | wrong or unverified phone number | manual | an opt-in confirmation done with the customer present; there is no code check to test |
| Q03 | shared family phone | pass |  |
| Q04 | customer paid in the meantime | pass |  |
| Q05 | customer opts out | pass |  |
| Q06 | sending hours | pass |  |
| Q07 | language preference | pass |  |
| Q08 | `Send Ramesh a reminder for 850`, real balance 340 | pass |  |
| Q09 | tone | pass |  |
| Q10 | Kafka or WhatsApp sending not built | pass |  |

## R. Screen and experience

| ID | Case | Result | First failing assertion |
|---|---|---|---|
| R01 | microphone permission denied | manual | browser: microphone permission denied message |
| R02 | no internet at start | manual | browser: Offline status at start |
| R03 | small screen in sunlight | manual | visual: contrast and text size in sunlight |
| R04 | did the entry save? | pass |  |
| R05 | accidental press | manual | see M03 (recordings under 0.5 s are ignored) |
| R06 | undo without the microphone | manual | UI: visible Undo button |
| R07 | tagline "never touch the screen" | manual | wording of the tagline in the web app |
| R08 | poor Wi-Fi at the venue | manual | venue plan: hotspot, recorded backup video, text input |
| R09 | performance | manual | cached phrases are tested in N07; Gnani limits are checked by hand against the live account |
| R10 | tab sent to the background | manual | browser: reconnect on focus |
| R11 | server restart during a session | manual | server restart during a session; check by hand |
| R12 | low battery or memory | pass |  |

## S. Language support

| ID | Case | Result | First failing assertion |
|---|---|---|---|
| S01 | vocabulary tables | pass |  |
| S02 | Kannada or Marathi number words | manual | not built: Kannada and Marathi number words are optional |
| S03 | `Ramesh ji`, `Ramesh sahab` | pass |  |
| S04 | mixed-language sentence | pass |  |

## X. Sentences nobody listed

| ID | Case | Result | First failing assertion |
|---|---|---|---|
| X01 | unknown word: ask first, yes saves | pass |  |
| X02 | unknown word: no saves nothing | pass |  |
| X03 | flag off: the same sentences save directly | pass |  |
| X04 | demo script sentences do not ask | pass |  |
| X05 | trailing unknown word never saves silently | pass |  |
| X06 | stored names and tags are known words | pass |  |
| X07 | correction with an unknown word asks | pass |  |
| X08 | queries and undo are not gated | pass |  |
| X09 | new-customer question and unknown word | pass |  |
| X10 | parser names the unknown words | pass |  |

## Y. Review findings

| ID | Case | Result | First failing assertion |
|---|---|---|---|
| Y01 | yes plus an undo word is no | pass |  |
| Y02 | delete request naming the entry never appends | pass |  |
| Y03 | negated and two-name answers | pass |  |
| Y04 | two amounts in an answer ask again | pass |  |
| Y05 | correction after an expired or dropped question | pass |  |
| Y06 | carry-over only by explicit forms | pass |  |
| Y07 | goods counts are not amounts | pass |  |
| Y08 | saath is not 60 | pass |  |
| Y09 | questions, negations and guesses | pass |  |
| Y10 | English negation is not a correction | pass |  |
| Y11 | strict mode survives another question | pass |  |
| Y12 | direction in English and goods | pass |  |
| Y13 | write-off undo and correction | pass |  |
| Y14 | amount modifiers | pass |  |
| Y15 | time words | pass |  |
| Y16 | N saal/hafte/mahine pehle | pass |  |
| Y17 | no-op correction | pass |  |
| Y18 | stative sentences | pass |  |
| Y19 | Kochar is a name | pass |  |
| Y20 | private mode confirm questions | pass |  |
| Y21 | reused utt_id | pass |  |

## Z. Second review

| ID | Case | Result | First failing assertion |
|---|---|---|---|
| Z01 | two-entry sentences and questions | pass |  |
| Z02 | stray numbers | pass |  |
| Z03 | usko / usne answers | pass |  |
| Z04 | number-word names | pass |  |
| Z05 | make it N corrections | pass |  |
| Z06 | reductions | pass |  |
| Z07 | purchase plus payment | pass |  |
| Z08 | answers that conflict with the pending kind | pass |  |
| Z09 | change karke | pass |  |
| Z10 | duplicate question takes yes or no | pass |  |
| Z11 | replayed utterance | pass |  |
| Z12 | question survives a silent turn | pass |  |
| Z13 | everyday speech keeps working | pass |  |
| Z14 | natural answers | pass |  |
| Z15 | correction after a non-entry turn | pass |  |
| Z16 | entry plus query | pass |  |
| Z17 | problem-statement sentence and the demo script | pass |  |
| Z18 | overpayment by the second customer | pass |  |
| Z19 | two implausible amounts | pass |  |
| Z20 | both customers overpay | pass |  |
| Z21 | balance instruction stays in its clause | pass |  |
| Z22 | reduction with its own amount | pass |  |
| Z23 | one amount, two names | pass |  |
| Z24 | stray word heard as a name | pass |  |
| Z25 | silent, empty, long turns and expiry in a chain | pass |  |
| Z26 | private mode in a chain | pass |  |
| Z27 | wording with several entries pending | pass |  |
| Z28 | single-entry regression guard | pass |  |

## Manual cases

- E13: merge is not built; honorific stripping and the new-customer question (E03, E08, E09) prevent the duplicate
- E16: not built: one database file is one shop
- M04: browser pre-buffer (300 ms before the press); needs a microphone
- M05: browser 300 ms tail after release; needs a microphone
- M12: Gnani returns no confidence score, so there is nothing to test
- M13: a background speaker is a recording case; push-to-talk, readback and undo are the guard (D08, N08)
- M14: needs recordings: run scripts/replay_audio.py with a noisy manifest
- M15: needs recordings (whisper, shouting, clipping, far microphone)
- M16: needs recordings of other accents and voices
- N02: the optional per-customer `say` field is not in the contract; check by ear
- N05: browser behaviour: pressing the button stops playback and mutes the microphone
- O01: browser behaviour: the offline message and the typed-sentence queue
- O04: browser queue order; the server only sees the entries in the order they arrive
- P02b: PIN entry screen and wording (the access-code check is automated)
- Q02: an opt-in confirmation done with the customer present; there is no code check to test
- R01: browser: microphone permission denied message
- R02: browser: Offline status at start
- R03: visual: contrast and text size in sunlight
- R05: see M03 (recordings under 0.5 s are ignored)
- R06: UI: visible Undo button
- R07: wording of the tagline in the web app
- R08: venue plan: hotspot, recorded backup video, text input
- R09: cached phrases are tested in N07; Gnani limits are checked by hand against the live account
- R10: browser: reconnect on focus
- R11: server restart during a session; check by hand
- S02: not built: Kannada and Marathi number words are optional
