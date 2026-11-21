# Fix log: every failing case and the fix that closed it

KhataVaani's first rule is that a wrong entry is never saved silently. This file lists the sentences that broke that
rule, or got a wrong or confusing reply, since the first build: what the build did then, what it does now, and the
change to the parser (`server/nlu/`) and to the interface specification (`docs/CONTRACT.md`) that fixed it. A new
case is added here when it is found and its row is completed when the fix is in.

How to read it
- **Said** is what was spoken or typed. `→` separates turns. Unless a row says otherwise the ledger holds Ramesh
  (owes ₹540), Sunita (₹500) and Mohan (₹60), and the new-customer question and strict mode are on.
- **Before** is what the build of that time did, taken from the review or test run that found the case.
- **Now** is what the current build does. Every cell in that column was produced by replaying the sentence through
  the real parser and pipeline on a temporary ledger: `python scripts/fix_log_replay.py` prints one line per turn,
  and the ids in the first column are the ids that script uses (`python scripts/fix_log_replay.py 5.B` replays one
  group).
- **Fix** names the rule and the contract section that states it. The tests that pin each round are named under
  the round's heading.

The complete list of edge cases, pass or fail, is in [EDGE_CASES.md](EDGE_CASES.md) and
[EDGE_REPORT.md](EDGE_REPORT.md). This file holds only the cases that needed a fix.

## Open now

- After a sentence is refused while a question is open (round 11), that question is closed, so the entry has to be
  said again. Nothing is saved wrongly.
- `Ramesh ne 500 ka note diya, 200 kaate, 300 wapas kiye` asks "Kiska khata?" although Ramesh was named.
- `his wife paid 200` with no earlier customer asks "Whose account?"; with one it asks to open "Ramesh ki biwi".

## Rounds at a glance

All times are 2026-11-21, IST.

| Round | Time | How the cases were found | Tried | Found | Contract | Commit |
|---|---|---|---|---|---|---|
| 1 | 13:45 | Independent review of the first build | about 330 sentences | 8 wrong saves, 8 other parser faults | 1.12, 3.1 | a1bb442 |
| 2 | 13:55 | First test with real speech | 52 new reference cases, 21 of them word-for-word transcripts | 9 faults | 1.13, 3.2 | a1bb442 |
| 3 | 15:20 | The edge-case list (EDGE_CASES.md), every sentence run through the parser | about 200 listed cases | 25 groups of faults | 1.14, 2.1, 3.3, 5.1 | a1bb442 |
| 4 | 16:10 | Live runs through the real speech service | the demo script and free speech | 4 faults | 1.9, 1.14 | a1bb442 |
| 5 | 16:50 | Second independent review | about 1,000 sentences and answer sequences | 12 wrong saves, 9 other faults | 1.15 | 1f32d37 |
| 6 | 17:30 | Customer names left by a real voice session | 6 names | 3 faults | 1.15 (names) | c1ebc4a |
| 7 | 18:30 | Third independent review | about 300 sentences and conversations | 11 wrong saves, 13 other faults | 1.16 | 832666b |
| 8 | 19:25 | Live check of the published build | two-entry sentences | 4 faults | 1.17 | f9ee05b |
| 9 | 19:30 | Fourth independent review | about 1,300 turns | 10 wrong-save families, 13 other faults | 1.18, 3.4 | contract 1.7 |
| 10 | 20:40 | Recorded clips with noise, through the live speech service | 240 turns (120 clips, noise handling off and on) | 1 wrong save in an experiment, 1 false alarm in the design | 3.5 | contract 1.7 |
| 11 | 21:35 | Live check of the build that holds rounds 9 and 10 | the demo sentences and two review sentences, with questions open | 2 wrong saves | 1.18 (Answers) | contract 1.7 |

## Round 1: review of the first build

Tests: `server/tests/nlu/test_review_rules.py`. Rules: contract 1.12.

