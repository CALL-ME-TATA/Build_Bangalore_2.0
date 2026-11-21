"""Replay recorded audio through a running server and measure accuracy and timing. Live use only: tests never run it.

Play each WAV of a manifest through /ws/session exactly as the browser does (hello, start, 1,024-byte frames every
32 ms, end) and report exact-amount accuracy, direction accuracy, customer match, silent wrong saves, how many turns
asked a question, and the per-stage timings of the `timing` message (median and p95).

    cd server
    ../.venv/Scripts/python ../scripts/replay_audio.py manifest.jsonl --url ws://127.0.0.1:8000/ws/session

A manifest line is JSON, one per file:
    {"wav": "clips/ramesh_340.wav", "expect": {"customer": "ramesh", "kind": "credit", "amount": 340, "date_offset": 0}}
    {"wav": "clips/hello.wav", "expect_status": "rejected"}
`wav` is relative to the manifest. `expect_status` is ok, needs_clarification or rejected.

Noisy copies for robustness checks (white, pink and babble noise at 20, 10 and 5 dB SNR):
    ../.venv/Scripts/python ../scripts/replay_audio.py --make-noisy clips/ [--out clips/noisy] [--snr 20 10 5]
The folder's manifest.jsonl, when present, gives the expectations that the noisy copies inherit.

Only the standard library is used for audio work (wave, struct, random, math).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import math
import random
import statistics
import struct
import sys
import time
import wave
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

SAMPLE_RATE = 16000
FRAME_BYTES = 1024          # 512 samples
FRAME_S = 0.032
INT16_MAX = 32767
STAGES = ["stt_final", "parse", "db", "tts_first_chunk", "end_to_first_audio", "gnani_stt_latency"]
NOISE_KINDS = ("white", "pink", "babble")


# ---- audio helpers (pure) -----------------------------------------------------------------------------------------

def read_wav(path: Path, target_rate: int = SAMPLE_RATE) -> list[int]:
    """Samples of a 16-bit WAV as mono ints at `target_rate` (stereo is averaged, other rates are resampled)."""
    with wave.open(str(path), "rb") as w:
        if w.getsampwidth() != 2:
            raise ValueError(f"{path}: only 16-bit WAV files are supported")
        channels, rate, n = w.getnchannels(), w.getframerate(), w.getnframes()
        raw = w.readframes(n)
    values = struct.unpack(f"<{len(raw) // 2}h", raw)
    if channels > 1:
        values = tuple(sum(values[i:i + channels]) // channels for i in range(0, len(values) - channels + 1, channels))
    return resample(list(values), rate, target_rate)


def write_wav(path: Path, samples: list[int], rate: int = SAMPLE_RATE) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    clipped = [max(-INT16_MAX - 1, min(INT16_MAX, int(s))) for s in samples]
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(struct.pack(f"<{len(clipped)}h", *clipped))


def resample(samples: list[int], rate: int, target: int) -> list[int]:
    """Linear resampling; returns the input unchanged when the rates match."""
    if rate == target or not samples:
        return samples
    n_out = max(1, int(len(samples) * target / rate))
    out = []
    for i in range(n_out):
        pos = i * rate / target
        j = int(pos)
        frac = pos - j
        a = samples[min(j, len(samples) - 1)]
        b = samples[min(j + 1, len(samples) - 1)]
        out.append(int(a + (b - a) * frac))
    return out


def rms(samples: list[float]) -> float:
    return math.sqrt(sum(s * s for s in samples) / len(samples)) if samples else 0.0


def white_noise(n: int, rng: random.Random) -> list[float]:
    return [rng.uniform(-1.0, 1.0) for _ in range(n)]


def pink_noise(n: int, rng: random.Random) -> list[float]:
    """Pink (1/f) noise from white noise with Paul Kellet's filter."""
    b0 = b1 = b2 = b3 = b4 = b5 = b6 = 0.0
    out = []
    for _ in range(n):
        white = rng.uniform(-1.0, 1.0)
        b0 = 0.99886 * b0 + white * 0.0555179
        b1 = 0.99332 * b1 + white * 0.0750759
        b2 = 0.96900 * b2 + white * 0.1538520
        b3 = 0.86650 * b3 + white * 0.3104856
        b4 = 0.55000 * b4 + white * 0.5329522
        b5 = -0.7616 * b5 - white * 0.0168980
        out.append(b0 + b1 + b2 + b3 + b4 + b5 + b6 + white * 0.5362)
        b6 = white * 0.115926
    return out


