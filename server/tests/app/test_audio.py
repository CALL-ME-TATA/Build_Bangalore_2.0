"""Tests for app.audio: measuring and the foreground gate of one spoken turn (CONTRACT section 3.5)."""
from __future__ import annotations

import array
import math
import random
import time

import pytest

from app.audio import GIVE_UP, HANG, LOOK, TurnAudio

N = 512  # samples per frame
BYTES = N * 2


def _pack(samples) -> bytes:
    a = array.array("h", [max(-32768, min(32767, int(round(s)))) for s in samples])
    return a.tobytes()


def noise_frame(rng: random.Random, rms: float) -> bytes:
    return _pack(rng.gauss(0.0, rms) for _ in range(N))


def tone_frame(rms: float, phase: int) -> bytes:
    amp = rms * math.sqrt(2)
    return _pack(amp * math.sin(2 * math.pi * 220.0 * (phase * N + i) / 16000) for i in range(N))


def mixed_frame(rng: random.Random, speech_rms: float, bg_rms: float, tone: bool, phase: int) -> bytes:
    """A speech frame: the speech component plus the background, at the combined level."""
    bg = [rng.gauss(0.0, bg_rms) for _ in range(N)]
    if tone:
        amp = speech_rms * math.sqrt(2)
        sp = [amp * math.sin(2 * math.pi * 220.0 * (phase * N + i) / 16000) for i in range(N)]
    else:
        sp = [rng.gauss(0.0, speech_rms) for _ in range(N)]
    return _pack(a + b for a, b in zip(sp, bg))


def build_turn(*, lead=12, bursts=(30,), gaps=(), tail=30, bg_rms=100.0, speech_rms=3000.0,
               tone=False, fluct=0.0, seed=1):
    """Frames of a turn plus the index ranges (start, end inclusive) of the bursts.

    `fluct` makes the background level wander per frame by up to that fraction.
    """
    rng = random.Random(seed)

    def bg_level() -> float:
        return bg_rms * (1.0 + rng.uniform(-fluct, fluct))

    frames: list[bytes] = []
    spans: list[tuple[int, int]] = []
    for _ in range(lead):
        frames.append(noise_frame(rng, bg_level()))
    for k, length in enumerate(bursts):
        start = len(frames)
        for j in range(length):
            frames.append(mixed_frame(rng, speech_rms, bg_level(), tone, len(frames)))
        spans.append((start, len(frames) - 1))
        if k < len(gaps):
            for _ in range(gaps[k]):
                frames.append(noise_frame(rng, bg_level()))
    for _ in range(tail):
        frames.append(noise_frame(rng, bg_level()))
    return frames, spans


def run(frames, **kw):
    t = TurnAudio(**kw)
    out: list[bytes] = []
    for f in frames:
        out += t.push(f)
    out += t.flush()
    return out, t.stats()


def quarter(frame: bytes) -> bytes:
    a = array.array("h")
    a.frombytes(frame)
    return array.array("h", [int(x * 0.25) for x in a]).tobytes()


def is_quarter(src: bytes, out: bytes) -> bool:
    return out == quarter(src)


def expected_sep(speech_rms: float, bg_rms: float, tail: int) -> float:
    total = 10 * math.log10(speech_rms ** 2 + bg_rms ** 2 + 1)
    bg = 10 * math.log10(bg_rms ** 2 + 1)
    return total - bg - 0.06 * tail


# --- separation estimate -------------------------------------------------------------------------------------------

@pytest.mark.parametrize("speech,bg,tone,fluct", [
    (3000.0, 100.0, False, 0.0),
    (3000.0, 100.0, True, 0.0),
    (1500.0, 300.0, False, 0.0),
    (3000.0, 300.0, False, 0.25),
    (2000.0, 50.0, True, 0.25),
    (4000.0, 1000.0, False, 0.0),
])
def test_separation_estimate_close_to_construction(speech, bg, tone, fluct):
    tail = 20
    frames, _ = build_turn(speech_rms=speech, bg_rms=bg, tone=tone, fluct=fluct, tail=tail)
    _, stats = run(frames)
    assert abs(stats["separation_db"] - expected_sep(speech, bg, tail)) < 3.0
    assert stats["separation_db"] == round(stats["separation_db"], 1)


