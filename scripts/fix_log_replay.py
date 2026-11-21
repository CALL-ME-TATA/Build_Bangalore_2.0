"""Replay the cases of docs/FIX_LOG.md through the real parser and pipeline and print what each turn does.

    python scripts/fix_log_replay.py                 every case
    python scripts/fix_log_replay.py 5. 7.B          only the cases whose id starts with one of these
    python scripts/fix_log_replay.py --server PATH   use the server folder of another checkout

Each case runs on its own temporary ledger with an injected clock (the shop helper of the edge-case suite), so
nothing here touches a real ledger or the speech service. Turns are two seconds apart; ("wait", seconds) lets time
pass. One output line per turn:

    'what was said' -> status/action/reason [ledger rows added] says 'reply'

The case ids are the row numbers of docs/FIX_LOG.md. The "Now" column of that file is this script's output.
"""
from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
args = sys.argv[1:]
server = ROOT / "server"
if "--server" in args:
    i = args.index("--server")
    server = Path(args[i + 1]).resolve()
    del args[i:i + 2]
sys.path.insert(0, str(server))
sys.path.insert(0, str(server / "tests" / "edge"))

from kit import Shop  # noqa: E402  (the edge-case test kit: real parser, real pipeline, temporary ledger)

W = "wait"

# Ledgers. `seed` rows are (name, kind, amount[, days_ago[, tag]]); `customers` are (name, tags) with no entries.
BASE = {"seed": [("ramesh", "credit", 540), ("sunita", "credit", 500), ("mohan", "credit", 60)],
        "customers": [("rakesh", None), ("sharma", None)]}
EMPTY = {"seed": [], "customers": []}
TWO_SURESH = {"seed": [("ramesh", "credit", 540), ("sunita", "credit", 500)],
              "customers": [("suresh", ["chai wale"]), ("suresh", ["gali number 3"]), ("rakesh", None)]}
PAIR = {"seed": [("ramesh", "credit", 1030), ("mohan", "credit", 140)], "customers": []}
FOUR = {"seed": [("ramesh", "credit", 1030), ("mohan", "credit", 140), ("geeta", "credit", 1005)],
        "customers": [("sunita", None)]}


def only(*seed: tuple) -> dict:
    return {"seed": list(seed), "customers": []}