| # | Said | Before | Now | Fix |
|---|---|---|---|---|
| 1.1 | `Sharma ka 100 udhaar` → `Chacha ne 500 diye` (also `Aunty ko 200 diye`, `Abhi ko 200 udhaar diya`) | Saved the entry to Sharma, the previous customer | Asks "Chacha naya grahak hai. Khata banaun?" | The words directly before a particle are the name, even a kinship word, an honorific or a filler. A clause with a particle and no name never takes the previous customer (1.12, Names) |
| 1.2 | `Uska 200 udhaar likh do` | Created a customer "Uska" with ₹200 credit | Asks "Kiska khata?". Right after a Ramesh entry, `Usko 100 udhaar diya` saves ₹100 credit for Ramesh | Pronouns are never names. They point to the last entry's customer inside the carry-over window (1.12) |
| 1.3 | `Ramesh ka teen sau chalis udhar kal do sau diya tha` → `Nahi chaar sau tees` | Changed yesterday's ₹200 payment to ₹430 | Asks "Kaunsi entry: ₹340 udhaar ya ₹200 jama?". `340 nahi 430` corrects the ₹340 entry | The parser receives every entry of the last sentence (`last_events`); a correction names its target or asks (1.12, Context and targets) |
| 1.4 | `Ramesh ne teen sau do din pehle diye the` | Asked "Kitne rupaye?" and then saved the answer dated 302 days back | Saves a ₹300 payment dated two days ago | Only the one number directly before `din` is the day count; more than 60 days asks (1.12, Dates) |
| 1.5 | `Ramesh ka 200 udhaar nahi hai`, `Ramesh ko 200 udhaar nahi dena` | Saved ₹200 credit | Refuses: "Theek hai, kuch nahi likha." | `nahi` with nothing to replace after it is a negation (1.12) |
| 1.6 | `Ramesh ka 340 udhaar` → `Sunita ki entry hata do` (also `Pehli entry hatao`) | Reversed Ramesh's entry | Asks "Sirf pichli entry hata sakta hoon: Ramesh, ₹340 udhaar. Hata doon?". `Ramesh ka order cancel ho gaya` is refused | Undo runs without a question only for a plain undo phrase or a name that matches the last entry (1.12, 1.15) |
| 1.7 | `Ramesh ka 340 udhaar` → `Nahi Sunita ka total batao` | Moved Ramesh's ₹340 to Sunita | Answers "Sunita ke ₹500 baaki hain." | `Nahi` followed by a query runs the query (1.12) |
| 1.7b | `Ramesh ka 340 udhaar` → `Nahi Sunita ne 500 diye` | Replaced Ramesh's credit with a Sunita payment | Asks "Pichli entry hata kar yeh likhoon?" | When customer, amount and kind all change, it asks before it replaces (1.12) |
| 1.8 | `Sunit ko 200 udhaar diya` with Sunita in the ledger; `Rakesh Sharma ...` with Ramesh Sharma | Saved to Sunita; saved to Ramesh Sharma | Asks "Sunit naya grahak hai, ya Sunita?" and "Rakesh Sharma naya grahak hai, ya Ramesh Sharma?" | Names match word by word on the same consonants and the same ending. The 90% fuzzy ratio was removed (1.12, Names) |
| 1.9 | `Ramesh 200` → "Ramesh ne diye, ya Ramesh ko udhaar?" → `Ramesh ne diye` (also `Chai wale` to a same-name question, `Nahi 7500` to "₹75,000, pakka?") | Repeated the question for ever | Saves the ₹200 payment; saves for Suresh chai wale; saves ₹7,500 | An answer may carry extra words. Two answers that do not settle a question cancel it (1.12, Answers) |
| 1.10 | `Ramesh Chopra ko 200 udhaar diya`, `Maine Ramesh ko 200 udhaar diya`, `Ramesh has paid 500`, `Give Ramesh 300 credit` | Asked "Kitne rupaye?" and dropped name and amount | New-customer question for Ramesh Chopra; ₹200 credit for Ramesh; ₹500 payment; ₹300 credit | A run of words before a particle is one name. `maine`, `mujhe`, `humne` are never names (1.12); English forms (1.13) |
| 1.11 | `Kya Ramesh ne 500 diye the?` | Saved a ₹500 payment | Refused | A yes or no question is not an entry (1.12) |
| 1.12 | `Ramesh ke naam likh do sau rupaye` | Saved ₹200 | Asks "₹200 ya ₹100?" | `likh do sau` has two readings (1.12) |
| 1.13 | `Ramesh ko 200 udhaar dena`, `Ramesh ko 200 dene hain` | Saved a credit | Asks the direction; the second is refused as not yet happened | `dena` is ambiguous (1.12); `dena hai`, `dene hain` are future (1.14) |
| 1.14 | `Ramesh ne 500 diye Sunita bhi` | Saved Ramesh's payment only | Asks "Kitne rupaye?" for the second name | A second name with no amount of its own is asked about (1.12) |
| 1.15 | `Kal kitna udhaar gaya?` | Answered with today's total | "Kal ₹300 udhaar gaya." | Queries carry a period (1.12) |
| 1.16 | `200 udhaar` → "Kiska khata?" → `Dobara boliye` | Created a customer "Dobara Boliye" | Asks again; nothing is created | Words that are not a name never become a customer (1.12, Answers) |

Fixed in the server and the page in the same round (contract 3.1 and 7): the spoken AI disclosure could be cut off by an
early press and was then never repeated; a transcript that arrived late leaked into the next turn; a speech
connection that closed mid-sentence saved half a sentence; the page ignored a new session after a restart; cached
reply audio could hold customer names; the read endpoints did not ask for the access code.

## Round 2: first test with real speech

Tests: `server/tests/nlu/test_voice_english.py`, `test_transcript_rules.py`, and the reference cases `u001` to
`u009`, `e001` to `e022`, `v001` to `v021` in `eval/golden.seed.jsonl`. Rules: contract 1.13, 3.2.

| # | Said | Before | Now | Fix |
|---|---|---|---|---|
| 2.1 | `Pay five hundred rupees to Ramesh` | Customer "Pay" | Asks, in English, "Did Ramesh pay, or did Ramesh take credit?" | An imperative verb is never a name; "pay ... to X" does not say who paid (1.13) |
| 2.2 | `Maine char sau pachpan rupaye diye` | Customer "Maine" | Asks "Kiska khata?" | First-person words are never names (1.13); a new turn with no name asks whose account (1.15) |
| 2.3 | `Ramesh ki biwi ka khata?`, heard once as `Ramesh ki bevi. Ka khata?` | Answered with Ramesh's own balance | "Ramesh ki biwi ka khata nahi mila." | A relation names a different person; a full stop inside an utterance is not a boundary (1.13) |
| 2.4 | `Ramesh 1000` → direction question → `ami Hazar` → `Udhaar` | Created a customer "Ami" and saved ₹1,000 to Ami | Repeats the question, then saves ₹1,000 credit for Ramesh | While a question is open, only a complete entry or a query replaces it; anything else is an answer attempt and never creates a customer (1.13) |
| 2.5 | `Ramesh ka 300 udhaar` → `nahi nahi, saadh sau rupaye` | Changed the entry to a customer "Saadh", ₹100 | Asks "Kitne rupaye?" | A word before `sau` or `hazaar` that is not a number is a misheard number, never a name (1.13) |
| 2.6 | `Ramesh ka 300 udhaar` → `nahi nahi, sau rupaye aaye mere paas` | Created a customer "Mere Paas" | Corrects the entry to a ₹100 payment by Ramesh | `mere paas`, `mereko`, `mujhko`, `mera` are never names (1.13) |
| 2.7 | `Ramesh ne paanch sa rupaye diye` | "sa" was not read as "sau" | Saves a ₹500 payment | Spellings seen in live transcripts: `sa`, `wapis`, `khaate`, `bevi` (1.13) |
| 2.8 | `Five hundred in Ramesh's account`, `Give Ramesh five hundred rupees worth of product` | Not understood | Asks the direction; saves ₹500 credit | English sentence forms (1.13) |
| 2.9 | `Sunita paid five hundred rupees` | Replied in Hindi | "Received ₹500 from Sunita." | The result carries the language spoken and the reply uses it (1.13, 3.2) |

## Round 3: the edge-case list

Tests: `server/tests/nlu/test_edge_rules.py` and `server/tests/edge/test_a_*.py` to `test_s_*.py`, one or more per
case id. Rules: contract 1.14, 2.1, 3.3, 5.1. Each "Before" is the real output of the build of 15:20.