# --- gate behaviour ------------------------------------------------------------------------------------------------

def test_clear_separation_turns_down_lead_in_and_tail_only():
    frames, [(start, end)] = build_turn(lead=20, bursts=(30,), tail=40)
    out, stats = run(frames)
    assert len(out) == len(frames)
    assert all(len(o) == len(f) for o, f in zip(out, frames))
    # the burst, byte for byte
    for i in range(start, end + 1):
        assert out[i] == frames[i], i
    # the lead-in, apart from the frames just before the burst
    for i in range(0, start - LOOK):
        assert is_quarter(frames[i], out[i]), i
    # the tail after the hang
    for i in range(end + 1 + HANG, len(frames)):
        assert is_quarter(frames[i], out[i]), i
    assert stats["turned_down_ms"] >= 32 * ((start - LOOK) + (len(frames) - (end + 1 + HANG)))
    assert stats["turned_down_ms"] % 32 == 0
    assert stats["frames"] == len(frames)
    assert stats["noisy"] is False


def test_output_is_input_delayed_by_look_until_flush():
    frames, _ = build_turn(lead=20, bursts=(30,), tail=20)
    t = TurnAudio(trim=False)
    emitted: list[bytes] = []
    for i, f in enumerate(frames):
        got = t.push(f)
        emitted += got
        assert len(emitted) == max(0, i + 1 - LOOK)
    assert emitted == frames[: len(frames) - LOOK]
    rest = t.flush()
    assert emitted + rest == frames
    assert t.flush() == []


def test_push_plus_flush_returns_every_frame_once_with_gating():
    frames, _ = build_turn()
    out, _ = run(frames)
    assert len(out) == len(frames)
    for f, o in zip(frames, out):
        assert o == f or is_quarter(f, o)


def test_short_pause_inside_speech_is_not_turned_down():
    frames, spans = build_turn(lead=12, bursts=(20, 20), gaps=(HANG - 6,), tail=30)
    out, _ = run(frames)
    (s1, e1), (s2, e2) = spans
    for i in range(s1, e2 + 1):
        assert out[i] == frames[i], i


def test_long_pause_is_turned_down_after_the_hang():
    frames, spans = build_turn(lead=12, bursts=(20, 20), gaps=(HANG + 10,), tail=30)
    out, _ = run(frames)
    (s1, e1), (s2, e2) = spans
    assert is_quarter(frames[e1 + 1 + HANG + 2], out[e1 + 1 + HANG + 2])
    for i in range(s2, e2 + 1):
        assert out[i] == frames[i], i


def test_weak_separation_at_first_opening_passes_everything_after():
    # speech 10 dB over a 60 dB background: opens, but below the 16 dB limit
    frames, [(start, end)] = build_turn(lead=12, bursts=(30,), tail=30, bg_rms=1000.0, speech_rms=3000.0)
    out, stats = run(frames)
    assert stats["separation_db"] < 16.0
    for i in range(start + 1, len(frames)):
        assert out[i] == frames[i], i


def test_trim_db_is_the_fail_open_limit():
    # separation about 29 dB: gate works at 16, fails open when the limit is raised to 40
    frames, [(start, end)] = build_turn(lead=12, bursts=(30,), tail=40)
    out, _ = run(frames, trim_db=40.0)
    assert out[start + 1:] == frames[start + 1:]


def test_gate_that_never_opens_by_give_up_passes_the_rest():
    rng = random.Random(5)
    frames = [noise_frame(rng, 200.0) for _ in range(GIVE_UP + 30)]
    out, stats = run(frames)
    for i in range(GIVE_UP - 1, len(frames)):
        assert out[i] == frames[i], i
    for i in range(0, GIVE_UP - 1 - LOOK):
        assert is_quarter(frames[i], out[i]), i
    assert stats["separation_db"] < 3.0


def test_trim_false_changes_nothing_but_still_measures():
    frames, _ = build_turn(lead=20, bursts=(30,), tail=40)
    out, stats = run(frames, trim=False)
    assert out == frames
    assert stats["turned_down_ms"] == 0
    assert stats["separation_db"] > 20.0
    assert stats["frames"] == len(frames)


