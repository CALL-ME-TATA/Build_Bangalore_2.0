// Pure formatting helpers for the UI.

/** Whole rupees with Indian digit grouping: 125000 -> "₹1,25,000". */
export function rupees(n) {
  const v = Math.round(Number(n) || 0);
  const sign = v < 0 ? '-' : '';
  const s = String(Math.abs(v));
  let out = s;
  if (s.length > 3) {
    const head = s.slice(0, -3).replace(/\B(?=(\d\d)+(?!\d))/g, ',');
    out = head + ',' + s.slice(-3);
  }
  return sign + '₹' + out;
}

/** Local calendar date as YYYY-MM-DD. */
export function ymd(d = new Date()) {
  const p = (x) => String(x).padStart(2, '0');
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
}

function dayNumber(s) {
  const [y, m, d] = s.split('-').map(Number);
  return Date.UTC(y, m - 1, d) / 86400000;
}

/** "Today", "Yesterday", "3 din pehle", or the raw date for older or future dates. */
export function dayLabel(date, today) {
  if (!date || !/^\d{4}-\d{2}-\d{2}/.test(date)) return '';
  const diff = dayNumber(today) - dayNumber(date.slice(0, 10));
  if (diff === 0) return 'Today';
  if (diff === 1) return 'Yesterday';
  if (diff > 1 && diff < 7) return `${diff} din pehle`;
  return date.slice(0, 10);
}

/** View model for one entry card, e.g. "+ ₹340" / "Credit · Today". */
export function entryCard(entry, today) {
  const credit = entry.kind === 'credit';
  const name = entry.customer && (entry.customer.display || entry.customer.name);
  return {
    cls: credit ? 'credit' : 'payment',
    sign: credit ? '+' : '−',
    amount: rupees(entry.amount),
    kind: credit ? 'Credit' : 'Payment',
    day: dayLabel(entry.date, today),
    name: name || '',
    reversed: Boolean(entry.reversed),
  };
}

const STATE_LABELS = {
  listening: 'Sun raha hoon… (Listening)',
  hearing: 'Aawaz aa rahi hai… (Hearing)',
  transcribing: 'Samajh raha hoon… (Transcribing)',
  thinking: 'Soch raha hoon… (Thinking)',
  speaking: 'Bol raha hoon… (Speaking)',
  idle: 'Dabakar boliye (Hold to talk)',
};

export function stateLabel(phase) {
  return STATE_LABELS[phase] || STATE_LABELS.idle;
}

/** Latency rows for the chip, from the server timing message and the client measurement. */
export function latencyRows(timing, clientMs) {
  const rows = [];
  const ms = (timing && timing.ms) || {};
  const names = [
    ['gnani_stt_latency', 'Gnani STT'],
    ['stt_final', 'End to final text'],
    ['parse', 'Parse'],
    ['db', 'Database'],
    ['tts_first_chunk', 'TTS first chunk'],
    ['end_to_first_audio', 'End to first audio (server)'],
  ];
  for (const [k, label] of names) if (ms[k] != null) rows.push([label, Math.round(ms[k])]);
  if (clientMs != null) rows.push(['Release to first sound (phone)', Math.round(clientMs)]);
  return rows;
}