| # | Said | Before | Now | Fix |
|---|---|---|---|---|
| 3.1 | `Ramesh ka 2k udhaar`, `Ramesh ka 2.5k udhaar` | Saved ₹2; asked the amount | Saves ₹2,000 and ₹2,500 | `k` is a thousand (A13) |
| 3.2 | `Ramesh ka 5 crore udhaar`, `Ramesh ka 999999999999 udhaar` | Saved ₹5; the reply builder crashed | Refuses: "Itni badi rakam nahi likh sakta." | Crore is a unit; amounts above the limit are refused (A15, A22) |
| 3.3 | `teen customer aaye the`, `Ramesh ko 2 kilo chawal udhaar` | Saved a ₹3 payment for a new customer "Customer"; saved ₹2 credit | Refused; asks "Kitne ka?" | A number before a count noun or a measure word is not an amount (A16, A24, H03) |
| 3.4 | `uh Ramesh ka matlab 340 udhaar` | Customer "Uh Ramesh" | Saves ₹340 credit for Ramesh | Fillers are never part of a name (D15) |
| 3.5 | `Ramesh ka 200 udhaar` → `nahi, Ramesh ka nahi, Sunita ka 200` | Corrected the entry but kept Ramesh | Moves the entry to Sunita | The words after the last `nahi` replace the words before it (D04) |
| 3.6 | Two entries → `undo karo` → `nahi, 430` | Changed an older entry | Refuses: "Woh entry hat chuki hai. Poori entry dobara boliye." | No correction right after an undo (D11) |
| 3.7 | `Ramesh ka 340 udhaar ruko`, `Ramesh bol raha tha 340 udhaar` | Saved both | Cancels; asks "Ramesh ke ₹340 udhaar likhun?" | A stop word cancels (D12, D13); reported speech is confirmed first (G04) |
| 3.8 | `Wholesaler ko 5000 diya`, `Cash mein 300 becha`, `maal ka paisa 3000 diya`, `Dukaan ka kiraya 8000` | Saved for new customers "Wholesaler" and "Becha", or for the previous customer | Refuses: "Yeh udhaar entry nahi hai, isliye nahi likha." | Supplier, expense and cash-sale words are out of scope (I01 to I03) |
| 3.9 | `sunita kofivehundred diya`, `sunitako 500 diya` | A customer "sunita kofivehundred"; a customer "Sunitako" | Saves ₹500 credit for Sunita in both | Glued tokens are cut when the pieces are a stored name, a particle and a number (F01 to F05) |
| 3.10 | `Sunitha ka 50 udhaar`, `Rakes ka 50 udhaar` | New customers | Saves for Sunita; asks "Rakes naya grahak hai, ya Rakesh?" | `th` is `t` in names; a close name is asked about (E03, E05, E09) |
| 3.11 | `Ramesh ka 200 ya 300 udhaar`, `Ramesh ka teen chaar sau udhaar` | Asked the direction; asked "Kitne rupaye?" | Asks "₹200 ya ₹300?" and "₹340 ya ₹400?" | Two readings of an amount are always asked about first (A11, A12) |
| 3.12 | `Ramesh ka minus 50 udhaar` | Asked the direction | Refused | A negative amount is invalid (A22) |
| 3.13 | `Ramesh ka 340 udhaar, total 800 ho gaya` | Asked the direction | Saves ₹340 credit | A stated balance beside an entry is never an entry (H10) |
| 3.14 | `pichle hafte kitna udhaar gaya`, `Is mahine ka total`, `Total udhaar kitna hai` | Today's total; refused; today's credit | Last week's credit; this month's summary; "Kul baaki ₹1,100 hai, 3 grahakon par." | Periods and the outstanding total (J06, J09) |
| 3.15 | `Ramesh ne 1000 diya` when he owes ₹340 | Saved | Asks "Ramesh ke sirf ₹340 baaki hain. ₹1,000 hi likhun?" | Over-payment question (H08) |
| 3.16 | `200 add kar do` 61 s after an entry; `Ramesh ka total` → `aur 200`; `Ramesh ne 100 diye` → `50 add kar do` | Saved; saved a credit; saved a credit | Asks "Kiska khata?"; asks the direction; saves a ₹50 payment | Carry-over lasts 60 s; after a query the customer carries and the kind does not; with no direction word the last entry's kind is used (L01 to L06) |
| 3.17 | `Das ka 100 udhaar` with a customer Das | Asked "Kiska khata?" (Das read as 10) | Saves ₹100 credit for Das | A stored name beats a number word (E07) |
| 3.18 | `Ramesh ne Sunita ko 100 diya` | Asked "Kitne rupaye?" | Refused as out of scope | One customer paying another is not this shop's entry (B14) |
| 3.19 | `Ramesh ka bill 450 hai, 200 diya, baaki udhaar` | "Bill" read as a name | Asks "Ramesh ke ₹250 udhaar likhun?" | Bill minus paid is computed and confirmed (H01) |
| 3.20 | `Send Ramesh a reminder for 850` | "Send Ramesh Reminder" read as a name | Reminder action; refused politely when Ramesh has not opted in | Reminders (Q08) |
| 3.21 | `100 wapas kiya` → "Kiska khata?" → `Ramesh ko 100 wapas kiya` | Repeated "Kiska khata?" | Takes Ramesh and asks the direction | A name inside the answer is used (1.14) |
| 3.22 | `gave Sunita 500 on credit`, `Ramesh ne 30 udhaar chuka diya`, `Ramesh ka udhaar wapas aaya 20`, `Ramesh 100 note kar lo` | Asked the direction, or refused | Credit ₹500; payment ₹30; payment ₹20; credit ₹100 | Direction forms (B06, B11, L04) |
| 3.23 | `Sunita ka 3,40 udhaar`, `Ramesh Ramesh ka 340 340 udhaar`, `Ramesh ka four three zero udhaar` | Asked the amount | Saves ₹340, ₹340 and ₹430 | Commas between digits, repeated words and digit-by-digit numbers (A17, A18) |
| 3.24 | `Ramesh` alone; `haan` alone; `Ramesh ka 340 kitna hua?` | Refused; refused; asked the direction | "Ramesh ka kya likhun?"; "Kis baare mein?"; the balance | Name alone (E12), yes with no question (G06), a question word with an amount is a query (G09) |
| 3.25 | `Ramesh ka baaki chhod do`, `Sunita ne poora de diya`, `Ramesh ne aadha de diya`, `Geeta ka round off kar do` | A balance query, the amount question, or refused | "Ramesh ke ₹540 baaki hain. Poore maaf karun?", "Sunita ke ₹500 baaki hain. Poore jama likhun?", "Aadha yaani ₹270. Ramesh se jama likhun?", "Geeta ke ₹1,005 baaki hain. ₹5 chhod doon?" | Settle, half, write-off and round-off are worked out from the balance and confirmed (H04 to H09) |

