# KhataVaani web app

Static PWA: Preact + htm (vendored in `vendor/`), plain ES modules and CSS. No build step, no requests to other origins.
It speaks the protocol in `docs/CONTRACT.md` section 3.

## Run

The server serves this folder at `/` and the WebSocket at `/ws/session` on the same origin:

```
cd server
../.venv/Scripts/python -m uvicorn app.main:app --port 8000
```

Open `http://localhost:8000` on the desktop. `localhost` counts as a secure context, so the microphone works there.

## Phone: HTTPS is required for the microphone

Chrome on Android only allows `getUserMedia` on HTTPS (or localhost). Put a tunnel in front of the server and open the
tunnel URL on the phone:

```
cloudflared tunnel --url http://localhost:8000
# or
ngrok http 8000
```

The page and the WebSocket use the same host, and the socket switches to `wss://` automatically on HTTPS. If the server
has an `ACCESS_CODE`, open the page as `https://<tunnel>/?code=<code>`.

Without microphone permission the app still starts; use the "Type karein" box to send text turns.

## Using it

1. Tap "Shuru karein". The greeting plays.
2. Hold the orange button (or hold Space on a desktop) and speak; release to finish. Pressing during a reply stops it
   at once (barge-in).
3. The Talk screen shows the state, live transcript, entry cards, the spoken reply, a latency chip (tap it for per-hop
   timings and the trace id) and a permanent "AI sahayak" label. The Khata tab shows totals, customer balances and
   recent entries, refreshed after every result.

## Layout

| File | Role |
|---|---|
| `app.js`, `ui.js` | Mount and components |
| `controller.js` | Microphone, player, socket and store wiring; press and release handling |
| `store.js` | Pure reducer: turn ids, barge-in, client latency |
| `ws.js` | Protocol client with reconnect and `resume` |
| `format.js`, `api.js` | Formatting helpers; `/api/customers` and `/api/ledger` calls |
| `audio/dsp.js` | Pure: downsampler, PCM16 conversion, chunker, PCM decoder |
| `audio/capture-worklet.js` | AudioWorklet: context rate to 16 kHz PCM16, 32 ms chunks |
| `audio/player.js` | Gapless playback with an immediate `stop()` |
| `sw.js` | Caches the app shell only (network first) |

## Tests

```
node --test web/tests
```

Covers the downsampler, PCM conversion, chunking, the message reducer (turn ordering, barge-in, latency), formatting
and the reconnect logic. Microphone, audio output and layout need a real browser.

## Notes

- Audio frames are 1,024 bytes (512 samples). The last partial frame, under 32 ms, is not sent: `end` goes out on release.
- Entry and balance amounts are shown as whole rupees, as received.
- The manifest uses an SVG icon; Chrome may ask for PNG icons before offering "Install app".
