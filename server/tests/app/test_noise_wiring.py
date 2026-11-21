"""Noise handling wired into the session (CONTRACT 3.5): one TurnAudio per spoken turn, every frame passed on once
and in order before the commit, `limits.noisy` for a noisy turn, `timing.noise` for spoken turns only."""
from __future__ import annotations

import json
import random
import struct

import httpx
import pytest
import websockets

from app.config import Settings
from app.gnani.stt import SttResult
from app.main import create_app

from .conftest import fake_nw
from .test_review_fixes import running
from .test_session import hello, is_type, of, recv_until

FRAME = 1024
SAMPLES = FRAME // 2


def frame(amplitude: int, rnd: random.Random) -> bytes:
    """One 32 ms frame of noise-like samples at about `amplitude`."""
    return struct.pack(f"<{SAMPLES}h", *[max(-32767, min(32767, int(rnd.gauss(0, amplitude))))
                                          for _ in range(SAMPLES)])


def turn_frames(background: int, speech: int, seed: int = 1, pre: int = 8, speaking: int = 30) -> list[bytes]:
    """Pre-roll of background, then speech frames over the same background, then a short tail."""
    rnd = random.Random(seed)
    out = [frame(background, rnd) for _ in range(pre)]
    out += [frame(int((background ** 2 + speech ** 2) ** 0.5), rnd) for _ in range(speaking)]
    out += [frame(background, rnd) for _ in range(6)]
    return out


class RecordingStt:
    """A speech client that records what it receives: frames in order, then "COMMIT" at end_turn."""

    def __init__(self, text: str = "ramesh ka 340 udhaar"):
        self.log: list = []
        self.text = text
        self.turns = 0

    def warm(self):
        pass

    async def begin_turn(self, on_event=None):
        self.turns += 1
        self.log.append(("BEGIN", self.turns))

    async def send_audio(self, pcm: bytes):
        self.log.append(pcm)

    async def end_turn(self):
        self.log.append("COMMIT")
        return SttResult(text=self.text, segments=[self.text], latency_ms=100.0, heard=True)

    async def close(self):
        pass

    def frames_of_turn(self, n: int) -> list[bytes]:
        start = self.log.index(("BEGIN", n))
        end = self.log.index("COMMIT", start)
        return [x for x in self.log[start + 1:end] if isinstance(x, bytes)]

    def after_commit(self, n: int) -> list[bytes]:
        start = self.log.index(("BEGIN", n))
        end = self.log.index("COMMIT", start)
        nxt = next((i for i in range(end, len(self.log)) if isinstance(self.log[i], tuple)), len(self.log))
        return [x for x in self.log[end + 1:nxt] if isinstance(x, bytes)]


@pytest.fixture
def stt():
    return RecordingStt()


async def spoken_turn(ws, frames, turn_id, chunk=FRAME):
    data = b"".join(frames)
    await ws.send(json.dumps({"type": "start", "mode": "ptt"}))
    for i in range(0, len(data), chunk):
        await ws.send(data[i:i + chunk])
    await ws.send(json.dumps({"type": "end"}))
    msgs = await recv_until(ws, is_type("audio_end", turn_id=turn_id))
    return of(msgs, "result")[0], of(msgs, "timing")[0]


def app_for(settings, parser, stt, fake_gnani):
    settings.gnani_base_url = fake_gnani.base_url
    return create_app(settings, parse=parser, number_to_words=fake_nw, stt_factory=lambda s, kt: stt)


async def test_every_frame_reaches_speech_once_in_order_before_the_commit(settings, parser, stt, fake_gnani):
    frames = turn_frames(300, 6000)
    async with running(app_for(settings, parser, stt, fake_gnani)) as (_, url):
        async with websockets.connect(url) as ws:
            await hello(ws)
            await spoken_turn(ws, frames, 1)
    sent = stt.frames_of_turn(1)
    assert len(sent) == len(frames) and [len(f) for f in sent] == [FRAME] * len(frames)
    assert stt.after_commit(1) == []  # nothing arrives after the commit
    # Frames kept by the gate are byte-identical; frames turned down are the same frame at a quarter.
    for got, want in zip(sent, frames):
        assert got == want or all(abs(a * 4 - b) <= 4 for a, b in zip(struct.unpack(f"<{SAMPLES}h", got)[:20],
                                                                       struct.unpack(f"<{SAMPLES}h", want)[:20]))