# --- noisy flag ----------------------------------------------------------------------------------------------------

def test_noisy_flag_on_both_sides_of_the_threshold():
    clear, _ = build_turn(bg_rms=300.0, speech_rms=2000.0, tail=10)     # about 16 dB
    weak, _ = build_turn(bg_rms=1000.0, speech_rms=1500.0, tail=10)     # about 5 dB
    _, s_clear = run(clear)
    _, s_weak = run(weak)
    assert s_clear["separation_db"] > 12.0 and s_clear["noisy"] is False
    assert s_weak["separation_db"] < 12.0 and s_weak["noisy"] is True


def test_confirm_db_moves_the_threshold():
    frames, _ = build_turn(bg_rms=300.0, speech_rms=2000.0, tail=10)
    _, s = run(frames, confirm_db=30.0)
    assert s["noisy"] is True
    _, s = run(frames, confirm_db=5.0)
    assert s["noisy"] is False


def test_fewer_than_16_frames_is_never_noisy():
    rng = random.Random(2)
    frames = [noise_frame(rng, 300.0) for _ in range(15)]
    _, s = run(frames)
    assert s["separation_db"] < 12.0 and s["frames"] == 15 and s["noisy"] is False
    frames.append(noise_frame(rng, 300.0))
    _, s = run(frames)
    assert s["frames"] == 16 and s["noisy"] is True


def test_confirm_db_zero_means_never_noisy():
    rng = random.Random(2)
    frames = [noise_frame(rng, 300.0) for _ in range(40)]
    _, s = run(frames, confirm_db=0)
    assert s["separation_db"] < 12.0 and s["noisy"] is False


# --- odd sizes, silence, full scale, determinism -------------------------------------------------------------------

def test_short_even_last_frame_keeps_its_length_and_is_quartered():
    frames, _ = build_turn(lead=20, bursts=(20,), tail=40)
    frames.append(b"".join([_pack([2000] * 300)]))   # 600 bytes
    out, _ = run(frames)
    assert len(out) == len(frames)
    assert len(out[-1]) == 600
    assert is_quarter(frames[-1], out[-1])


def test_odd_length_frames_do_not_raise_and_pass_unchanged():
    frames, _ = build_turn(lead=20, bursts=(20,), tail=40)
    odd_tail = bytes(range(1, 102))             # 101 bytes
    odd_mid = frames[2][:-1]                    # 1023 bytes inside the part that is turned down
    frames[2] = odd_mid
    frames.append(odd_tail)
    frames.append(b"\x07")
    out, stats = run(frames)
    assert len(out) == len(frames)
    assert out[2] == odd_mid
    assert out[-2] == odd_tail and out[-1] == b"\x07"
    assert stats["frames"] == len(frames)


def test_empty_frame_is_passed_through():
    t = TurnAudio()
    out = t.push(b"") + t.flush()
    assert out == [b""]


def test_digital_silence_does_not_raise():
    frames = [bytes(BYTES)] * 60
    out, stats = run(frames)
    assert out == frames
    assert stats["separation_db"] == 0.0