Not built from the list: merging two customers (E13), several shops on one device (E16), Kannada and Marathi number
words (S02).

## Round 4: live runs through the real speech service

Tests: `server/tests/nlu/test_pending_cross.py` (every kind of open question crossed with every kind of answer),
`server/tests/edge/test_g_pending_matrix.py`. Rules: contract 1.9, 1.14.

| # | Said | Before | Now | Fix |
|---|---|---|---|---|
| 4.1 | `Geeta ne 150 diye` → new-customer question → `Ramesh ka 50 udhaar` | Saved a ₹150 payment for Ramesh | Saves ₹50 credit for Ramesh; nothing for Geeta | A complete new sentence spoken while a question is open is parsed fresh and the question is dropped, for every kind of question (1.9) |
| 4.2 | `Ramesh ne 5000 diye` → over-payment question → `Ramesh ka 60 udhaar` | Saved a ₹60 payment | Saves ₹60 credit | The same rule; a number answer whose own direction word disagrees is refused |
| 4.3 | `Ramesh ka 100 udhaar` → `340 ya 740` → `pehla` | Asked the direction, kept 340 silently, and `pehla` saved a payment | Asks "₹340 ya ₹740?", then "Kiska khata?" | Two amounts are asked about first; `pehla` and `doosra` answer only questions with ordered choices (A12) |
| 4.4 | `Ramesh ka 340 udhaar bahut` (an unknown last word, strict mode) | Asked "Kitne rupaye?" | Asks "Ramesh ke ₹340 udhaar likhun?" | An unknown word at the end goes to the confirmation with the amount kept (1.14, strict mode) |

In the same round the reply for several entries was shortened to fit the twelve-word limit:
"2 entry likhi: Ramesh ke ₹340 udhaar, kal ke ₹200 jama."

## Round 5: second independent review

Tests: `server/tests/nlu/test_review2_rules.py` (finding id in every test name), `server/tests/edge/test_y_review.py`.
Rules: contract 1.15.

| # | Said | Before | Now | Fix |
|---|---|---|---|---|
| 5.B1 | `Ramesh ka 75000 udhaar` → "₹75,000, pakka?" → `haan hata do` (also `ok cancel karo`) | Saved ₹75,000 | "Theek hai, entry nahi ki." | An undo or stop word in an answer means no, whatever else the answer holds |
| 5.B2 | `Ramesh ka 340 udhaar` → `Ramesh ka 340 udhaar hata do` (also `Sunita ka 200 udhaar hata do`) | Saved a second ₹340 credit; saved ₹200 for Sunita | Asks "Sirf pichli entry hata sakta hoon: Ramesh, ₹340 udhaar. Hata doon?" | An undo word with an amount is never a new entry |
| 5.B3 | "Rakes naya grahak hai, ya Rakesh?" → `Rakesh nahi`; "Kiska khata?" → `Ramesh nahi Sunita`, `Ramesh ya Sunita` | Saved to Rakesh; saved to Ramesh | Asks again; saves for Sunita; asks again | A denied name is never picked. `X nahi Y` is Y; two names are asked about again |
| 5.B4 | "Kitne rupaye?" → `300 ya 400`; "₹75,000, pakka?" → `7000 ya 7500` | Saved the first amount | Asks "₹300 ya ₹400?" and "₹7,000 ya ₹7,500?" | Two amounts in an answer are asked about, as in a fresh sentence |
| 5.B5 | A Ramesh entry → a question about Sunita → 70 s pass → `nahi, 300` | "Theek kar diya: Ramesh, ₹300 udhaar": changed an unrelated entry | Asks "Ramesh ki ₹340 udhaar entry ₹300 kar doon?" | A correction after a turn that was not an entry names the entry and asks (1.15, 1.16) |
| 5.B5b | A Ramesh entry → `Ramesh ka total` → `cancel` | Reversed the entry silently | Asks "Sirf pichli entry hata sakta hoon: Ramesh, ₹340 udhaar. Hata doon?" | A bare cancel after a turn that was not an entry asks first |
| 5.B6 | `Ramesh ka 340 udhaar` → `Chacha 200 le gaye`; → `500 udhaar`; → `kal 200 diya tha` → `wahi` | Saved all to Ramesh | New-customer question for Chacha; "Kiska khata?"; then a ₹200 payment dated yesterday | Across turns only `aur N`, `N add kar do` and pronouns carry the customer; a first word before the amount is a name; `wahi` picks the last customer |
| 5.B7 | `Ramesh ko 12 ande udhaar`, `Ramesh ne 2 baar 100 diye` | Saved ₹12; saved ₹100 | Asks "Kitne ka?"; asks "Ramesh se ₹100 jama likhun?" | A number before a goods word is a count; a count beside an amount is confirmed |
| 5.B8 | `Ramesh saaman saath le gaya`, `रमेश सामान साथ ले गया` | Saved ₹60 credit | Asks "Kitne rupaye?" | `saath` is 60 only inside a number phrase or before a currency word; Devanagari साथ is never a number |
| 5.B9 | `Ramesh ne 500 diye kya`, `has Ramesh paid 500`, `Ramesh ne 500 diya hoga`; `Ramesh ne 500 na diye` | Saved a ₹500 payment | Asks "Ramesh se ₹500 jama likhun?"; the last is refused | A question or a guess is confirmed; `na` before a verb is a negation |
| 5.B10 | A payment → `Ramesh did not pay 500` | Changed the payment to ₹500 | Refused: "Okay, nothing was saved." | English negations are never corrections |
| 5.B11 | `Mohan bina 500 diye chala gaya`, `Ramesh ka Monday ko 500 udhaar hone wala tha` | A new-customer or date question, then a save that never stated amount or direction | Refused as negated; refused as not yet happened | Unknown words ride along through every later question and are confirmed before the save; `bina ... diye` is a negation |
| 5.B12 | `took 500 from Ramesh`, `I paid Ramesh 500`, `Ramesh and Sunita paid 500`, `Ramesh ne 500 ka maal lautaya` | Credit; payment from Ramesh; payment by Ramesh only; credit | Payment ₹500; refused as out of scope; asks; asks the direction | English direction forms; the shop paying the customer is out of scope; returned goods ask |
| 5.S1 | Write-off saved → `undo karo` | "Undo karne ke liye kuch nahi hai." | "Pichli entry hata di: Ramesh, ₹540 maaf." | A write-off is a last entry like any other |
| 5.S2 | `Ramesh ne 500 ka aadha diya`, `Ramesh ko 500 nahi to 600 udhaar` | Saved ₹500; saved ₹600 | Asks before saving | Words that change an amount are never ignored |
| 5.S3 | `Ramesh ne raat ko 500 diye` | Refused: "raat" read as a second customer | Saves the ₹500 payment | A time word before `ko` is not a name |
| 5.S4 | `Ramesh ne 1 saal pehle 500 diye` | Saved with today's date | Asks "Kaunsa din? Aaj, kal ya parso boliye." | A date never falls back to today |
| 5.S5 | Same-name question about ₹200 → `chai wale ko 300` | Saved the original ₹200 | Asks again | An answer with a different amount is not an answer |
| 5.N1 | `Ramesh ka 340 udhaar` → `nahi 340`; a payment → `that was credit not payment` | "Corrected" 340 to 340; left it a payment | "Sahi amount boliye, ya hata do boliye."; "Corrected: Ramesh, ₹340 credit." | A correction that changes nothing is asked about; a correction can change the kind |
| 5.N2 | `Ramesh ka 500 udhaar hai` | Saved | Asks "Ramesh ke ₹500 udhaar likhun?" | A statement of fact is confirmed |
| 5.N3 | `yaad se Ramesh ko 500 udhaar likho` | Returned a reminder action and lost the entry | Asks; nothing is lost silently (the `yaad se` filler rule is part of round 9) | `yaad` is not a reminder word |
| 5.N4 | `Kochar ko 200 udhaar` | Looped on "Kiska khata?" (cut into `ko` + `char`) | Asks "Kochar naya grahak hai. Khata banaun?" | A token is cut into particle and number only when a customer remains |

