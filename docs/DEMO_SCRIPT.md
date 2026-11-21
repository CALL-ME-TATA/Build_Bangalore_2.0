# Demo script

For the 2 to 3 minute video and for the live judge demo. The reply wordings below are the templates in
`server/app/replies.py`; the balances are worked out step by step from an empty ledger.

## Before you start

- Build the web app once: `cd frontend`, `npm ci`, `npm run build`.
- Use a fresh ledger so the balances match. Either run `python -m app.admin purge` from `server/`, or start with a
  separate file: `python scripts/dev.py --live --db data/demo/khata.db` (a new file is empty).
- Choose a variant (it changes only the first sentence for each new name):
  - **Variant A, new-customer question on (the default):** `python scripts/dev.py --live --db data/demo/khata.db`
  - **Variant B, no question:** `python scripts/dev.py --live --db data/demo/khata.db --set CONFIRM_NEW_CUSTOMER=0`
- Open the app in Chrome (over the HTTPS tunnel on a phone), tap "Shuru karein" once so the greeting plays and the
  speech sockets warm up. Hold the button, speak, release. One sentence per press, at a normal pace.
- Timing: "Aur 200 payment mila" uses the last customer only within 60 seconds of the previous entry. Say the
  steps without long pauses. If it is late, the reply is "Kiska khata?"; answer "Ramesh".
- Strict mode is on, so a sentence with a word the app does not know is asked about before saving. Stay close to the
  sentences below, and rehearse each one once against the live service.

Reading the tables: "Variant A" and "Variant B" are the two reply columns of step 2 only. Every other step is the same
in both.

## Short version (about 60 seconds)

| # | You say | Reply (spoken and on screen) | Ramesh's balance |
|---|---|---|---|
| 1 | (tap "Shuru karein") | "Namaste! Main KhataVaani hoon, ek AI sahayak." | none yet |
| 2A | "Ramesh ka 340 udhaar" | Variant A: "Ramesh naya grahak hai. Khata banaun?" Then you say "haan": "Naya khata Ramesh. Ramesh ke khate mein ₹340 udhaar likh diya." | 340 |
| 2B | "Ramesh ka 340 udhaar" | Variant B: "Naya khata Ramesh. Ramesh ke khate mein ₹340 udhaar likh diya." | 340 |
| 3 | "Nahi, 430" | "Theek kar diya: Ramesh, ₹430 udhaar." The 340 card is struck through and a 430 card appears | 430 |
| 4 | "Aur 200 payment mila" | "Ramesh se ₹200 mile, jama kar diya." | 230 |
| 5 | "Ramesh ka total?" | "Ramesh ke ₹230 baaki hain." | 230 |
| 6 | "Aaj ka hisaab batao" | "Aaj ₹430 udhaar gaya, ₹200 jama hue. Sabse zyada baaki: Ramesh, ₹230." | 230 |

Check of step 6: today's credit is 430 (the reversed 340 does not count), today's payment is 200, and Ramesh's due
is 430 - 200 = 230.

## Full version (about 2.5 minutes)

Steps 1 to 5 are the short version. The balance after each step is Ramesh's, from an empty ledger.

1. **Greeting.** Tap "Shuru karein".
   Reply: "Namaste! Main KhataVaani hoon, ek AI sahayak."
   Say: "The first thing it does is tell you it is an AI." Balance: none.
2. **New customer and credit.** "Ramesh ka 340 udhaar".
   - Variant A: it does not save yet. Reply: "Ramesh naya grahak hai. Khata banaun?" Say "haan".
   - Reply (both variants): "Naya khata Ramesh. Ramesh ke khate mein ₹340 udhaar likh diya."
   - Screen: card + ₹340 Credit. Balance: 340.
   - Say (variant A): "It never opens an account for a name it has not heard, without asking."
3. **Spoken correction.** "Nahi, 430".
   Reply: "Theek kar diya: Ramesh, ₹430 udhaar."
   Screen: the ₹340 card is struck through and a new + ₹430 card appears. Say: "Nothing was edited. The old entry is
   reversed and a new one is added." Balance: 430.
4. **Payment.** "Aur 200 payment mila".
   Reply: "Ramesh se ₹200 mile, jama kar diya."
   Screen: card - ₹200 Payment. Ramesh is carried over from the last entry. Balance: 430 - 200 = 230.
5. **Balance query.** "Ramesh ka total?"
   Reply: "Ramesh ke ₹230 baaki hain." Balance: 230.
6. **Ambiguous number.** "Ramesh ka teen chaar sau udhaar".
   It could be 340 or 400, so it asks: "₹340 ya ₹400?" Nothing is saved. Answer "pehla".
   Reply: "Ramesh ke khate mein ₹340 udhaar likh diya." Balance: 230 + 340 = 570.
   Say: "It would not guess between two readings of the same words."
7. **Undo.** "undo karo".
   Reply: "Pichli entry hata di: Ramesh, ₹340 udhaar." Balance: 570 - 340 = 230.
   Say: "Undo adds a reversal. The old row stays in the ledger."