def babble_noise(others: list[list[int]], n: int, rng: random.Random, voices: int = 4) -> list[float]:
    """Babble: shifted copies of other recordings summed. Falls back to white noise with nothing to sum."""
    pool = [o for o in others if o]
    if not pool:
        return white_noise(n, rng)
    out = [0.0] * n
    for _ in range(voices):
        clip = rng.choice(pool)
        shift = rng.randrange(len(clip))
        for i in range(n):
            out[i] += clip[(i + shift) % len(clip)]
    return out


def mix_at_snr(signal: list[int], noise: list[float], snr_db: float) -> list[int]:
    """`signal` plus `noise` scaled so that rms(signal) / rms(scaled noise) equals the SNR. The noise is repeated or
    cut to the signal's length. The result is clipped to 16 bits."""
    if not signal:
        return []
    if not noise:
        return list(signal)
    noise = [noise[i % len(noise)] for i in range(len(signal))]
    sig_rms, noise_rms = rms(signal), rms(noise)
    if noise_rms == 0 or sig_rms == 0:
        return list(signal)
    gain = sig_rms / (noise_rms * 10 ** (snr_db / 20))
    return [max(-INT16_MAX - 1, min(INT16_MAX, int(round(s + gain * x)))) for s, x in zip(signal, noise)]


def measured_snr_db(signal: list[int], mixed: list[int]) -> float:
    """SNR of a mix against its clean signal, from the difference."""
    diff = [m - s for m, s in zip(mixed, signal)]
    return 20 * math.log10(rms(signal) / rms(diff)) if rms(diff) else float("inf")


def make_noisy(folder: Path, out: Path, snrs: list[int], seed: int = 1) -> list[dict]:
    """Write noisy copies of every WAV in `folder` into `out` and a manifest there. Returns the manifest entries."""
    rng = random.Random(seed)
    wavs = sorted(p for p in folder.glob("*.wav"))
    clips = {p: read_wav(p) for p in wavs}
    expect = {}
    source_manifest = folder / "manifest.jsonl"
    if source_manifest.exists():
        for entry in read_manifest(source_manifest):
            expect[Path(entry["wav"]).name] = {k: v for k, v in entry.items() if k != "wav"}
    entries = []
    for p, samples in clips.items():
        others = [c for q, c in clips.items() if q != p]
        for kind in NOISE_KINDS:
            for snr in snrs:
                if kind == "white":
                    noise = white_noise(len(samples), rng)
                elif kind == "pink":
                    noise = pink_noise(len(samples), rng)
                else:
                    noise = babble_noise(others, len(samples), rng)
                name = f"{p.stem}_{kind}{snr}dB.wav"
                write_wav(out / name, mix_at_snr(samples, noise, snr))
                entries.append({"wav": name, **expect.get(p.name, {}), "noise": kind, "snr_db": snr})
    out.mkdir(parents=True, exist_ok=True)
    (out / "manifest.jsonl").write_text(
        "\n".join(json.dumps(e, ensure_ascii=False) for e in entries) + ("\n" if entries else ""), encoding="utf-8")
    return entries


# ---- manifest and metrics (pure) --------------------------------------------------------------------------------

def read_manifest(path: Path) -> list[dict]:
    entries = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            entry = json.loads(line)
            if "wav" not in entry:
                raise ValueError(f"manifest line without `wav`: {line}")
            entries.append(entry)
    return entries


