"""Unit tests for the pure functions of scripts/replay_audio.py: noise mixing, noisy copies, judging and metrics."""
from __future__ import annotations

import importlib.util
import json
import math
import random
import struct
import wave
from datetime import date
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "replay_audio.py"
spec = importlib.util.spec_from_file_location("replay_audio", SCRIPT)
ra = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ra)


def tone(n=8000, amp=8000, period=40):
    return [int(amp * math.sin(2 * math.pi * i / period)) for i in range(n)]


@pytest.mark.parametrize("snr", [20, 10, 5, 0])
@pytest.mark.parametrize("kind", ["white", "pink", "babble"])
def test_mix_reaches_the_requested_snr(kind, snr):
    rng = random.Random(3)
    signal = tone(16000, amp=4000)
    noise = {"white": ra.white_noise, "pink": ra.pink_noise}.get(kind, None)
    noise = noise(16000, rng) if noise else ra.babble_noise([tone(9000, 3000, 55), tone(7000, 3000, 31)], 16000, rng)
    mixed = ra.mix_at_snr(signal, noise, snr)
    assert len(mixed) == len(signal)
    assert abs(ra.measured_snr_db(signal, mixed) - snr) < 0.3


def test_mix_clips_to_16_bits():
    mixed = ra.mix_at_snr([32000] * 100, [1.0, -1.0] * 50, -20)
    assert max(mixed) <= 32767 and min(mixed) >= -32768


def test_mix_repeats_short_noise_and_handles_empty_inputs():
    assert len(ra.mix_at_snr(tone(1000), [0.5, -0.5, 0.2], 10)) == 1000
    assert ra.mix_at_snr([], [1.0], 10) == []
    assert ra.mix_at_snr([5, 6, 7], [], 10) == [5, 6, 7]
    assert ra.mix_at_snr([0, 0, 0], [1.0, 2.0], 10) == [0, 0, 0], "silence stays silence"


def test_pink_noise_has_more_low_than_high_frequency_energy():
    x = ra.pink_noise(8192, random.Random(1))
    diff = [b - a for a, b in zip(x, x[1:])]
    assert ra.rms(diff) < ra.rms(x) * 1.2, "differencing white noise raises its level; pink noise is smoother"
    w = ra.white_noise(8192, random.Random(1))
    wdiff = [b - a for a, b in zip(w, w[1:])]
    assert ra.rms(diff) / ra.rms(x) < ra.rms(wdiff) / ra.rms(w)


def test_babble_sums_shifted_copies_and_is_deterministic():
    others = [tone(5000, 1000, 40), tone(6000, 1000, 70)]
    a = ra.babble_noise(others, 4000, random.Random(5))
    b = ra.babble_noise(others, 4000, random.Random(5))
    assert a == b and len(a) == 4000 and max(abs(v) for v in a) > 1000


def test_wav_round_trip_and_resampling(tmp_path):
    samples = tone(1600)
    path = tmp_path / "a.wav"
    ra.write_wav(path, samples)
    assert ra.read_wav(path) == samples
    ra.write_wav(path, tone(800), rate=8000)
    assert len(ra.read_wav(path, 16000)) == 1600


def test_stereo_is_averaged_to_mono(tmp_path):
    path = tmp_path / "s.wav"
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(struct.pack("<4h", 100, 300, -50, 50))
    assert ra.read_wav(path) == [200, 0]


def test_frames_are_1024_bytes_and_the_last_is_padded():
    out = ra.frames(tone(512 * 2 + 10))
    assert [len(f) for f in out] == [1024, 1024, 1024]
    assert out[-1][20:] == b"\x00" * 1004


def test_make_noisy_writes_every_copy_and_a_manifest_that_inherits_expectations(tmp_path):
    for name in ("one", "two"):
        ra.write_wav(tmp_path / f"{name}.wav", tone(4000, 5000, 30 if name == "one" else 50))
    (tmp_path / "manifest.jsonl").write_text(
        json.dumps({"wav": "one.wav", "expect": {"customer": "ramesh", "kind": "credit", "amount": 340,
                                                 "date_offset": 0}}) + "\n"
        + json.dumps({"wav": "two.wav", "expect_status": "rejected"}) + "\n", encoding="utf-8")
    out = tmp_path / "noisy"
    entries = ra.make_noisy(tmp_path, out, [20, 10, 5])
    assert len(entries) == 2 * 3 * 3
    assert len(list(out.glob("*.wav"))) == 18
    lines = [json.loads(line) for line in (out / "manifest.jsonl").read_text(encoding="utf-8").splitlines()]
    one = [e for e in lines if e["wav"].startswith("one_")]
    assert all(e["expect"]["amount"] == 340 for e in one) and len(one) == 9
    assert {e["noise"] for e in lines} == {"white", "pink", "babble"} and {e["snr_db"] for e in lines} == {20, 10, 5}
    assert all(e["expect_status"] == "rejected" for e in lines if e["wav"].startswith("two_"))
    clean = ra.read_wav(tmp_path / "one.wav")
    noisy = ra.read_wav(out / "one_white10dB.wav")
    assert abs(ra.measured_snr_db(clean, noisy) - 10) < 0.5


