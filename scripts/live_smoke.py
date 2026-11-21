"""Live smoke test against the real Gnani API. It uses the key in .env and real credits; the automated tests use the mock.

Run from the repository root:  server/../.venv/Scripts/python scripts/live_smoke.py
(or from server/ with `../.venv/Scripts/python ../scripts/live_smoke.py`).

1. Synthesises three phrases with Timbre v3.0 as 16 kHz raw PCM.
2. Streams each phrase to Prisma v3.0 in 1,024-byte frames at real-time cadence, once per format (verbatim,
   transcribe, codemix, transliterate), sends commit, and records the transcript, Gnani's `latency`, and the time from
   commit to transcript.
3. Prints a summary table, including the TTS time to first chunk.

The API key is read through app.config and is never printed.
"""
from __future__ import annotations

import asyncio
import dataclasses
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "server"))

from app.config import get_settings  # noqa: E402
from app.gnani.stt import FRAME_BYTES, SttClient  # noqa: E402
from app.gnani.tts import TtsClient  # noqa: E402

PHRASES = ["रमेश का तीन सौ चालीस उधार", "Ramesh ka three forty udhaar", "सुनीता ने डेढ़ सौ दिए"]
FORMATS = ["verbatim", "transcribe", "codemix", "transliterate"]
FRAME_S = FRAME_BYTES / 2 / 16000  # 32 ms


async def synthesise(settings, text: str) -> tuple[bytes, float | None]:
    """Return (16 kHz PCM, milliseconds to the first chunk). The cache is bypassed with a temporary directory."""
    cfg = dataclasses.replace(settings, tts_sample_rate=16000)
    client = TtsClient(cfg, cache_dir=Path(tempfile.mkdtemp()), memory_cache={})
    pcm = bytearray()
    first = None
    t0 = time.perf_counter()
    try:
        async for chunk in client.synth(text):
            if first is None:
                first = (time.perf_counter() - t0) * 1000
            pcm.extend(chunk)
    finally:
        await client.close()
    return bytes(pcm), first


async def transcribe(settings, fmt: str, pcm: bytes) -> dict:
    cfg = dataclasses.replace(settings, stt_format=fmt)
    client = SttClient(cfg, lambda: ["ramesh", "sunita"])
    await client.begin_turn()
    start = time.perf_counter()
    for i in range(0, len(pcm), FRAME_BYTES):
        await client.send_audio(pcm[i:i + FRAME_BYTES])
        await asyncio.sleep(FRAME_S)
    t_commit = time.perf_counter()
    result = await client.end_turn()
    t_done = time.perf_counter()
    await client.close()
    return {"text": result.text, "error": result.error, "gnani_latency": result.latency_ms,
            "commit_to_transcript_ms": (t_done - t_commit) * 1000, "stream_s": t_commit - start}


async def main() -> int:
    settings = get_settings()
    if not settings.gnani_api_key:
        print("GNANI_API_KEY is not set (put it in .env).")
        return 1
    print(f"Gnani base URL: {settings.gnani_base_url}   voice: {settings.tts_voice}")
    rows = []
    for phrase in PHRASES:
        print(f"\nPhrase: {phrase}")
        try:
            pcm, first_ms = await synthesise(settings, phrase)
        except Exception as exc:
            print(f"  TTS failed: {type(exc).__name__}: {exc}")
            continue
        print(f"  TTS: {len(pcm)} bytes, first chunk {first_ms:.0f} ms" if first_ms else "  TTS: no audio")
        for fmt in FORMATS:
            r = await transcribe(settings, fmt, pcm)
            print(f"  [{fmt}] {r['text']!r} error={r['error']} gnani_latency={r['gnani_latency']} "
                  f"commit_to_transcript={r['commit_to_transcript_ms']:.0f} ms")
            rows.append((phrase, fmt, r, first_ms))
    print("\nSummary")
    print(f"{'phrase':34} {'format':14} {'gnani ms':>9} {'commit->txt ms':>15} {'tts 1st ms':>11}  transcript")
    for phrase, fmt, r, first_ms in rows:
        lat = "-" if r["gnani_latency"] is None else f"{r['gnani_latency']:.0f}"
        tts = "-" if first_ms is None else f"{first_ms:.0f}"
        print(f"{phrase[:34]:34} {fmt:14} {lat:>9} {r['commit_to_transcript_ms']:>15.0f} {tts:>11}  {r['text']}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
