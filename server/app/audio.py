"""Per-turn audio measuring and foreground gate (CONTRACT section 3.5).

One `TurnAudio` per spoken turn. Frames are 1,024 bytes (512 samples of little-endian int16, 32 ms at 16 kHz).
The output runs `LOOK` frames behind the input so that the frames just before the speaker starts can still be kept;
`flush()` releases what is held at the end of the turn. Every input frame comes out exactly once, in order and with
its length unchanged, either byte-identical or with each sample at `ATTEN` of its value.

Pure Python, no I/O, no logging, no module state.
"""
from __future__ import annotations

import array
import math
import sys
from collections import deque
from operator import mul

PRE = 8              # frames that give the background level (the pre-roll)
RISE_DB = 8.0        # a frame is near when this far above the background ...
DROP_DB = 14.0       # ... and at most this far below the speaker level
RELEASE_DB = 0.06    # speaker level peak release per frame
MIN_RUN = 2          # near frames in a row that open the gate
HANG = 16            # frames without a near frame before the gate closes
LOOK = 8             # frames before an opening that count as inside
GIVE_UP = 48         # frames into the turn after which an unopened gate passes everything
ATTEN = 0.25         # amplitude of a frame outside the gate (12 dB down)
MIN_NOISY_FRAMES = 16
LOW_PCT = 0.25       # the reported separation also measures against this percentile of the turn's frame levels
FRAME_MS = 32

_BIG_ENDIAN = sys.byteorder == "big"


def _level_db(frame: bytes) -> float:
    n = len(frame) // 2
    if n == 0:
        return 0.0
    a = array.array("h")
    a.frombytes(frame[: n * 2])
    if _BIG_ENDIAN:
        a.byteswap()
    return 10 * math.log10(sum(map(mul, a, a)) / n + 1.0)


def _turned_down(frame: bytes) -> bytes:
    if len(frame) & 1:
        return frame
    a = array.array("h")
    a.frombytes(frame)
    if _BIG_ENDIAN:
        a.byteswap()
    out = array.array("h", [int(x * ATTEN) for x in a])
    if _BIG_ENDIAN:
        out.byteswap()
    return out.tobytes()


class TurnAudio:
    def __init__(self, *, trim: bool = True, trim_db: float = 16.0, confirm_db: float = 14.0) -> None:
        self._trim = trim
        self._trim_db = trim_db
        self._confirm_db = confirm_db
        self._n = 0
        self._pre: list[float] = []
        self._bg: float | None = None
        self._peak: float | None = None
        self._run = 0
        self._hang = 0
        self._opened = False
        self._latched = False
        self._queue: deque[list] = deque()   # [frame, keep]
        self._down = 0
        self._levels: list[float] = []       # every frame level of the turn (at most about 940), for `stats`

    def _separation(self) -> float:
        """Speaker level minus the lower of the pre-roll level and the 25th percentile of the turn's frame levels.

        The second keeps a speaker who starts talking as the button is pressed (speech inside the pre-roll) from
        counting as background. Only the reported figure uses it; the gate keeps the pre-roll level."""
        if self._peak is None or not self._levels:
            return 0.0
        pre = self._bg if self._bg is not None else max(self._pre)
        levels = sorted(self._levels)
        low = levels[min(int(len(levels) * LOW_PCT), len(levels) - 1)]
        return self._peak - min(pre, low)

    def push(self, frame: bytes) -> list[bytes]:
        """Take one input frame; return the frames to send on now (the output runs LOOK frames behind)."""
        db = _level_db(frame)
        self._n += 1
        self._levels.append(db)
        if self._bg is None:
            self._pre.append(db)
            if len(self._pre) >= PRE:
                self._bg = sorted(self._pre)[(3 * len(self._pre)) // 4]
        bg = self._bg if self._bg is not None else max(self._pre)
        self._peak = db if self._peak is None else max(self._peak - RELEASE_DB, db)
        near = db >= bg + RISE_DB and db >= self._peak - DROP_DB
        self._run = self._run + 1 if near else 0
        opened_now = False
        if self._run >= MIN_RUN:
            opened_now = self._hang == 0
            self._hang = HANG
            self._opened = True
        if opened_now and self._peak - bg < self._trim_db:
            self._latched = True
        if not self._opened and self._n >= GIVE_UP:
            self._latched = True
        keep = self._hang > 0 or self._latched
        if not near and self._hang > 0:
            self._hang -= 1
        if opened_now:
            for item in self._queue:
                item[1] = True
        self._queue.append([frame, keep])
        out: list[bytes] = []
        while len(self._queue) > LOOK:
            out.append(self._emit(*self._queue.popleft()))
        return out

    def flush(self) -> list[bytes]:
        """The frames still held, at the end of the turn."""
        out = [self._emit(f, k) for f, k in self._queue]
        self._queue.clear()
        return out

    def stats(self) -> dict:
        raw = self._separation()
        sep = round(raw, 1)
        noisy = self._n >= MIN_NOISY_FRAMES and self._confirm_db > 0 and raw < self._confirm_db
        return {
            "separation_db": sep,
            "noisy": noisy,
            "turned_down_ms": self._down * FRAME_MS,
            "frames": self._n,
        }

    def _emit(self, frame: bytes, keep: bool) -> bytes:
        if keep or not self._trim or len(frame) & 1 or not frame:
            return frame
        self._down += 1
        return _turned_down(frame)
