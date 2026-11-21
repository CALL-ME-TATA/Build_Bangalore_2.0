"""Test-wide setup.

The app loads `.env` without overriding variables that are already set. A developer's real `.env` must never
switch on Google sign-in, a paid LLM, Kafka or the Supabase copy inside the tests, so these are set to empty
(which counts as unset) for the whole run. Tests that need one of them pass their own Settings or a fake.
"""
from __future__ import annotations

import os

for _name in ("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "ALLOWED_EMAILS", "SESSION_SECRET", "PUBLIC_URL",
              "LLM_API_KEY", "KAFKA_BOOTSTRAP", "SUPABASE_URL", "SUPABASE_SECRET_KEY",
              "SUPABASE_SERVICE_ROLE_KEY", "SUPABASE_ACCESS_TOKEN", "TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN",
              "TWILIO_MESSAGING_SERVICE_SID", "TWILIO_FROM", "TWILIO_ALLOWED_TO", "TWILIO_TRIAL_TEMPLATE",
              "REMINDER_ANY_HOUR"):
    os.environ[_name] = ""
