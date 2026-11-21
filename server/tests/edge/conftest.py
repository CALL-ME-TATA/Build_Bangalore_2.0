"""Fixtures for the edge-case suite."""
from __future__ import annotations

import pytest

from .kit import Shop


@pytest.fixture
def shop(tmp_path):
    s = Shop(tmp_path / "shop")
    yield s
    s.close()


@pytest.fixture
def rs(shop):
    """A shop with customers Ramesh and Sunita, each owing 1,000 (so a payment of a few hundred is not an overpayment)."""
    shop.seed(("ramesh", "credit", 1000), ("sunita", "credit", 1000))
    return shop


@pytest.fixture
def make_shop(tmp_path):
    made = []

    def factory(start=None, env=None, parse_fn=None, disclosed=True):
        kw = {"start": start} if start else {}
        s = Shop(tmp_path / f"shop{len(made)}", env=env, parse_fn=parse_fn, disclosed=disclosed, **kw)
        made.append(s)
        return s

    yield factory
    for s in made:
        s.close()


@pytest.fixture
def live_stack(tmp_path):
    """The real app and the mock Gnani server on local ports, with a controllable clock."""
    from .wskit import LiveStack

    stack = LiveStack(tmp_path / "live").start()
    yield stack
    stack.stop()


@pytest.fixture
def make_live_stack(tmp_path):
    from .wskit import LiveStack

    made = []

    def factory(env=None):
        stack = LiveStack(tmp_path / f"live{len(made)}", env=env).start()
        made.append(stack)
        return stack

    yield factory
    for s in made:
        s.stop()
