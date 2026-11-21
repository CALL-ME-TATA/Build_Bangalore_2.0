-- Tables for the copy of every shop's KhataVaani ledger (server/app/cloud_sync.py, CONTRACT 3.7).
-- Safe to run more than once. The server runs it itself when SUPABASE_ACCESS_TOKEN is set; otherwise paste it
-- once into the project's SQL editor.
-- Names, tags, phone numbers and transcripts arrive AES-256-GCM encrypted (base64 of nonce + ciphertext + tag);
-- the key stays with the shop's server. Amounts (paise), kinds and dates are plain, as in the local ledger.
-- `shop` is "default" for the one-shop ledger, else the account's hashed id (never an email address).

create table if not exists public.khata_customers (
  shop text not null,
  id text not null,
  ident text not null,                      -- encrypted JSON: key, display, aliases, tags, phone, lang, say
  reminders_opt_in boolean not null default false,
  created_ts text not null,
  synced_at text not null,
  primary key (shop, id)
);

create table if not exists public.khata_events (
  shop text not null,
  id bigint not null,
  ts text not null,
  kind text not null,                       -- credit, payment or reversal
  customer_id text not null,
  amount_paise bigint not null,
  effective_date date not null,
  utterance_id text,
  supersedes_id bigint,                     -- a reversal: the event it cancels
  replaces_id bigint,                       -- a correction: the event it replaced
  session_id text,
  trace_id text,
  adjustment text,                          -- 'writeoff' on a write-off
  synced_at text not null,
  primary key (shop, id)
);

create table if not exists public.khata_utterances (
  shop text not null,
  id text not null,
  ts text not null,
  session_id text,
  body text not null,                       -- encrypted JSON: transcript, status, reply text, timings
  device_ts text,
  status text,
  action text,
  noisy boolean,
  synced_at text not null,
  primary key (shop, id)
);

create table if not exists public.khata_consent_log (
  shop text not null,
  id bigint not null,
  ts text not null,
  customer_id text not null,
  opt_in boolean not null,
  synced_at text not null,
  primary key (shop, id)
);

create table if not exists public.khata_confusions (
  shop text not null,
  heard bigint not null,
  meant bigint not null,
  n integer not null,
  last_ts text not null,
  synced_at text not null,
  primary key (shop, heard, meant)
);

create index if not exists khata_utterances_shop_ts on public.khata_utterances (shop, ts);

-- Only the server's secret key may read or write: row level security is on and no policy opens it to the
-- publishable (anon) key.
alter table public.khata_customers enable row level security;
alter table public.khata_events enable row level security;
alter table public.khata_utterances enable row level security;
alter table public.khata_consent_log enable row level security;
alter table public.khata_confusions enable row level security;

-- Let the REST API see the new tables at once.
notify pgrst, 'reload schema';
