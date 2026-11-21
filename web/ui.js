// Preact components. Logic lives in store.js, format.js and controller.js.
import { html, useState, useEffect, useRef } from './vendor/htm-preact.js';
import { entryCard, latencyRows, rupees, stateLabel, ymd } from './format.js';
import { loadKhata } from './api.js';
import { t } from './i18n.js';

const MicIcon = () => html`<svg viewBox="0 0 24 24" width="28" height="28" aria-hidden="true"><path fill="currentColor" d="M12 15a3 3 0 0 0 3-3V6a3 3 0 0 0-6 0v6a3 3 0 0 0 3 3Zm5-3a5 5 0 0 1-10 0H5a7 7 0 0 0 6 6.9V22h2v-3.1A7 7 0 0 0 19 12h-2Z"/></svg>`;

export function Header({ conn, lang }) {
  return html`<header class="top">
    <span class="logo"><${MicIcon} /></span>
    <h1>KhataVaani</h1>
    <span class="ai-badge" title=${t(lang, 'aiTitle')}>${t(lang, 'ai')}</span>
    ${conn !== 'open' && html`<span class="conn">${conn === 'reconnecting' ? t(lang, 'reconnecting') : conn}</span>`}
  </header>`;
}

export function StartOverlay({ onStart, busy, lang }) {
  return html`<div class="overlay">
    <div class="logo big"><${MicIcon} /></div>
    <h2>KhataVaani</h2>
    <p>${t('hi', 'tagline')}</p>
    <p class="sub">${t('en', 'tagline')}</p>
    <button class="primary" disabled=${busy} onClick=${() => onStart('hi')}>Shuru karein <small>Hindi / Hinglish</small></button>
    <button class="primary alt" disabled=${busy} onClick=${() => onStart('en')}>Start <small>English</small></button>
  </div>`;
}

function EntryCards({ entries, lang }) {
  if (!entries.length) return null;
  const today = ymd();
  return html`<div class="cards">
    ${entries.map((e) => {
      const c = entryCard(e, today);
      return html`<div class=${`card ${c.cls}${c.reversed ? ' reversed' : ''}`} key=${e.id}>
        <b>${c.sign} ${c.amount}</b>
        <span>${c.kind} · ${c.day}${c.reversed ? html`<span class="removed">${t(lang, 'removed')}</span>` : ""}</span>
        ${c.name && html`<span class="who">${c.name}</span>`}
      </div>`;
    })}
  </div>`;
}

function LatencyChip({ timing, clientMs }) {
  const rows = latencyRows(timing, clientMs);
  if (!rows.length) return null;
  const server = timing && timing.ms && timing.ms.end_to_first_audio;
  return html`<details class="latency">
    <summary>
      ${server != null && html`Server ${Math.round(server)} ms`}
      ${server != null && clientMs != null && ' · '}
      ${clientMs != null && html`Phone ${Math.round(clientMs)} ms`}
    </summary>
    <table>${rows.map(([k, v]) => html`<tr><td>${k}</td><td>${v} ms</td></tr>`)}</table>
    ${timing && timing.traceId && html`<code>trace ${timing.traceId}</code>`}
  </details>`;
}

function TypeBox({ onSend, disabled, lang }) {
  const [text, setText] = useState('');
  const submit = (e) => {
    e.preventDefault();
    onSend(text);
    setText('');
  };
  return html`<details class="typebox">
    <summary>${t(lang, 'typeLabel')}</summary>
    <form onSubmit=${submit}>
      <input value=${text} onInput=${(e) => setText(e.target.value)} placeholder="Ramesh ka 340 udhaar" disabled=${disabled} />
      <button disabled=${disabled || !text.trim()}>${t(lang, 'send')}</button>
    </form>
  </details>`;
}