CASES: list[tuple[str, dict, list]] = [
    # ---- round 1: review of the first build ---------------------------------------------------------------------
    ("1.1a", only(("sharma", "credit", 100)), ["Sharma ka 100 udhaar", "Chacha ne 500 diye."]),
    ("1.1b", only(("sharma", "credit", 100)), ["Sharma ka 100 udhaar", "Aunty ko 200 diye."]),
    ("1.1c", only(("sharma", "credit", 100)), ["Sharma ka 100 udhaar", "Abhi ko 200 udhaar diya."]),
    ("1.2a", EMPTY, ["Uska 200 udhaar likh do."]),
    ("1.2b", BASE, ["Ramesh ka 100 udhaar", "Usko 100 udhaar diya."]),
    ("1.3a", BASE, ["Ramesh ka teen sau chalis udhar kal do sau diya tha.", "Nahi chaar sau tees."]),
    ("1.3b", BASE, ["Ramesh ka teen sau chalis udhar kal do sau diya tha.", "340 nahi 430."]),
    ("1.4a", BASE, ["Ramesh ne teen sau do din pehle diye the."]),
    ("1.4b", BASE, ["Ramesh ko paanch sau teen din pehle udhaar diya."]),
    ("1.5a", BASE, ["Ramesh ka 200 udhaar nahi hai."]),
    ("1.5b", BASE, ["Ramesh ko 200 udhaar nahi dena."]),
    ("1.6a", BASE, ["Ramesh ka 340 udhaar", "Sunita ki entry hata do."]),
    ("1.6b", BASE, ["Ramesh ka 340 udhaar", "Pehli entry hatao."]),
    ("1.6c", BASE, ["Ramesh ka 340 udhaar", "Ramesh ka order cancel ho gaya."]),
    ("1.7a", BASE, ["Ramesh ka 340 udhaar", "Nahi Sunita ka total batao."]),
    ("1.7b", BASE, ["Ramesh ka 340 udhaar", "Nahi Sunita ne 500 diye."]),
    ("1.8a", BASE, ["Sunit ko 200 udhaar diya."]),
    ("1.8b", only(("ramesh sharma", "credit", 100)), ["Rakesh Sharma ko 200 udhaar diya."]),
    ("1.9a", BASE, ["Ramesh 200", "Ramesh ne diye."]),
    ("1.9b", TWO_SURESH, ["Suresh ko 200 udhaar", "Chai wale."]),
    ("1.9c", BASE, ["Ramesh ka 75000 udhaar", "Nahi 7500."]),
    ("1.10a", BASE, ["Ramesh Chopra ko 200 udhaar diya."]),
    ("1.10b", BASE, ["Maine Ramesh ko 200 udhaar diya."]),
    ("1.10c", BASE, ["Ramesh has paid 500."]),
    ("1.10d", BASE, ["Give Ramesh 300 credit."]),
    ("1.11", BASE, ["Kya Ramesh ne 500 diye the?"]),
    ("1.12", BASE, ["Ramesh ke naam likh do sau rupaye."]),
    ("1.13a", BASE, ["Ramesh ko 200 udhaar dena."]),
    ("1.13b", BASE, ["Ramesh ko 200 dene hain"]),
    ("1.14", BASE, ["Ramesh ne 500 diye Sunita bhi."]),
    ("1.15", only(("ramesh", "credit", 300, 1), ("sunita", "credit", 50)), ["Kal kitna udhaar gaya?"]),
    ("1.16", BASE, ["200 udhaar", "Dobara boliye."]),
    # ---- round 2: first voice test ------------------------------------------------------------------------------
    ("2.1", BASE, ["Pay five hundred rupees to Ramesh."]),
    ("2.2", BASE, ["Ramesh ka 100 udhaar", "Maine char sau pachpan rupaye diye."]),
    ("2.3a", BASE, ["Ramesh ki biwi ka khata?"]),
    ("2.3b", BASE, ["Ramesh ki bevi. Ka khata?"]),
    ("2.4", BASE, ["Ramesh 1000", "ami Hazar.", "Udhaar."]),
    ("2.5", BASE, ["Ramesh ka 300 udhaar", "nahi nahi, saadh sau rupaye."]),
    ("2.6", BASE, ["Ramesh ka 300 udhaar", "nahi nahi, sau rupaye aaye mere paas."]),
    ("2.7", BASE, ["Ramesh ne paanch sa rupaye diye"]),
    ("2.8a", BASE, ["Five hundred in Ramesh's account."]),
    ("2.8b", BASE, ["Give Ramesh five hundred rupees worth of product."]),
    ("2.9", BASE, ["Sunita paid five hundred rupees"]),
    # ---- round 3: the edge-case list ----------------------------------------------------------------------------
    ("3.1a", BASE, ["Ramesh ka 2k udhaar"]),
    ("3.1b", BASE, ["Ramesh ka 2.5k udhaar"]),
    ("3.2a", BASE, ["Ramesh ka 5 crore udhaar"]),
    ("3.2b", BASE, ["Ramesh ka 999999999999 udhaar"]),
    ("3.3a", BASE, ["teen customer aaye the"]),
    ("3.3b", BASE, ["Ramesh ko 2 kilo chawal udhaar"]),
    ("3.4", BASE, ["uh Ramesh ka matlab 340 udhaar"]),
    ("3.5", BASE, ["Ramesh ka 200 udhaar", "nahi, Ramesh ka nahi, Sunita ka 200"]),
    ("3.6", BASE, ["Ramesh ka 340 udhaar", "Sunita ka 200 udhaar", "undo karo", "nahi, 430"]),
    ("3.7a", BASE, ["Ramesh ka 340 udhaar ruko"]),
    ("3.7b", BASE, ["Ramesh bol raha tha 340 udhaar"]),
    ("3.8a", BASE, ["Wholesaler ko 5000 diya"]),
    ("3.8b", BASE, ["Cash mein 300 becha"]),
    ("3.8c", BASE, ["Ramesh ka 100 udhaar", "maal ka paisa 3000 diya"]),
    ("3.8d", BASE, ["Dukaan ka kiraya 8000"]),
    ("3.9a", BASE, ["sunita kofivehundred diya"]),
    ("3.9b", BASE, ["sunitako 500 diya"]),
    ("3.10a", BASE, ["Sunitha ka 50 udhaar"]),
    ("3.10b", BASE, ["Rakes ka 50 udhaar"]),
    ("3.11a", BASE, ["Ramesh ka 200 ya 300 udhaar"]),
    ("3.11b", BASE, ["Ramesh ka teen chaar sau udhaar"]),
    ("3.12", BASE, ["Ramesh ka minus 50 udhaar"]),
    ("3.13", BASE, ["Ramesh ka 340 udhaar, total 800 ho gaya"]),
    ("3.14a", only(("ramesh", "credit", 300, 8), ("sunita", "credit", 50)), ["pichle hafte kitna udhaar gaya"]),
    ("3.14b", BASE, ["Is mahine ka total"]),
    ("3.14c", BASE, ["Total udhaar kitna hai"]),
    ("3.15", only(("ramesh", "credit", 340)), ["Ramesh ne 1000 diya"]),
    ("3.16a", BASE, ["Ramesh ka 340 udhaar", (W, 61), "200 add kar do"]),
    ("3.16b", BASE, ["Ramesh ka total", "aur 200"]),
    ("3.16c", BASE, ["Ramesh ne 100 diye", "50 add kar do"]),
    ("3.17", only(("das", "credit", 50)), ["Das ka 100 udhaar"]),
    ("3.18", BASE, ["Ramesh ne Sunita ko 100 diya"]),
    ("3.19", BASE, ["Ramesh ka bill 450 hai, 200 diya, baaki udhaar"]),
    ("3.20", BASE, ["Send Ramesh a reminder for 850"]),
    ("3.21", BASE, ["100 wapas kiya", "Ramesh ko 100 wapas kiya"]),
    ("3.22a", BASE, ["gave Sunita 500 on credit"]),
    ("3.22b", BASE, ["Ramesh ne 30 udhaar chuka diya"]),
    ("3.22c", BASE, ["Ramesh ka udhaar wapas aaya 20"]),
    ("3.22d", BASE, ["Ramesh 100 note kar lo"]),
    ("3.23a", BASE, ["Sunita ka 3,40 udhaar"]),
    ("3.23b", BASE, ["Ramesh Ramesh ka 340 340 udhaar"]),
    ("3.23c", BASE, ["Ramesh ka four three zero udhaar"]),
    ("3.24a", BASE, ["Ramesh"]),
    ("3.24b", BASE, ["haan"]),
    ("3.24c", BASE, ["Ramesh ka 340 kitna hua?"]),
    ("3.25a", BASE, ["Ramesh ka baaki chhod do"]),
    ("3.25b", BASE, ["Sunita ne poora de diya"]),
    ("3.25c", BASE, ["Ramesh ne aadha de diya"]),
    ("3.25d", only(("geeta", "credit", 1005)), ["Geeta ka round off kar do"]),
    # ---- round 4: live runs through the real server -------------------------------------------------------------
    ("4.1", only(("ramesh", "credit", 340)), ["Geeta ne 150 diye", "Ramesh ka 50 udhaar"]),
    ("4.2", only(("ramesh", "credit", 70)), ["Ramesh ne 5000 diye", "Ramesh ka 60 udhaar"]),
    ("4.3", BASE, ["Ramesh ka 100 udhaar", "340 ya 740", "pehla"]),
    ("4.4", BASE, ["Ramesh ka 340 udhaar bahut"]),
    # ---- round 5: second review ---------------------------------------------------------------------------------
    ("5.B1a", BASE, ["Ramesh ka 75000 udhaar", "haan hata do"]),
    ("5.B1b", BASE, ["Ramesh ka 75000 udhaar", "ok cancel karo"]),
    ("5.B2a", BASE, ["Ramesh ka 340 udhaar", (W, 45), "Ramesh ka 340 udhaar hata do"]),
    ("5.B2b", BASE, ["Ramesh ka 340 udhaar", (W, 45), "Sunita ka 200 udhaar hata do"]),
    ("5.B3a", BASE, ["Rakes ka 50 udhaar", "Rakesh nahi"]),
    ("5.B3b", BASE, ["200 udhaar", "Ramesh nahi Sunita"]),
    ("5.B3c", BASE, ["200 udhaar", "Ramesh ya Sunita"]),
    ("5.B4a", BASE, ["Ramesh ko udhaar", "300 ya 400"]),
    ("5.B4b", BASE, ["Ramesh ka 75000 udhaar", "7000 ya 7500"]),
    ("5.B5a", BASE, ["Ramesh ko 340 udhaar", "Sunita ne 2000 diye", (W, 70), "nahi, 300"]),
    ("5.B5b", BASE, ["Ramesh ko 340 udhaar", "Ramesh ka total", "cancel"]),
    ("5.B6a", BASE, ["Ramesh ka 340 udhaar", "Chacha 200 le gaye"]),
    ("5.B6b", BASE, ["Ramesh ka 340 udhaar", "500 udhaar"]),
    ("5.B6c", BASE, ["Ramesh ka 340 udhaar", "kal 200 diya tha", "wahi"]),
    ("5.B7a", BASE, ["Ramesh ko 12 ande udhaar"]),
    ("5.B7b", BASE, ["Ramesh ne 2 baar 100 diye"]),
    ("5.B8a", BASE, ["Ramesh saaman saath le gaya"]),
    ("5.B8b", BASE, ["रमेश सामान साथ ले गया"]),
    ("5.B9a", BASE, ["Ramesh ne 500 diye kya"]),
    ("5.B9b", BASE, ["has Ramesh paid 500"]),
    ("5.B9c", BASE, ["Ramesh ne 500 na diye"]),
    ("5.B9d", BASE, ["Ramesh ne 500 diya hoga"]),
    ("5.B10", BASE, ["Ramesh ne 340 diye", "Ramesh did not pay 500"]),
    ("5.B11a", BASE, ["Mohan bina 500 diye chala gaya"]),
    ("5.B11b", BASE, ["Ramesh ka Monday ko 500 udhaar hone wala tha"]),
    ("5.B12a", BASE, ["took 500 from Ramesh"]),
    ("5.B12b", BASE, ["I paid Ramesh 500"]),
    ("5.B12c", BASE, ["Ramesh and Sunita paid 500"]),
    ("5.B12d", BASE, ["Ramesh ne 500 ka maal lautaya"]),
    ("5.S1", BASE, ["Ramesh ka baaki maaf kar do", "haan", "undo karo"]),
    ("5.S2a", BASE, ["Ramesh ne 500 ka aadha diya"]),
    ("5.S2b", BASE, ["Ramesh ko 500 nahi to 600 udhaar"]),
    ("5.S3", BASE, ["Ramesh ne raat ko 500 diye"]),
    ("5.S4", BASE, ["Ramesh ne 1 saal pehle 500 diye"]),
    ("5.S5", TWO_SURESH, ["Suresh ko 200 udhaar", "chai wale ko 300"]),
    ("5.N1a", BASE, ["Ramesh ka 340 udhaar", "nahi 340"]),
    ("5.N1b", BASE, ["Ramesh ne 340 diye", "that was credit not payment"]),
    ("5.N2", BASE, ["Ramesh ka 500 udhaar hai"]),
    ("5.N3", BASE, ["yaad se Ramesh ko 500 udhaar likho"]),
    ("5.N4", EMPTY, ["Kochar ko 200 udhaar"]),
    # ---- round 6: names left by a real voice session ------------------------------------------------------------
    ("6.1", only(("ramesh", "credit", 340)), ["Ramish Ramesh ne 50 diye"]),
    ("6.2", only(("divakar", "credit", 100)), ["Diwa Kar ka 50 udhaar"]),
    ("6.3", only(("ramesh", "credit", 340)), ["Jamesh ka 50 udhaar"]),
    ("6.4", only(("tanishk", "credit", 100)), ["Tanishke ka 50 udhaar"]),
    # ---- round 7: third review ----------------------------------------------------------------------------------
    ("7.B1a", only(("ramesh", "credit", 340)), ["Ramesh ko 500 udhaar aur Vikram ko 200 udhaar", "haan"]),
    ("7.B1b", BASE, ["Vikram ko 500 udhaar aur Sunit ne 200 diye", "haan", "Sunita"]),
    ("7.B1c", BASE, ["Ramesh ne 500 diye Sunita 200", "ne diye", "haan"]),
    ("7.B2a", BASE, ["Ramesh ko 2026 mein 500 udhaar diya"]),
    ("7.B2b", BASE, ["Ramesh ne 200 diye 300 baaki hai"]),
    ("7.B2c", BASE, ["Ramesh ko 21 November ko 500 udhaar"]),
    ("7.B2d", BASE, ["Ramesh ko 10:30 pe 500 udhaar"]),
    ("7.B2e", BASE, ["Ramesh ko 1000 udhaar pe 50 byaj"]),
    ("7.B2f", BASE, ["Ramesh ko 340 rupaye 50 paise udhaar"]),
    ("7.B3", BASE, ["Sunita 200", "usko diye"]),
    ("7.B4a", only(("ramesh", "credit", 540), ("mohan das", "credit", 60)), ["Ramesh ne teen sau das diye"]),
    ("7.B4b", only(("ramesh", "credit", 540), ("sattar", "credit", 60)), ["Ramesh ne do sau sattar diye"]),
    ("7.B5a", BASE, ["Ramesh ko 340 udhaar", "usko 430 kar do", "haan"]),
    ("7.B5b", BASE, ["Ramesh ko 340 udhaar", "wo galat tha, 430 likho"]),
    ("7.B5c", BASE, ["Ramesh ne 200 diye", "usko 300 kar do"]),
    ("7.B6a", BASE, ["Ramesh ka 200 write off kar do"]),
    ("7.B6b", BASE, ["Ramesh ko 50 ka discount diya"]),
    ("7.B6c", BASE, ["Ramesh ka 100 udhaar", "aur 200 de do"]),
    ("7.B6d", BASE, ["Ramesh ko 200 advance diya"]),
    ("7.B7a", BASE, ["Ramesh ne 340 ka saaman liya, 300 diye, 40 udhaar likh do"]),
    ("7.B7b", BASE, ["Ramesh ne 500 ka saaman liya aur payment kar diya"]),
    ("7.B7c", BASE, ["Ramesh ko 500 udhaar diya tha wo aa gaya"]),
    ("7.B8a", BASE, ["Ramesh ko 340 ka gutkha diya", "nahi 300 jama"]),
    ("7.B8b", BASE, ["Ramesh ka 75000 udhaar", "nahi 7500 jama"]),
    ("7.B9", BASE, ["Ramesh ko 340 udhaar", "change karke 430 kar do"]),
    ("7.B10", BASE, ["Ramesh ko 340 udhaar", "Ramesh ko 340 udhaar", "nahi 430"]),
    ("7.S2a", only(("pinky", "credit", 430)), ["Pinky se 430 mil gaye"]),
    ("7.S2b", only(("gupta", "credit", 150)), ["Gupta ji ne 150 Google Pay kiya"]),
    ("7.S2c", only(("sharma", "credit", 2000)), ["Sharma ji ke do hazaar mein se paanch sau aa gaye"]),
    ("7.S3a", BASE, ["Sunita 200", "haan udhaar"]),
    ("7.S3b", EMPTY, ["Vikram ko 200 udhaar", "nahi banana"]),
    ("7.S4a", BASE, ["Ramesh ko 340 udhaar", "theek karo 430"]),
    ("7.S4b", BASE, ["wo wala 430 hai"]),
    ("7.S5", BASE, ["Ramesh ko 340 udhaar", "amount galat hai"]),
    ("7.S6", BASE, ["Ramesh ne poora de diya", "haan", "nahi 500"]),
    ("7.S7", BASE, ["Ramesh ko 340 udhaar", "Ramesh ka total", "nahi, 430"]),
    ("7.S8", BASE, ["500 udhaar", "Ramesh ka kal ka"]),
    ("7.S10", BASE, ["Ramesh ko teen sau, chalis udhaar"]),
    ("7.S11a", only(("pinky", "credit", 430)), ["पिंकी ने 100 दिए"]),
    ("7.S11b", only(("lakshmi", "credit", 900)), ["Laxmi ne 100 diye"]),
    ("7.S12", BASE, ["Ramesh ne 200 diye ab kitna baaki hai"]),
    ("7.S13a", only(("lakshmi", "credit", 900)), ["Lakshmi ko kitna dena hai"]),
    ("7.S13b", BASE, ["Ramesh ko 200 de do"]),
    ("7.S13c", BASE, ["Sunita ne Ramesh ke 200 diye"]),
    ("7.X1", EMPTY, ["Mohan ka 340 udhaar, kal 200 diya tha", "haan"]),
    # ---- round 8: live check of the published build (contract 1.17) ---------------------------------------------
    ("8.1a", PAIR, ["Ramesh ne 500 diye aur Mohan ne 200 diye", "haan"]),
    ("8.1b", {"seed": [("ramesh", "credit", 1030)], "customers": [("sunita", None)]},
     ["Ramesh ne 500 diye aur Sunita ne 200 diye", "haan"]),
    ("8.2a", PAIR, ["Ramesh ka 99000 udhaar aur Mohan ka 88000 udhaar", "haan", "haan"]),
    ("8.2b", PAIR, ["Ramesh ne 2000 diye aur Mohan ne 200 diye", "haan", "haan"]),
    ("8.3a", PAIR, ["Ramesh ka 200 udhaar aur Mohan ka baaki maaf kar do", "140", "haan"]),
    ("8.3b", PAIR, ["Ramesh ka 200 udhaar aur Mohan ke 50 maaf kar do", "haan"]),
    ("8.4a", BASE, ["Ramesh ka khata, Sunita ko pandrah sau udhaar", "Sunita"]),
    ("8.4b", EMPTY, ["Maya khata Shivakumar, Shivakumar ke khate mein pandrah sau rupaye udhaar likh diya.",
                     "Shivakumar", "haan"]),
    # ---- round 9: fourth review (contract 1.18) -----------------------------------------------------------------
    ("9.B1a", FOUR, ["Ramesh ne 200 ka saaman liya paise de diye"]),
    ("9.B1b", FOUR, ["Ramesh ne 200 ka saaman liya cash de diya"]),
    ("9.B1c", FOUR, ["Ramesh 200 ka saaman le gaya aur de gaya"]),
    ("9.B1d", FOUR, ["Ramesh ko 200 udhaar diye the, aaj de gaya"]),
    ("9.B1e", FOUR, ["Ramesh bought goods for 200 in cash"]),
    ("9.B2a", FOUR, ["Ramesh udhaar ke 200 de gaya"]),
    ("9.B2b", FOUR, ["Ramesh 200 udhaar de gaya"]),
    ("9.B3a", FOUR, ["Ramesh ke naam se 200 jama karo"]),
    ("9.B3b", FOUR, ["Ramesh ke naam 200 aaye"]),
    ("9.B3c", FOUR, ["Ramesh ke khate mein 200 payment likh do"]),
    ("9.B4a", FOUR, ["Vikram ko 500 udhaar", "haan bhai", "haan"]),
    ("9.B4b", FOUR, ["Vikram ko 500 udhaar", "yeah open it", "yes"]),
    ("9.B5a", FOUR, ["Ramesh ne 500 ka saaman liya 200 diye baaki udhaar", "udhaar", "haan"]),
    ("9.B5b", FOUR, ["Ramesh ne 500 ka saaman liya 300 baaki hai"]),
    ("9.B6a", FOUR, ["Ramesh also paid 200", "yes"]),
    ("9.B6b", FOUR, ["Ramesh ne 500 ka saaman liya, 200 udhaar rakha", "haan"]),
    ("9.B6c", FOUR, ["Ramesh paid 200 out of 500"]),
    ("9.B6d", FOUR, ["Ramesh ka 340 udhaar", "100 kam karo"]),
    ("9.B6e", FOUR, ["Ramesh ka 340 udhaar", "he took another 100"]),
    ("9.B8a", FOUR, ["Ramesh ka 340 udhaar", "Ramesh ka 430 likhna tha"]),
    ("9.B8b", FOUR, ["Ramesh ka 340 udhaar", "430 kar do"]),
    ("9.B8c", FOUR, ["Ramesh ka 340 udhaar", "sorry 430"]),
    ("9.B8d", FOUR, ["Ramesh ka 340 udhaar", "Ramesh ka 430 udhaar tha"]),
    ("9.B9a", FOUR, ["Ramesh ka udhaar 200 ho gaya"]),
    ("9.B9b", FOUR, ["Ramesh se 200 vasool karne hain"]),
    ("9.B9c", FOUR, ["Ramesh ka 200 udhaar likhna mat"]),
    ("9.B9d", FOUR, ["Ramesh ne 200 diye the kya aur Mohan ko 100 udhaar"]),
    ("9.B9e", FOUR, ["Ramesh ka 200 udhaar batao"]),
    ("9.B9f", FOUR, ["Ramesh ka 200 udhaar likh dena kal"]),
    ("9.B10a", FOUR, ["Ramesh paid 200 last night"]),
    ("9.B10b", FOUR, ["kal Ramesh ne 200 diye the aur Mohan ne bhi 100 diye the"]),
    ("9.S1a", FOUR, ["Mohan ne 100 diye aur 100 diye"]),
    ("9.S1b", FOUR, ["Mohan ka 400 maaf kar do"]),
    ("9.S1c", FOUR, ["Sunita ka 50 maaf kar do"]),
    ("9.S2", FOUR, ["Ramesh ka 200 udhaar", "Ramesh ka 200 udhaar", "Ramesh ka 200 udhaar"]),
    ("9.S3", {"seed": [("suresh", "credit", 500, 0, "chai wale"), ("suresh", "credit", 100, 0, "gali 4")],
              "customers": [("suresh", None)]}, ["Suresh ka 200 udhaar", "pehle wale"]),
    ("9.S4", {"seed": [("suresh", "credit", 500, 0, "chai wale"), ("suresh", "credit", 100, 0, "gali 4")],
              "customers": []}, ["Suresh ne poora de diya", "chai wale"]),
    ("9.S5a", FOUR, ["Ramesh ne 500 ka note diya, 200 kaate, 300 wapas kiye"]),
    ("9.S5b", FOUR, ["Ramesh ne 15 ko 200 diye"]),
    ("9.S5c", FOUR, ["Ramesh ko sath sau udhaar"]),
    ("9.S6a", FOUR, ["Geeta ne 1000 diye baaki chhod do"]),
    ("9.S6b", FOUR, ["Mohan ne 100 diye aur baaki maaf kar do"]),
    ("9.S7", FOUR, ["Ramesh ne 100 diye", "nahi Geeta ko 500 udhaar", "nahi"]),
    ("9.S8a", FOUR, ["Ramesh 200", "kal udhaar"]),
    ("9.S8b", FOUR, ["Rames ko 500 udhaar", "haan"]),
    ("9.S8c", FOUR, ["Ramesh ka 100 udhaar aur Mohan ka 100 udhaar", "100 nahi 150", "Mohan"]),
    ("9.S8d", FOUR, ["Ramesh ne jaldi se 200 diye aur Mohan ko 100 udhaar"]),
    ("9.S9a", FOUR, ["Ramesh took 300", "he paid 200"]),
    ("9.S9b", FOUR, ["Ramesh paid in full"]),
    ("9.S9c", FOUR, ["Ramesh paid 200 this morning"]),
    # ---- round 10: noise (contract 3.5). ("noisy", text) is a spoken turn whose audio measured as noisy ---------
    ("10.1a", FOUR, ["pandra sau udhaar likh do, mohan."]),
    ("10.1b", FOUR, [("noisy", "pandra sau udhaar likh do, mohan."), "nahi"]),
    ("10.2", FOUR, [("noisy", "Ramesh ka 340 udhaar"), "haan"]),
    ("10.3", FOUR, [("noisy", "Ramesh ka total")]),
    ("10.4", FOUR, ["Ramesh ka 340 udhaar", ("noisy", "nahi, 430")]),
    # ---- round 11: a sentence that is refused on its own, said while a question is open -----------------------
    ("11.1", FOUR, ["Ramesh ka 75000 udhaar", "Ramesh ka 200 udhaar nahi hai", "haan"]),
    ("11.2", FOUR, ["Ramesh ka teen chaar sau udhaar", "Ramesh ne 200 ka saaman liya paise de diye", "haan"]),
    ("11.3", FOUR, ["Ramesh ko udhaar", "Ramesh ko 200 dene hain"]),
    ("11.3b", FOUR, ["Ramesh ka teen chaar sau udhaar", "Wholesaler ko 5000 diye", "pehla"]),
    ("11.4", FOUR, ["Ramesh ka 340 udhaar", ("noisy", "nahi, 430"), "haan"]),
]


