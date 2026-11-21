"""Test-wide setup.

The app loads `.env` without overriding variables that are already set. A developer's real `.env` must never
switch on Google sign-in or a paid LLM inside the tests, so these are set to empty (which counts as unset) for
the whole run. Tests that need sign-in or the LLM pass their own Settings or a fake.
"""
from __future__ import annotations

import os

for _name in ("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "ALLOWED_EMAILS", "SESSION_SECRET", "PUBLIC_URL",
              "LLM_API_KEY", "KAFKA_BOOTSTRAP"):
    os.environ[_name] = ""