8. **A sentence that is not an entry.** "Wholesaler ko paanch hazaar diye".
   Reply: "Yeh udhaar entry nahi hai, isliye nahi likha." Nothing is saved. Balance: 230.
   Say: "A payment to a supplier is not a customer's udhaar, so it is refused."
9. **A bill with a part payment.** "Ramesh ka bill 450 hai, 200 diya, baaki udhaar".
   It works out 450 - 200 and asks: "Ramesh ke ₹250 udhaar likhun?" Answer "haan".
   Reply: "Ramesh ke khate mein ₹250 udhaar likh diya." Balance: 230 + 250 = 480.
   Say: "Anything the app computed is confirmed before it is written."
10. **Balance again.** "Ramesh ka total?"
    Reply: "Ramesh ke ₹480 baaki hain." Balance: 480.
11. **Daily summary.** "Aaj ka hisaab batao".
    Reply: "Aaj ₹680 udhaar gaya, ₹200 jama hue. Sabse zyada baaki: Ramesh, ₹480."
    Check: today's credits are 430 and 250 (340 was undone), payment 200, and 680 - 200 = 480.
12. **Barge-in.** While any reply is playing, press the button. The reply stops at once and the app listens.

Optional extras, after the summary (they change the ledger, so they come last):

- **Two entries in one sentence.** "Mohan ka 340 udhaar, kal 200 diya tha". With variant A it first asks "Mohan naya
  grahak hai. Khata banaun?"; answer "haan". The reply follows the template "N entry likhi: ..." with the new-account
  prefix, for example "Naya khata Mohan. 2 entry likhi: Mohan ke ₹340 udhaar, kal ke ₹200 jama." Mohan's balance is
  340 - 200 = 140. (The same wording with Ramesh is "2 entry likhi: Ramesh ke ₹340 udhaar, kal ke ₹200 jama.")
- **Large amount.** "Ramesh ka paanch lakh udhaar". Reply: "₹5,00,000, pakka?" Answer "nahi": "Theek hai, entry nahi
  ki." Nothing is saved, and the balances above do not change.

## What to say about the design

- **Deterministic parser.** "Amounts and direction come from a rule-based grammar, not a language model. 'Dedh sau'
  is always 150 and 'saade teen sau' is always 350. It is tested over every amount from 1 to 9,99,999 and the golden
  cases. If it is not sure, it asks one short question and saves nothing." The edge-case list and its results are in
  docs/EDGE_CASES.md and docs/EDGE_REPORT.md.
- **Why we ask for words.** "Gnani's digit output mode wrote 'dedh sau' as 1,500 and 'three forty' as 3:40. So we
  request Latin transliteration, with numbers as words, and compute the amount ourselves."
- **Latency (measured on 2026-11-21 with recorded audio through the real Gnani services).**
  - The first reply audio arrives 0.34 to 0.66 s after the end of speech.
  - The final transcript arrives 0.21 to 0.41 s after the button is released, because we send the `commit` frame on release.
  - The first speech chunk arrives 0.12 to 0.39 s after the reply text is ready, because the text-to-speech socket is already open.
  - The latency chip on the Bolo screen shows the numbers for your own turns; tap it for the per-hop breakdown.
- **Privacy.** "Names and transcripts are encrypted. The ledger is append-only. After judging we purge everything with
  one command." Private mode (Settings) shows balance answers on screen and says "Jawab screen par hai." instead of
  speaking them.
- **Reminders.** "Only customers who opted in. The message is rebuilt from the current balance and goes out by SMS
  only when the shopkeeper presses Send reminder, at most once a day per customer. Nothing is sent on its own."

## If something goes wrong

- **Network is down or slow.** The reply is "Network mein dikkat hai, dobara boliye." Wait a few seconds and repeat the
  sentence. Nothing was saved for a failed turn. Typed sentences are queued while offline and sent on reconnect.
- **Microphone blocked.** Click the lock icon in Chrome's address bar, allow the microphone, and reload. On a phone
  the page must be opened over HTTPS (the tunnel URL), or the microphone is refused.
- **Use "Type karein".** Type the same sentence in the text box. It runs the same parser, ledger and spoken reply,
  only without speech recognition. In the mock run (no key) replies are a test tone.
- **No connection at the venue.** The demo route (`#/demo`) plays a scripted session on the page without touching the
  server; use it, or a recorded video, and say that it is scripted.
- **A sentence was misheard or not understood.** The reply is "Maaf kijiye, samajh nahi aaya. Dobara boliye." Repeat
  it. If a wrong amount was saved, say "undo karo" or "Nahi, <sahi amount>".
- **A repeated entry.** If a sentence is repeated within 30 seconds the app asks "Yeh entry abhi likhi hai. Ek aur
  likhun?" Answer "nahi" unless you meant it.
- **Nothing heard.** A press under half a second is ignored. Silence gets "Kuch sunai nahi diya. Dobara boliye." and a
  very long recording gets "Bahut lamba ho gaya. Chhote vaakya mein boliye."
- **A question is waiting.** Answer it in one short phrase ("haan", "nahi", "pehla", a number), or say a full new
  sentence, which cancels the question. A question expires after 60 seconds.