def say_noisy(shop: Shop, text: str):
    """One turn with the flag the server sets when the turn's audio was noisy (CONTRACT section 3.5)."""
    run_turn = shop.pipeline.run_turn
    shop.pipeline.run_turn = lambda state, transcript, **kw: run_turn(state, transcript, noisy=True, **kw)
    try:
        return shop.say(text)
    finally:
        shop.pipeline.run_turn = run_turn


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    wanted = [a for a in args if not a.startswith("-")]
    root = Path(tempfile.mkdtemp(prefix="fix_log_"))
    try:
        for cid, setup, turns in CASES:
            if wanted and not any(cid.startswith(p) for p in wanted):
                continue
            shop = Shop(root / cid.replace(".", "_"))
            try:
                for name, tags in setup.get("customers", []):
                    shop.customer(name, tags)
                if setup.get("seed"):
                    shop.seed(*setup["seed"])
                shop.new_session()
                print(f"## {cid}")
                for turn in turns:
                    if isinstance(turn, tuple) and turn[0] == W:
                        shop.wait(turn[1])
                        print(f"   (wait {turn[1]} s)")
                        continue
                    try:
                        if isinstance(turn, tuple):  # ("noisy", text): a spoken turn whose audio measured as noisy
                            print("   " + say_noisy(shop, turn[1]).describe() + "  (noisy turn)")
                        else:
                            print("   " + shop.say(turn).describe())
                    except Exception as exc:  # a crash is a finding: report it and go on
                        print(f"   {turn!r} -> RAISED {type(exc).__name__}")
            finally:
                shop.close()
    finally:
        shutil.rmtree(root, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