Fixed in the server in the same round: balance questions were spoken aloud in private mode; a repeated turn id was
not tied to its sentence (it is now tied to a fingerprint of the text and refused on mismatch).

## Round 6: names left by a real voice session

Tests: `server/tests/nlu/test_voice_names.py`. Rules: contract 1.15, "Names that speech-to-text repeats, splits or
joins". The session had left the customers Jamesh, Diwa Kar and Ramish Ramesh beside the real Ramesh and Divakar.

| # | Said | Before | Now | Fix |
|---|---|---|---|---|
| 6.1 | `Ramish Ramesh ne 50 diye` (Ramesh exists) | Opened an account "Ramish Ramesh" | Saves the payment for Ramesh | A name written twice in two spellings is one name |
| 6.2 | `Diwa Kar ka 50 udhaar` (Divakar exists) | Opened an account "Diwa Kar" | Saves the credit for Divakar | A name split in two, or two pieces written as one, matches the one stored name it fits |
| 6.3 | `Jamesh ka 50 udhaar`, `Tanishke ka 50 udhaar` | Opened new accounts | Asks "Jamesh naya grahak hai, ya Ramesh?" and "Tanishke naya grahak hai, ya Tanishk?" | The new-customer question is on by default; `sh`, `ch`, `th` count as one consonant when a close name is looked for |

## Round 7: third independent review

Tests: `server/tests/nlu/test_review3_rules.py`, `server/tests/app/test_review3.py`,
`server/tests/edge/test_z_review2.py` (Z01 to Z17; Z01 is the whole demo script). Rules: contract 1.16.