def new_entries(result: dict) -> list[dict]:
    """The entries a turn created or kept: reversed ones (the old side of an amend, an undo) are left out."""
    return [e for e in result.get("entries") or [] if not e.get("reversed")]


def percentile(values: list[float], pct: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, max(0, round(pct / 100 * (len(ordered) - 1))))]


def judge(record: dict, today: date) -> dict:
    """Compare one turn with its expectation. `record` has `entry` (manifest line) and `result` (result message)."""
    entry, result = record["entry"], record["result"]
    expect = entry.get("expect")
    status = result.get("status")
    saved = new_entries(result) if result.get("action") in ("append", "amend") and status == "ok" else []
    out = {"wav": entry["wav"], "status": status, "asked": status == "needs_clarification", "amount": None,
           "kind": None, "customer": None, "date": None, "silent_wrong_save": False}
    if "expect_status" in entry:
        out["status_ok"] = status == entry["expect_status"]
        if entry["expect_status"] != "ok" and saved:
            out["silent_wrong_save"] = True
    if expect:
        first = saved[0] if saved else None
        if "amount" in expect:
            out["amount"] = bool(first) and first.get("amount") == expect["amount"]
        if "kind" in expect:
            out["kind"] = bool(first) and first.get("kind") == expect["kind"]
        if "customer" in expect:
            name = ((first or {}).get("customer") or {}).get("display", "")
            out["customer"] = bool(first) and name.lower() == str(expect["customer"]).lower()
        if "date_offset" in expect:
            want = date.fromordinal(today.toordinal() - int(expect["date_offset"])).isoformat()
            out["date"] = bool(first) and first.get("date") == want
        wrong = [f for f in ("amount", "kind", "customer", "date") if out[f] is False]
        if saved and wrong:
            out["silent_wrong_save"] = True
    return out


def summarise(judged: list[dict], timings: list[dict]) -> dict:
    def rate(key: str) -> tuple[int, int]:
        stated = [j[key] for j in judged if j.get(key) is not None]
        return sum(1 for v in stated if v), len(stated)

    stage_stats = {}
    for stage in STAGES:
        values = [float(t[stage]) for t in timings if t.get(stage) is not None]
        stage_stats[stage] = (statistics.median(values), percentile(values, 95), len(values)) if values else None
    return {
        "turns": len(judged), "amount": rate("amount"), "direction": rate("kind"), "customer": rate("customer"),
        "date": rate("date"), "status": rate("status_ok"),
        "silent_wrong_saves": sum(1 for j in judged if j["silent_wrong_save"]),
        "asked": sum(1 for j in judged if j["asked"]), "stages": stage_stats,
    }


def format_summary(s: dict) -> str:
    def pct(pair):
        return f"{pair[0]}/{pair[1]} ({100 * pair[0] / pair[1]:.1f}%)" if pair[1] else "n/a"

    lines = [
        f"turns                  {s['turns']}",
        f"exact amount           {pct(s['amount'])}",
        f"direction              {pct(s['direction'])}",
        f"customer match         {pct(s['customer'])}",
        f"date                   {pct(s['date'])}",
        f"expected status        {pct(s['status'])}",
        f"silent wrong saves     {s['silent_wrong_saves']}",
        f"turns that asked       {s['asked']}",
        "", f"{'stage':<22}{'n':>5}{'median ms':>11}{'p95 ms':>9}",
    ]
    for stage, stats in s["stages"].items():
        lines.append(f"{stage:<22}{stats[2]:>5}{stats[0]:>11.1f}{stats[1]:>9.1f}" if stats
                     else f"{stage:<22}{0:>5}{'-':>11}{'-':>9}")
    return "\n".join(lines)


# ---- live replay ------------------------------------------------------------------------------------------------

def frames(samples: list[int]) -> list[bytes]:
    """1,024-byte frames; the last one is padded with silence."""
    raw = struct.pack(f"<{len(samples)}h", *samples)
    out = [raw[i:i + FRAME_BYTES] for i in range(0, len(raw), FRAME_BYTES)]
    if out and len(out[-1]) < FRAME_BYTES:
        out[-1] = out[-1] + b"\x00" * (FRAME_BYTES - len(out[-1]))
    return out