async def test_with_noise_trim_off_the_frames_are_byte_identical(settings, parser, stt, fake_gnani):
    settings.noise_trim = False
    frames = turn_frames(3000, 3500)
    async with running(app_for(settings, parser, stt, fake_gnani)) as (_, url):
        async with websockets.connect(url) as ws:
            await hello(ws)
            _, timing = await spoken_turn(ws, frames, 1)
            await spoken_turn(ws, frames, 2, chunk=640)  # another client's chunk size: the same bytes, in order
    assert stt.frames_of_turn(1) == frames
    assert b"".join(stt.frames_of_turn(2)) == b"".join(frames)
    assert timing["ms"]["noise"]["turned_down_ms"] == 0


async def test_a_noisy_turn_is_reported_and_reaches_the_parser_flagged(settings, parser, stt, fake_gnani):
    async with running(app_for(settings, parser, stt, fake_gnani)) as (http, url):
        async with websockets.connect(url) as ws:
            await hello(ws)
            result, timing = await spoken_turn(ws, turn_frames(4000, 4000, seed=2), 1)
            assert timing["ms"]["noise"]["noisy"] is True and timing["ms"]["noise"]["separation_db"] < 12
            assert set(timing["ms"]["noise"]) == {"separation_db", "noisy", "turned_down_ms"}
            assert parser.calls[-1]["ctx"]["limits"]["noisy"] is True
            _, clean = await spoken_turn(ws, turn_frames(100, 8000, seed=3), 2)
            assert clean["ms"]["noise"]["noisy"] is False and clean["ms"]["noise"]["separation_db"] >= 12
            assert "noisy" not in parser.calls[-1]["ctx"]["limits"]  # two turns do not share state
            await ws.send(json.dumps({"type": "text", "text": "ramesh ka total"}))
            typed = of(await recv_until(ws, is_type("audio_end", turn_id=3)), "timing")[0]
            assert "noise" not in typed["ms"] and "noisy" not in parser.calls[-1]["ctx"]["limits"]
        async with httpx.AsyncClient() as c:
            assert (await c.get(http + "/api/metrics")).json()["noisy_turns"] == 1


async def test_noise_confirm_off_never_flags(settings, parser, stt, fake_gnani):
    settings.noise_confirm_db = 0
    async with running(app_for(settings, parser, stt, fake_gnani)) as (_, url):
        async with websockets.connect(url) as ws:
            await hello(ws)
            _, timing = await spoken_turn(ws, turn_frames(4000, 4000, seed=2), 1)
    assert timing["ms"]["noise"]["noisy"] is False and "noisy" not in parser.calls[-1]["ctx"]["limits"]


async def test_cancel_and_barge_in_start_the_next_turn_fresh(settings, parser, stt, fake_gnani):
    noisy_frames = turn_frames(4000, 4000, seed=4)
    async with running(app_for(settings, parser, stt, fake_gnani)) as (_, url):
        async with websockets.connect(url) as ws:
            await hello(ws)
            # A cancelled press: its audio never reaches a later turn.
            await ws.send(json.dumps({"type": "start", "mode": "ptt"}))
            for f in noisy_frames[:12]:
                await ws.send(f)
            await ws.send(json.dumps({"type": "cancel"}))
            await recv_until(ws, is_type("result"))
            clean = turn_frames(100, 8000, seed=5)
            _, timing = await spoken_turn(ws, clean, 2)
            assert timing["ms"]["noise"]["noisy"] is False
            got = stt.frames_of_turn(2)
            assert len(got) == len(clean) and got[15] == clean[15]  # this turn's own audio, a frame inside the gate
            # A barge-in: a new press while the previous one is still being sent starts its own measurement.
            await ws.send(json.dumps({"type": "start", "mode": "ptt"}))
            for f in noisy_frames[:5]:
                await ws.send(f)
            _, timing = await spoken_turn(ws, clean, 4)
            assert len(stt.frames_of_turn(4)) == len(clean) and timing["ms"]["noise"]["noisy"] is False


def test_noise_settings_from_env():
    s = Settings.from_env({"NOISE_TRIM": "0", "NOISE_TRIM_DB": "18.5", "NOISE_CONFIRM_DB": "0"})
    assert s.noise_trim is False and s.noise_trim_db == 18.5 and s.noise_confirm_db == 0
    d = Settings.from_env({})
    assert d.noise_trim is True and d.noise_trim_db == 16.0 and d.noise_confirm_db == 14.0


def test_run_turn_flag_is_per_turn(pipeline, parser, state):
    state.disclosed = True
    pipeline.run_turn(state, "ramesh ka 340 udhaar", noisy=True)
    assert parser.calls[-1]["ctx"]["limits"]["noisy"] is True
    pipeline.run_turn(state, "ramesh ka total")
    assert "noisy" not in parser.calls[-1]["ctx"]["limits"]
    assert pipeline.ledger.metrics()["noisy_turns"] == 1