| # | Said | Before | Now | Fix |
|---|---|---|---|---|
| 7.B1 | `Ramesh ko 500 udhaar aur Vikram ko 200 udhaar` → `haan` | The question named Ramesh, and one yes opened every new account | Asks "Vikram naya grahak hai. Khata banaun?"; one question for each new name | A question is built from the entry it is about (`pending.index`); each new name is asked about once |
| 7.B1c | `Ramesh ne 500 diye Sunita 200` → `ne diye` | Asked about Ramesh and saved Sunita's ₹200 | Asks about Sunita, then "2 entry likhun: Ramesh se ₹500 jama, Sunita se ₹200 jama?" | Several entries that needed a question are read back in full before the save |
| 7.B2 | `Ramesh ko 2026 mein 500 udhaar diya`, `Ramesh ko 21 November ko 500 udhaar`, `Ramesh ne 200 diye 300 baaki hai`, `Ramesh ko 10:30 pe 500 udhaar`, `Ramesh ko 340 rupaye 50 paise udhaar` | Saved 2,026 and 500; saved 21 for Ramesh and 500 for a new customer "November"; saved 200 and 300; saved 500 twice | Asks the date; asks the date; saves the ₹200 payment only; saves ₹500 once; asks the amount | Dates, times and stated balances are never amounts or names |
| 7.B3 | `Sunita 200` → direction question → `usko diye` | Saved a payment | Saves ₹200 credit | `usko diye` is credit, `usne diye` is payment |
| 7.B4 | `Ramesh ne teen sau das diye` with a customer Mohan Das; `do sau sattar` with a customer Sattar | Saved ₹300; saved ₹200 | Saves ₹310 and ₹270 | A word that continues a number phrase is part of the number even when it is also a stored name |
| 7.B5 | `Ramesh ko 340 udhaar` → `usko 430 kar do` (also `wo galat tha, 430 likho`) | Saved a second credit of ₹430 | Asks "Ramesh ki ₹340 udhaar entry ₹430 kar doon?"; yes corrects it | A correction said as an instruction is confirmed and never adds an entry |
| 7.B6 | `Ramesh ka 200 write off kar do`, `Ramesh ko 50 ka discount diya`; `aur 200 de do`, `Ramesh ko 200 advance diya` | Saved new credits; saved payments | Asks "Ramesh ke ₹200 maaf karun?" and "Ramesh ke ₹50 maaf karun?"; asks the direction | A reduction with an amount is a write-off confirmation, never a credit; `de do` and `advance diya` ask |
| 7.B7 | `Ramesh ne 340 ka saaman liya, 300 diye, 40 udhaar likh do`; `... 500 ka saaman liya aur payment kar diya` | Saved three entries (net ₹80 instead of ₹40); saved a ₹500 credit | Asks "Ramesh ke ₹40 udhaar likhun?"; asks the direction | Three amounts where the first minus the second is the third are one computed credit; a credit followed by a payment cue is never saved as the credit alone |
| 7.B8 | "Ramesh ke ₹340 udhaar likhun?" → `nahi 300 jama` | Saved ₹300 credit | Asks again | A direction word in an answer is honoured through `nahi`; a conflict is not an answer |
| 7.B9 | `Ramesh ko 340 udhaar` → `change karke 430 kar do` | Asked "Karke naya grahak hai?" and moved the entry to "Karke" | Asks "Ramesh ki ₹340 udhaar entry ₹430 kar doon?" | Function words are never customer names |
| 7.B10 | The same entry twice → "Yeh entry abhi likhi hai. Ek aur likhun?" → `nahi 430` | Saved a second entry of ₹430 | Asks again | The duplicate question takes only yes or no |
| 7.S2 | `Pinky se 430 mil gaye`, `Gupta ji ne 150 Google Pay kiya`, `Sharma ji ke do hazaar mein se paanch sau aa gaye` | Asked the direction | Saves the payments (₹430, ₹150, ₹500) | Common payment verbs; in `N mein se M` the first number is the total |
| 7.S3 | Direction question → `haan udhaar`; new-customer question → `nahi banana` | Refused; asked "Banana naya grahak hai?" | Saves the credit; cancels | Natural answers |
| 7.S4 | `Ramesh ko 340 udhaar` → `theek karo 430`; `wo wala 430 hai` | Three questions and a new customer "Karo"; a question about an empty name | The correction confirmation; "Kiska khata?" | Function words are never names; no question about an empty name |
| 7.S5 | `Ramesh ko 340 udhaar` → `amount galat hai` | "Pichli entry hata kar yeh likhoon?" with nothing to write | "Sahi amount boliye, ya hata do boliye." | The unclear-correction wording |
| 7.S7 | An entry → `Ramesh ka total` → `nahi, 430` | "Pehle koi entry nahi hai." | Asks "Ramesh ki ₹340 udhaar entry ₹430 kar doon?" | A correction after a turn that was not an entry names the entry and asks |
| 7.S8 | `500 udhaar` → "Kiska khata?" → `Ramesh ka kal ka` | Saved with today's date | Saves dated yesterday | A date word in an answer is kept |
| 7.S10 | `Ramesh ko teen sau, chalis udhaar` | Two amounts and a direction question | Saves ₹340 | Punctuation inside a spoken number does not split it |
| 7.S11 | `पिंकी ने 100 दिए` (stored as pinky), `Laxmi ne 100 diye` (stored as lakshmi) | Not matched | Both match | Final `y` and `i`, and `x` and `ksh`, are the same in names |
| 7.S12 | `Ramesh ne 200 diye ab kitna baaki hai` | Answered the balance and dropped the payment | Asks "Ramesh se ₹200 jama likhun?" | An entry and a question in one sentence: the entry is never dropped silently |
| 7.S13 | `Lakshmi ko kitna dena hai`; `Ramesh ko 200 de do`; `Sunita ne Ramesh ke 200 diye` | Refused as future; saved a credit; asked "Kitne rupaye?" | The balance; asks the direction; refused as out of scope | `kitna dena hai` is a balance query; an instruction to give asks |
| 7.X1 | `Mohan ka 340 udhaar, kal 200 diya tha` on an empty ledger → `haan` | A regression of this round: the new-customer question was asked twice | One question, then "Naya khata Mohan. 2 entry likhi: Mohan ke ₹340 udhaar, kal ke ₹200 jama." | One new-customer question for each new name, not for each entry |

Fixed in the server and the page in the same round: a question stays open through a silent, empty or too-long turn
and is asked again; a replayed turn id never puts an old question back on screen; the question sheet stays open
through turns that are not an answer.

## Round 8: live check of the published build

Tests: `server/tests/nlu/test_review4_rules.py`, `server/tests/app/test_review4.py`,
`server/tests/edge/test_z_review3.py` (Z18 to Z28). Rules: contract 1.17. In this table Ramesh owes ₹1,030 and Mohan
owes ₹140.

| # | Said | Before | Now | Fix |
|---|---|---|---|---|
| 8.1 | `Ramesh ne 500 diye aur Mohan ne 200 diye` | Asked "Ramesh ke sirf ₹140 baaki hain. ₹500 hi likhun?": Mohan's balance with Ramesh's name and amount | Asks "Mohan ke sirf ₹140 baaki hain. ₹200 hi likhun?" | Every question about one entry of several carries that entry's index and is built from it |
| 8.2 | `Ramesh ka 99000 udhaar aur Mohan ka 88000 udhaar` → `haan`; `Ramesh ne 2000 diye aur Mohan ne 200 diye` → `haan` | One yes saved both; the second doubtful entry was never asked about | Asks "Ramesh ke ₹99,000, pakka?", then "Mohan ke ₹88,000, pakka?"; asks about each over-payment in turn | Each entry is checked on its own; a yes answers only the question that was asked |
| 8.3 | `Ramesh ka 200 udhaar aur Mohan ka baaki maaf kar do` | Asked "Ramesh ke ₹200 maaf karun?"; a yes wrote off ₹200 for Ramesh and dropped the credit | Asks "Mohan ke kitne rupaye?", then reads back "2 entry likhun: Ramesh ke ₹200 udhaar, Mohan ke ₹140 maaf?" | A balance instruction or a reduction stays with the clause it was said in |
| 8.4 | `Ramesh ka khata, Sunita ko pandrah sau udhaar`; heard from the speech service: `Maya khata Shivakumar, Shivakumar ke khate mein pandrah sau rupaye udhaar likh diya` | Asked "Kitne rupaye?" although the amount was said, then "Kiska khata?" | Asks "Kiska khata?" and saves ₹1,500 for the name given | One amount with two names asks whose account and keeps the amount |

## Round 9: fourth independent review

Tests: `server/tests/nlu/test_review5_rules.py`, `server/tests/app/test_review5.py`,
`server/tests/edge/test_z_review4.py` (Z29 to Z46). Rules: contract 1.18, 3.4. In this table Ramesh owes ₹1,030,
Mohan ₹140, Geeta ₹1,005 and Sunita nothing.