async def read_turn(ws, timeout: float = 20.0) -> dict:
    """Read until the turn's result is in and its audio and timing are done (or it has no audio)."""
    seen: dict = {}
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        raw = await asyncio.wait_for(ws.recv(), max(0.1, end - time.monotonic()))
        if isinstance(raw, bytes):
            continue
        msg = json.loads(raw)
        seen[msg["type"]] = msg
        if "result" in seen:
            if seen["result"].get("action") == "none":
                return seen
            if "audio_end" in seen and "timing" in seen:
                return seen
            if msg["type"] == "state" and msg.get("state") == "idle":
                return seen
    raise TimeoutError("turn did not finish")


async def replay(args: argparse.Namespace) -> int:
    from websockets.asyncio.client import connect

    manifest = Path(args.manifest)
    entries = read_manifest(manifest)
    today = args.today or datetime.now(ZoneInfo("Asia/Kolkata")).date()
    records, timings = [], []
    async with connect(args.url, max_size=None) as ws:
        hello = {"type": "hello", "lang": args.lang}
        if args.access_code:
            hello["access_code"] = args.access_code
        await ws.send(json.dumps(hello))
        await read_turn(ws)  # greeting
        for entry in entries:
            samples = read_wav(manifest.parent / entry["wav"])
            await ws.send(json.dumps({"type": "start", "mode": "ptt"}))
            t0 = time.monotonic()
            for i, frame in enumerate(frames(samples)):
                await ws.send(frame)
                delay = t0 + i * FRAME_S / args.speed - time.monotonic()
                if delay > 0:
                    await asyncio.sleep(delay)
            await ws.send(json.dumps({"type": "end"}))
            try:
                turn = await read_turn(ws)
            except TimeoutError:
                print(f"{entry['wav']}: no reply within 20 s", file=sys.stderr)
                continue
            records.append({"entry": entry, "result": turn["result"]})
            if "timing" in turn:
                timings.append(turn["timing"]["ms"])
            if args.verbose:
                r = turn["result"]
                print(f"{entry['wav']}: {r.get('status')}/{r.get('action')} {r.get('reply_text')}")
    summary = summarise([judge(r, today) for r in records], timings)
    print(format_summary(summary))
    return 1 if summary["silent_wrong_saves"] else 0


def main(argv: list[str] | None = None) -> int:
    # Replies hold the rupee sign and Devanagari; a redirected Windows console would otherwise fail to encode them.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("manifest", nargs="?", help="manifest JSONL to replay")
    ap.add_argument("--url", default="ws://127.0.0.1:8000/ws/session")
    ap.add_argument("--access-code", default=None)
    ap.add_argument("--lang", default="hi", choices=["hi", "en"])
    ap.add_argument("--speed", type=float, default=1.0, help="1.0 plays at real time; 4.0 four times faster")
    ap.add_argument("--today", type=date.fromisoformat, default=None, help="shop date for date_offset (default: IST today)")
    ap.add_argument("--verbose", action="store_true")
    ap.add_argument("--make-noisy", metavar="DIR", help="write noisy copies of the WAVs in DIR and a manifest")
    ap.add_argument("--out", help="output folder for --make-noisy (default: DIR/noisy)")
    ap.add_argument("--snr", type=int, nargs="+", default=[20, 10, 5])
    ap.add_argument("--seed", type=int, default=1)
    args = ap.parse_args(argv)
    if args.make_noisy:
        folder = Path(args.make_noisy)
        out = Path(args.out) if args.out else folder / "noisy"
        entries = make_noisy(folder, out, args.snr, args.seed)
        print(f"wrote {len(entries)} noisy files and {out / 'manifest.jsonl'}")
        return 0
    if not args.manifest:
        ap.error("a manifest is required unless --make-noisy is given")
    return asyncio.run(replay(args))


if __name__ == "__main__":
    sys.exit(main())