def test_full_scale_input_does_not_raise():
    square = _pack([32767 if (i // 8) % 2 else -32768 for i in range(N)])
    frames = [bytes(BYTES)] * 12 + [square] * 20 + [bytes(BYTES)] * 40
    out, stats = run(frames)
    assert len(out) == len(frames)
    assert all(len(o) == BYTES for o in out)
    assert stats["separation_db"] > 60.0
    # the attenuation of the most negative sample stays in range
    assert quarter(_pack([-32768] * N)) == _pack([-8192] * N)


def test_two_runs_give_identical_output():
    frames, _ = build_turn(lead=15, bursts=(25, 15), gaps=(10,), tail=30, fluct=0.2)
    a = run(frames)
    b = run(frames)
    assert a == b


def test_push_is_fast_enough_for_the_event_loop():
    frames, _ = build_turn(lead=20, bursts=(60,), tail=60)
    t = TurnAudio()
    start = time.perf_counter()
    for f in frames:
        t.push(f)
    per_frame_ms = (time.perf_counter() - start) * 1000 / len(frames)
    assert per_frame_ms < 0.5


# --- reported separation: the lower of the pre-roll level and the 25th percentile (CONTRACT 3.5, v1.7) ---------------

def test_clean_burst_from_the_first_frame_is_not_noisy():
    """A speaker who starts talking as the button is pressed: speech fills the pre-roll."""
    frames, _ = build_turn(lead=0, bursts=(40,), tail=30, bg_rms=100.0, speech_rms=3000.0)
    _, stats = run(frames)
    assert stats["noisy"] is False and stats["separation_db"] >= 21.0, stats
    print("no-lead-in clean burst separation_db:", stats["separation_db"])


def test_same_burst_over_a_loud_steady_background_is_noisy():
    frames, _ = build_turn(lead=0, bursts=(40,), tail=30, bg_rms=2000.0, speech_rms=3000.0)
    _, stats = run(frames)
    assert stats["noisy"] is True and stats["separation_db"] < 14.0, stats


def test_quiet_lead_in_reports_the_pre_roll_separation_as_before():
    tail = 20
    frames, _ = build_turn(lead=12, bursts=(30,), tail=tail, bg_rms=100.0, speech_rms=3000.0)
    _, stats = run(frames)
    assert abs(stats["separation_db"] - expected_sep(3000.0, 100.0, tail)) < 3.0 and stats["noisy"] is False


def test_default_confirm_threshold_is_14_db():
    # Separation of about 12.8 dB: noisy under the default 14, not under the old 12.
    frames, _ = build_turn(lead=12, bursts=(40,), tail=10, bg_rms=1000.0, speech_rms=4500.0, seed=9)
    _, stats = run(frames)
    assert 12.0 <= stats["separation_db"] < 14.0, stats
    assert stats["noisy"] is True and run(frames, confirm_db=12.0)[1]["noisy"] is False


# Fingerprints of the gate's output taken before the reported measure changed: what is turned down is unchanged.
GATE_CASES = [
    dict(),
    dict(lead=20, bursts=(30,), tail=40),
    dict(lead=0, bursts=(40,), tail=30),
    dict(lead=12, bursts=(20, 25), gaps=(10,), tail=30, bg_rms=300.0, speech_rms=1500.0, fluct=0.25, seed=3),
    dict(lead=10, bursts=(60,), tail=20, bg_rms=1000.0, speech_rms=1200.0, seed=4),
    dict(lead=8, bursts=(50,), tail=60, bg_rms=50.0, speech_rms=2000.0, tone=True, seed=5),
]
GATE_FINGERPRINTS = {
    (0, "on"): ("ab2bc76e143f9dd0", 608), (0, "off"): ("7b4663678b8372b2", 0), (0, "db25"): ("ab2bc76e143f9dd0", 608),
    (1, "on"): ("a0e1de968637f619", 1184), (1, "off"): ("90219fbb7c09c609", 0),
    (1, "db25"): ("a0e1de968637f619", 1184),
    (2, "on"): ("6c1da53e11ebee73", 1504), (2, "off"): ("134f62159c77c1ab", 0),
    (2, "db25"): ("6c1da53e11ebee73", 1504),
    (3, "on"): ("65d16fd3ea9421ff", 160), (3, "off"): ("4b5395520cc05dc9", 0), (3, "db25"): ("65d16fd3ea9421ff", 160),
    (4, "on"): ("31b85d777f7c3074", 1504), (4, "off"): ("75a6e459b63b7efe", 0),
    (4, "db25"): ("31b85d777f7c3074", 1504),
    (5, "on"): ("f6b608a893243259", 1440), (5, "off"): ("99d5307b84110f49", 0),
    (5, "db25"): ("f6b608a893243259", 1440),
}
GATE_KW = {"on": {}, "off": {"trim": False}, "db25": {"trim_db": 25.0}}


@pytest.mark.parametrize("key", sorted(GATE_FINGERPRINTS))
def test_gate_output_is_byte_for_byte_unchanged(key):
    import hashlib

    case, mode = key
    frames, _ = build_turn(**GATE_CASES[case])
    out, stats = run(frames, **GATE_KW[mode])
    assert (hashlib.sha256(b"".join(out)).hexdigest()[:16], stats["turned_down_ms"]) == GATE_FINGERPRINTS[key]