function TalkButton({ ctl, enabled, lang }) {
  const [down, setDown] = useState(false);
  const press = () => { setDown(true); ctl.press(); };
  const release = () => { setDown(false); ctl.release(); };
  useEffect(() => {
    // Holding Space is the desktop equivalent of the button.
    const typing = (e) => /^(INPUT|TEXTAREA)$/.test(e.target.tagName);
    const kd = (e) => {
      if (e.code !== 'Space' || e.repeat || typing(e)) return;
      e.preventDefault();
      press();
    };
    const ku = (e) => {
      if (e.code !== 'Space' || typing(e)) return;
      e.preventDefault();
      release();
    };
    addEventListener('keydown', kd);
    addEventListener('keyup', ku);
    return () => { removeEventListener('keydown', kd); removeEventListener('keyup', ku); };
  }, [ctl]);
  return html`<div class="talk">
    <button class=${`mic${down ? ' down' : ''}`} disabled=${!enabled && !down}
      onPointerDown=${press} onPointerUp=${release} onPointerCancel=${release} onPointerLeave=${release}
      onContextMenu=${(e) => e.preventDefault()} aria-label=${t(lang, 'idle')}>
      <${MicIcon} />
    </button>
    <div class="hint">${t(lang, 'hint')}</div>
  </div>`;
}

export function TalkScreen({ s, ctl }) {
  const lang = s.lang;
  const r = s.result;
  const clarify = r && r.status === 'needs_clarification';
  return html`<main class="talk-screen">
    <div class="stateline">${s.error ? html`<span class="err">${s.error}</span>` : stateLabel(s.phase, lang)}</div>
    ${ctl.micError && html`<div class="err box">${t(lang, ctl.micError)}</div>`}
    <section class="transcript">
      <h3>${t(lang, 'transcript')}</h3>
      <p class=${s.transcriptFinal ? '' : 'partial'}>${s.transcript ? `“${s.transcript}”` : '…'}</p>
    </section>
    ${r && html`<${EntryCards} entries=${r.entries} lang=${lang} />`}
    ${clarify && r.question && html`<div class="question" role="alert"><small>${t(lang, 'question')}</small>${r.question}</div>`}
    ${r && r.replyText && html`<div class="reply"><small>${t(lang, 'ai')}</small>${r.replyText}</div>`}
    <${LatencyChip} timing=${s.timing} clientMs=${s.clientMs} />
    <${TypeBox} lang=${lang} onSend=${(t) => ctl.sendText(t)} disabled=${s.conn !== 'open' || !s.greeted} />
    <${TalkButton} lang=${lang} ctl=${ctl} enabled=${ctl.micReady && s.greeted} />
  </main>`;
}

export function KhataScreen({ refreshKey, lang }) {
  const [data, setData] = useState(null);
  const [err, setErr] = useState(null);
  const seq = useRef(0);
  useEffect(() => {
    const mine = ++seq.current;
    loadKhata().then((d) => { if (mine === seq.current) { setData(d); setErr(null); } })
      .catch((e) => setErr(String(e.message || e)));
  }, [refreshKey]);
  const today = ymd();
  return html`<main class="khata-screen">
    <div class="hero">
      <h2>${t(lang, 'khataTitle')}</h2>
      <div class="totals">
        <div class="tot credit"><b>${rupees(data ? data.totals.credit_today : 0)}</b><span>${t(lang, 'creditGiven')}</span></div>
        <div class="tot payment"><b>${rupees(data ? data.totals.payment_today : 0)}</b><span>${t(lang, 'paymentIn')}</span></div>
      </div>
    </div>
    ${err && html`<div class="err box">${err}</div>`}
    <h3 class="sec">${t(lang, 'customers')}</h3>
    <ul class="list">
      ${data && data.customers.map((c) => html`<li key=${c.id}>
        <span class="avatar">${(c.display || '?')[0].toUpperCase()}</span>
        <span class="nm">${c.display}${c.tags && c.tags.length ? ` (${c.tags.join(', ')})` : ''}</span>
        <b class=${c.balance > 0 ? 'credit' : 'payment'}>${rupees(c.balance)}</b>
      </li>`)}
    </ul>
    <h3 class="sec">${t(lang, 'recent')}</h3>
    <ul class="list">
      ${data && data.entries.map((e) => {
        const c = entryCard(e, today);
        return html`<li key=${e.id} class=${c.reversed ? 'reversed' : ''}>
          <span class="nm">${c.name}<small>${c.kind} · ${c.day}${c.reversed ? html`<span class="removed">${t(lang, 'removed')}</span>` : ""}</small></span>
          <b class=${c.cls}>${c.sign} ${c.amount}</b>
        </li>`;
      })}
    </ul>
  </main>`;
}
