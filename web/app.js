// Entry point: mounts the UI and registers the service worker.
import { html, render, useState, useEffect } from './vendor/htm-preact.js';
import { createController } from './controller.js';
import { Header, StartOverlay, TalkScreen, KhataScreen } from './ui.js';

let setSnapshot = () => {};
const ctl = createController((s) => setSnapshot({ s }));

function App() {
  const [snap, setSnap] = useState({ s: ctl.state });
  const [started, setStarted] = useState(false);
  const [tab, setTab] = useState('talk');
  setSnapshot = setSnap;
  useEffect(() => { if ('serviceWorker' in navigator) navigator.serviceWorker.register('sw.js').catch(() => {}); }, []);

  const s = snap.s;
  const start = async () => {
    setStarted('busy');
    try { await ctl.start(); } catch (e) { setStarted(false); alert(String(e)); return; }
    setStarted(true);
  };
  return html`
    <${Header} conn=${s.conn} />
    ${tab === 'talk'
      ? html`<${TalkScreen} s=${s} ctl=${ctl} />`
      : html`<${KhataScreen} refreshKey=${s.resultCount} />`}
    <nav class="tabs">
      <button class=${tab === 'talk' ? 'on' : ''} onClick=${() => setTab('talk')}>Baat <small>Talk</small></button>
      <button class=${tab === 'khata' ? 'on' : ''} onClick=${() => setTab('khata')}>Khata <small>Ledger</small></button>
    </nav>
    ${started !== true && html`<${StartOverlay} onStart=${start} busy=${started === 'busy'} />`}
  `;
}

render(html`<${App} />`, document.getElementById('app'));