| # | Said | Before | Now | Fix |
|---|---|---|---|---|
| 9.B1 | `Ramesh ne 200 ka saaman liya paise de diye` (also `... cash de diya`, `Ramesh 200 ka saaman le gaya aur de gaya`, `Ramesh bought goods for 200 in cash`) | Saved ₹200 credit with no question | Refuses: "Yeh udhaar entry nahi hai, isliye nahi likha." | A purchase with a word that says the money was handed over is a cash sale, never a credit |
| 9.B1d | `Ramesh ko 200 udhaar diye the, aaj de gaya` | Saved a new ₹200 credit | Asks "Ramesh ne diye, ya Ramesh ko udhaar?" | A past credit with a word that says it came back asks the direction |
| 9.B2 | `Ramesh udhaar ke 200 de gaya`, `Ramesh 200 udhaar de gaya` | Saved ₹200 credit | Asks the direction | `udhaar` with a verb of the customer giving and no `ko` asks |
| 9.B3 | `Ramesh ke naam se 200 jama karo`, `Ramesh ke naam 200 aaye`, `Ramesh ke khate mein 200 payment likh do` | Saved ₹200 credit | Saves a ₹200 payment | `ke naam` and `ke khate mein` name the account; a payment word in the clause wins |
| 9.B4 | `Vikram ko 500 udhaar` → `haan bhai` (also `yeah open it`) | Asked "Bhai naya grahak hai?" and saved ₹500 to "Bhai" (or to "Open") | Opens the account for Vikram and saves his ₹500 | Yes with an address word is yes; address words and function words are never names |
| 9.B5 | `Ramesh ne 500 ka saaman liya 200 diye baaki udhaar`; `... 500 ka saaman liya 300 baaki hai` | Saved credits of ₹500 and ₹200; saved ₹500 credit | Asks "Ramesh ke ₹300 udhaar likhun?" in both | Purchase, paid amount and a word for the rest are one computed credit, confirmed |
| 9.B6 | `Ramesh also paid 200`; `100 kam karo`; `he took another 100` after a Ramesh entry | Saved to a new customer "Ramesh Also"; asked about customers "Kam" and "Another" | Saves the ₹200 payment for Ramesh; asks "Kiska khata?"; saves ₹100 credit for Ramesh | An unknown word that is not directly before a particle is never a customer; English adverbs are fillers; `he` carries the last customer |
| 9.B6b | `Ramesh ne 500 ka saaman liya, 200 udhaar rakha` → `haan` | Asked "Rakha naya grahak hai?" and saved ₹200 to "Rakha" | Asks "Ramesh ke ₹200 udhaar likhun?" and saves one credit of ₹200 | `rakha` is never a customer; a purchase amount followed by a smaller amount kept as udhaar is one computed credit |
| 9.B7 | The 9.B6 sentences with the new-customer question switched off | Saved with no question | A close name always asks; a new name is taken silently only directly before a particle | Strict mode covers a word that would become a customer |
| 9.B8 | `Ramesh ka 340 udhaar` → `Ramesh ka 430 likhna tha` (also `430 kar do`, `sorry 430`, `Ramesh ka 430 udhaar tha`) | Saved a second entry, or asked "Kiska khata?" | Asks "Ramesh ki ₹340 udhaar entry ₹430 kar doon?" | A restated correction right after an entry is the correction confirmation |
| 9.B9 | `Ramesh ka udhaar 200 ho gaya`, `Ramesh ka 200 udhaar batao`; `Ramesh se 200 vasool karne hain`; `Ramesh ka 200 udhaar likhna mat`; `Ramesh ne 200 diye the kya aur Mohan ko 100 udhaar`; `Ramesh ka 200 udhaar likh dena kal` | All saved with no question | Answers "Ramesh ke ₹1,030 baaki hain."; refused as not yet happened; refused as negated; reads both entries back and asks; asks the date | A stated balance and `batao` are queries; still to collect is future; a negation after the verb counts; a question clause makes the whole sentence a confirmation |
| 9.B10 | `Ramesh paid 200 last night`; `kal Ramesh ne 200 diye the aur Mohan ne bhi 100 diye the` | Dated today; the second entry dated today | Dated yesterday; both dated yesterday | `last night` is yesterday; a date word before the first name covers every clause without its own |
| 9.S1 | `Mohan ne 100 diye aur 100 diye` (owes ₹140); `Mohan ka 400 maaf kar do`; `Sunita ka 50 maaf kar do` | Saved both payments; the write-off question did not say it was above the balance | Asks "Mohan ke sirf ₹140 baaki hain. ₹100 hi likhun?"; "Mohan ke sirf ₹140 baaki hain. ₹400 maaf karun?"; "Sunita ka koi hisaab nahi hai." | Over-payment adds up one customer's payments; a write-off above the balance states the balance |
| 9.S2 | The same entry three times | The third repeat was saved without a question | Asks "Yeh entry abhi likhi hai. Ek aur likhun?" on every repeat | The duplicate question is asked every time |
| 9.S3 | Three customers named Suresh, one with no tag | The question offered two, and `pehle wale` saved to the one that was not offered | "Kaunse Suresh: bina tag wale, chai wale ya gali 4?"; `pehla`, `pehle wale`, `doosra`, `teesra` follow the spoken order | All are offered in one order, spoken and answered the same way |
| 9.S4 | `Suresh ne poora de diya` → `chai wale` | Answered the balance and dropped the instruction | Asks "Suresh chai wale ke ₹500 baaki hain. Poore jama likhun?" | The instruction goes on after the same-name answer |
| 9.S5 | `Ramesh ne 15 ko 200 diye`; `Ramesh ko sath sau udhaar` | Read 15 as an amount; saved ₹6,000 | Asks the date; asks "₹700 ya ₹6,000?" | A number up to 31 before `ko` is a day; `sath sau` has two readings |
| 9.S6 | `Geeta ne 1000 diye baaki chhod do`; `Mohan ne 100 diye aur baaki maaf kar do` | Asked "Geeta ke ₹1,000 maaf karun?": the paid amount as the write-off | Reads back "2 entry likhun: Geeta se ₹1,000 jama, ₹5 maaf?" and "2 entry likhun: Mohan se ₹100 jama, ₹40 maaf?" | A payment plus "drop the rest" is a payment and a write-off of the rest |
| 9.S7 | `Ramesh ne 100 diye` → `nahi Geeta ko 500 udhaar` → `nahi` | "Pichli entry hata kar yeh likhoon?", and the no saved the new entry | "Pichli entry hata kar Geeta ke ₹500 udhaar likhoon?"; the no saves nothing | A no cancels, and the question names the new entry |
| 9.S8 | Direction question → `kal udhaar`; "Rames naya grahak hai, ya Ramesh?" → `haan`; `Ramesh ne jaldi se 200 diye aur Mohan ko 100 udhaar`; which-entry question → `Mohan` | Answered yesterday's total and dropped the entry; opened the account "Rames"; asked "Kitne rupaye?"; not accepted | Saves the credit dated yesterday; asks again; saves both entries; corrects Mohan's entry | A date word beside a direction answer is kept; an either-or question takes no bare yes; `jaldi se` is a filler; a name picks the entry |
| 9.S9 | `Ramesh took 300` → `he paid 200`; `Ramesh paid in full`; `Ramesh paid 200 this morning` | "Whose account?"; "Kitne rupaye?"; replied in Hindi | Saves the ₹200 payment; asks "Ramesh owes ₹1,030. Record all of it as received?"; replies in English | English pronouns carry over; `paid in full` settles; English sentences get English replies |

