"""Latency harness: replays scripted utterances through /ws/session and prints p50/p95 for every hop.

Starts the mock Gnani server and the app in-process (both on free 127.0.0.1 ports, a temporary database), so the
numbers show the cost of the app itself plus whatever delays are configured for the mock.

    cd server
    ../.venv/Scripts/python ../scripts/latency_harness.py --n 30 --stt-delay-ms 400 --tts-first-chunk-delay-ms 250
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import importlib
import json
import os
import statistics
import struct
import sys
import tempfile
import time
from pathlib import Path

SERVER_DIR = Path(__file__).resolve().parents[1] / "server"
sys.path.insert(0, str(SERVER_DIR))

import httpx  # noqa: E402
from websockets.asyncio.client import connect  # noqa: E402

from mock_gnani.testing import serve_app, start_mock  # noqa: E402

UTTERANCES = [
    "ramesh ka 340 udhaar",
    "sunita ne 500 diye",
    "mohan ko 200 udhaar",
    "nahi 430",
    "aur 200 payment mila",
    "ramesh ka total",
    "aaj ka hisaab batao",
    "geeta ko dedh sau udhaar",
]
HOPS = ["stt_final", "parse", "db", "tts_first_chunk", "end_to_first_audio", "gnani_stt_latency"]


def pcm_audio(ms: int = 600) -> bytes:
    """Audio as the page sends it: 8 frames of near-silence (pre-roll), the tone as speech, 9 frames of near-silence."""
    n = 16000 * ms // 1000
    tone = [2000 if (i // 40) % 2 else -2000 for i in range(n)]
    quiet = [20 if (i // 7) % 2 else -20 for i in range(512 * 8)]
    tail = [20 if (i // 7) % 2 else -20 for i in range(512 * 9)]
    samples = quiet + tone + tail
    return struct.pack(f"<{len(samples)}h", *samples)


def percentile(values: list[float], pct: float) -> float:
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round(pct / 100 * (len(ordered) - 1))))
    return ordered[index]


async def read_turn(ws, timeout: float = 15.0) -> dict:
    """Read until the turn's result, audio_end and timing have all arrived (or a silent turn's result)."""
    seen: dict = {"first_frame_at": None}
    end = time.perf_counter() + timeout
    while time.perf_counter() < end:
        raw = await asyncio.wait_for(ws.recv(), max(0.1, end - time.perf_counter()))
        if isinstance(raw, bytes):
            if seen["first_frame_at"] is None:
                seen["first_frame_at"] = time.perf_counter()
            continue
        msg = json.loads(raw)
        seen[msg["type"]] = msg
        if msg["type"] == "error":
            raise RuntimeError(f"server error: {msg}")
        if "result" in seen and "audio_end" in seen and "timing" in seen:
            return seen
        if "result" in seen and seen["result"].get("action") == "none":
            return seen
    raise TimeoutError("turn did not finish")


async def main(args) -> int:
    mock_url, stop_mock = await start_mock()
    tmp = tempfile.TemporaryDirectory()
    os.environ.update({
        "GNANI_BASE_URL": mock_url,
        "GNANI_API_KEY": "harness-key",
        "LEDGER_DB": os.path.join(tmp.name, "khata.db"),
        "LEDGER_KEY": base64.b64encode(b"h" * 32).decode(),
    })
    os.environ.pop("ACCESS_CODE", None)
    main_mod = importlib.import_module("app.main")
    app_url, stop_app = await serve_app(main_mod.app, lifespan="auto")
    samples: dict[str, list[float]] = {hop: [] for hop in HOPS}
    client_side: list[float] = []
    failures = 0
    try:
        async with httpx.AsyncClient(base_url=mock_url) as mock:
            await mock.post("/__mock/script", json={
                "stt_delay_ms": args.stt_delay_ms,
                "tts_first_chunk_delay_ms": args.tts_first_chunk_delay_ms,
                "tts_chunk_ms": args.tts_chunk_ms,
            })
            async with connect("ws" + app_url[4:] + "/ws/session", max_size=None) as ws:
                await ws.send(json.dumps({"type": "hello", "lang": "hi"}))
                await read_turn(ws)  # greeting
                audio = pcm_audio()
                for i in range(args.n):
                    text = UTTERANCES[i % len(UTTERANCES)]
                    await mock.post("/__mock/script", json={"transcripts": [text]})
                    await ws.send(json.dumps({"type": "start", "mode": "ptt"}))
                    for j in range(0, len(audio), 640):
                        await ws.send(audio[j:j + 640])
                        await asyncio.sleep(0.01)  # near real-time cadence, as from a browser
                    sent_end = time.perf_counter()
                    await ws.send(json.dumps({"type": "end"}))
                    turn = await read_turn(ws)
                    if "timing" not in turn:
                        failures += 1
                        continue
                    for hop in HOPS:
                        value = turn["timing"]["ms"].get(hop)
                        if value is not None:
                            samples[hop].append(float(value))
                    if turn["first_frame_at"] is not None:
                        client_side.append((turn["first_frame_at"] - sent_end) * 1000)
    finally:
        await stop_app()
        await stop_mock()
        tmp.cleanup()

    print(f"{args.n} utterances; mock: stt_delay={args.stt_delay_ms} ms, "
          f"tts_first_chunk={args.tts_first_chunk_delay_ms} ms, tts_chunk={args.tts_chunk_ms} ms")
    print(f"{'hop':<22}{'n':>5}{'p50 ms':>10}{'p95 ms':>10}")
    rows = dict(samples)
    rows["client end->first frame"] = client_side
    for hop, values in rows.items():
        if values:
            print(f"{hop:<22}{len(values):>5}{statistics.median(values):>10.1f}{percentile(values, 95):>10.1f}")
        else:
            print(f"{hop:<22}{0:>5}{'-':>10}{'-':>10}")
    e2e = samples["end_to_first_audio"]
    if e2e:
        verdict = "within" if percentile(e2e, 95) < 2000 else "over"
        print(f"end_to_first_audio p95 is {verdict} the 2000 ms target")
    return 1 if failures else 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--n", type=int, default=20, help="number of utterances to replay")
    parser.add_argument("--stt-delay-ms", type=int, default=300)
    parser.add_argument("--tts-first-chunk-delay-ms", type=int, default=200)
    parser.add_argument("--tts-chunk-ms", type=int, default=10)
    raise SystemExit(asyncio.run(main(parser.parse_args())))