def test_make_noisy_is_repeatable_for_a_seed(tmp_path):
    ra.write_wav(tmp_path / "a.wav", tone(3000))
    ra.make_noisy(tmp_path, tmp_path / "x", [10], seed=4)
    ra.make_noisy(tmp_path, tmp_path / "y", [10], seed=4)
    assert (tmp_path / "x" / "a_white10dB.wav").read_bytes() == (tmp_path / "y" / "a_white10dB.wav").read_bytes()


TODAY = date(2026, 11, 21)


def result(status="ok", action="append", **entry):
    entries = []
    if entry:
        base = {"kind": "credit", "customer": {"display": "Ramesh"}, "amount": 340, "date": "2026-11-21",
                "reversed": False}
        entries = [{**base, **entry}]
    return {"status": status, "action": action, "entries": entries}


def judged(expect, res, **top):
    return ra.judge({"entry": {"wav": "a.wav", "expect": expect, **top}, "result": res}, TODAY)


EXPECT = {"customer": "ramesh", "kind": "credit", "amount": 340, "date_offset": 0}


def test_judge_a_correct_save():
    j = judged(EXPECT, result(kind="credit"))
    assert (j["amount"], j["kind"], j["customer"], j["date"], j["silent_wrong_save"]) == (True, True, True, True, False)


@pytest.mark.parametrize("change,field", [
    ({"amount": 430}, "amount"), ({"kind": "payment"}, "kind"),
    ({"customer": {"display": "Suresh"}}, "customer"), ({"date": "2026-11-20"}, "date")])
def test_judge_a_wrong_save_is_silent_and_marks_only_the_wrong_field(change, field):
    j = judged(EXPECT, result(**change))
    assert j[field] is False and j["silent_wrong_save"] is True
    assert [f for f in ("amount", "kind", "customer", "date") if j[f] is False] == [field]


def test_judge_date_offset_counts_back_from_today():
    j = judged({"date_offset": 2}, result(date="2026-11-19"))
    assert j["date"] is True


def test_judge_a_question_is_not_a_silent_save_and_counts_as_asked():
    j = judged(EXPECT, result("needs_clarification", "none"))
    assert j["asked"] is True and j["silent_wrong_save"] is False and j["amount"] is False


def test_judge_expected_rejection_that_saved_is_a_silent_wrong_save():
    j = ra.judge({"entry": {"wav": "a.wav", "expect_status": "rejected"}, "result": result(kind="credit")}, TODAY)
    assert j["silent_wrong_save"] is True and j["status_ok"] is False


def test_judge_expected_rejection_that_was_rejected_is_fine():
    j = ra.judge({"entry": {"wav": "a.wav", "expect_status": "rejected"}, "result": result("rejected", "none")}, TODAY)
    assert j["silent_wrong_save"] is False and j["status_ok"] is True


def test_judge_amend_uses_the_new_entry_not_the_reversed_one():
    res = {"status": "ok", "action": "amend", "entries": [
        {"kind": "credit", "customer": {"display": "Ramesh"}, "amount": 340, "date": "2026-11-21", "reversed": True},
        {"kind": "credit", "customer": {"display": "Ramesh"}, "amount": 430, "date": "2026-11-21", "reversed": False}]}
    assert judged({"amount": 430}, res)["amount"] is True


def test_summarise_rates_asked_silent_saves_and_stage_percentiles():
    rows = [judged(EXPECT, result(kind="credit")), judged(EXPECT, result(amount=430)),
            judged(EXPECT, result("needs_clarification", "none"))]
    timings = [{"stt_final": 100.0, "end_to_first_audio": 900.0}, {"stt_final": 300.0, "end_to_first_audio": 1100.0},
               {"stt_final": 200.0}]
    s = ra.summarise(rows, timings)
    assert s["turns"] == 3 and s["amount"] == (1, 3) and s["asked"] == 1 and s["silent_wrong_saves"] == 1
    assert s["stages"]["stt_final"][0] == 200.0 and s["stages"]["stt_final"][1] == 300.0
    assert s["stages"]["end_to_first_audio"][2] == 2 and s["stages"]["parse"] is None
    text = ra.format_summary(s)
    assert "silent wrong saves     1" in text and "stt_final" in text


def test_percentile_edges():
    assert ra.percentile([5.0], 95) == 5.0
    assert ra.percentile([1.0, 2.0, 3.0, 4.0], 50) in (2.0, 3.0)
    assert ra.percentile([1.0, 2.0, 3.0, 4.0], 95) == 4.0