Fixed in the page in the same round (contract 3.4): the queue of typed sentences now waits while any question is
open, and a queued sentence whose question was lost is sent again once under a new id instead of being stuck.

Found while this round was being built, and fixed with it:

| Said | Before | Now | Fix |
|---|---|---|---|
| `Mohan ka 340 udhaar, kal 200 diya tha` with a customer Imran in the ledger | "Mohan naya grahak hai, ya Imran?", and a bare yes was asked again | "Mohan naya grahak hai. Khata banaun?" | A close name differs in one consonant and in nothing else; the vowels must be the same |
| `Ramesh ka 300 udhaar, 100 chawal ka aur 200 aate ka` | Asked about a customer "Chawal" | Asks about Ramesh's entry; no question names a goods word | A goods word is never a customer name |
| `anil ko udhaar` → `do sau`, with the new-customer question switched off | Asked "Anil naya grahak hai?" although the switch was off | Saves ₹200 credit for Anil | A name accepted before a particle stays accepted through a later question |

## Round 10: noise

Tests: `server/tests/app/test_audio.py`, `test_noise_wiring.py`, the noise tests in `server/tests/e2e`, and
`NOISE_*` in `server/tests/nlu/test_review5_rules.py`. Rules: contract 3.5. The measurements are in the README
("Noise handling and noise test"). A row marked "noisy turn" was replayed with the flag the server sets when the
audio of a turn is noisy.

| # | Said | Before | Now | Fix |
|---|---|---|---|---|
| 10.1 | "Geeta ka pandrah sau udhaar likh do" under background talk almost as loud as the speaker; the speech service returned `pandra sau udhaar likh do, mohan.` (Geeta was lost and a background voice supplied "mohan") | Saved ₹1,500 credit for Mohan | On a noisy turn: asks "Mohan ke ₹1,500 udhaar likhun?", and a no saves nothing | A turn whose speaker is less than 14 dB above the background is read back and confirmed before it is saved |
| 10.2 | `Ramesh ka 340 udhaar` on a noisy turn → `haan` | Saved at once | Asks "Ramesh ke ₹340 udhaar likhun?", then saves | The same rule; a query on a noisy turn (`Ramesh ka total`) is still answered at once |
| 10.3 | Any sentence, when the speaker starts talking as they press the button | The first design measured the background from the moment before the press, so the speaker's own first words counted as background and every such turn was "noisy" (12 of 12 clean clips) | Not noisy: clean and lightly noisy clips are never flagged, with or without a lead-in | The background level is the lower of the pre-press level and the level a quarter of the turn's frames are below |
| 10.4 | Sentences with a voice in the background before or after the speaker (`Sunita paid five hundred rupees. So, paanch.`, `Geeta ne nau sau pachas rupaye diye Mohan.`) | The extra words reached the parser and led to a question | Audio outside the speaker's own burst reaches the speech service 12 dB quieter; in the 120-turn test this changed one result (10 of 12 saved at 10 dB of babble against 9) | The foreground gate; it never removes audio and does nothing when speaker and background are too close |

## Round 11: a refused sentence said while a question is open

Tests: `server/tests/nlu/test_pending_cross.py` (every kind of open question crossed with a sentence of every
refusal reason; 1,000 cases in that file). Rules: contract 1.18, "Answers". Ramesh owes ₹1,030.

| # | Said | Before | Now | Fix |
|---|---|---|---|---|
| 11.1 | `Ramesh ka 75000 udhaar` → "₹75,000, pakka?" → `Ramesh ka 200 udhaar nahi hai` | Saved ₹200 credit: the 200 was taken as the corrected amount | "Theek hai, entry nahi ki." Nothing is saved | A sentence that is refused on its own is never an answer; a negation cancels a yes-or-no question |
| 11.2 | `Ramesh ka teen chaar sau udhaar` → "₹340 ya ₹400?" → `Ramesh ne 200 ka saaman liya paise de diye` | Saved ₹200 credit | Refused as a cash sale. Nothing is saved | The same rule, for `out_of_scope` |
| 11.3 | "Kitne rupaye?" → `Ramesh ko 200 dene hain`; "₹340 ya ₹400?" → `Wholesaler ko 5000 diye` | Repeated the question (nothing saved) | Refused as not yet happened; refused as out of scope | The refusal is the result, as it is with no question open |
| 11.4 | `Ramesh ka 340 udhaar` → `nahi, 430` on a noisy turn | Asked "Ramesh ke ₹430 udhaar likhun?", which did not say an entry was being replaced | Asks "Ramesh ki ₹340 udhaar entry ₹430 kar doon?" | On a noisy turn a correction is confirmed with the correction wording |

## Known limits that are not faults of a rule

- A number heard as another valid number (340 heard as 740) cannot be seen by any rule. It is caught by the spoken
  readback and corrected with "Nahi, 340"; a pair the shop has corrected twice is remembered and asked about next
  time.
- A bare "nahi" to "Kitne rupaye?" or "Kiska khata?" repeats the question; two answers that do not settle a
  question cancel it.
- The noise test used a synthetic voice with generated noise. Recordings from a real counter are not measured yet.
