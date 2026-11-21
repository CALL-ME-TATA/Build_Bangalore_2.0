// Settings. Every control has a visible label and says its state in words. Display settings apply at once
// (the root layout writes them onto <html>); voice speed goes through session.setVoiceSpeed; reminder opt-ins
// call POST /api/customers/{id}/reminders; the export files are built here from the API data.
import { Link } from '@tanstack/react-router';
import { Download } from 'lucide-react';
import { useState, type ReactNode } from 'react';
import type { Lang } from '../../i18n';
import { Button } from '../../components/Button';
import { Switch } from '../../components/Switch';
import { useLang } from '../../hooks/useLabels';
import type { MicMode } from '../../lib/mic';
import { ymd } from '../../lib/format';
import { customersQuery, ledgerQuery, queryClient } from '../../services/query';
import { session, useSession } from '../../state/session';
import { useSettings, type TextSize, type Theme } from '../../state/settings';
import { ScreenHeader } from '../hisaab/ScreenParts';
import { ChoiceGroup } from './ChoiceGroup';
import { speedChoice, type Speed } from './choices';
import { RemindersList } from './RemindersList';
import { downloadFile, exportFileName, ledgerCsv, ledgerJson } from './exportData';
import { useSettingsLabels, type SettingsLabels } from './labels';

export function SettingsScreen() {
  const L = useSettingsLabels();
  const s = useSettings();
  const shopName = s.shopName;

  const setLanguage = (lang: Lang) => {
    s.set('language', lang);
    session.setLang(lang);
    useSession.getState().dispatch({ type: 'set_lang', lang }); // labels switch now, not at the next reply
  };
  const setSpeed = (v: Speed) => {
    s.set('voiceSpeed', Number(v));
    session.setVoiceSpeed(Number(v));
  };

  return (
    <main id="main" tabIndex={-1} className="mx-auto w-full max-w-talk px-5 pt-6 pb-48 outline-none lg:px-10 lg:pt-12 lg:pb-24">
      <ScreenHeader title={L.title} line={shopName} />

      <Section id="set-voice" title={L.sectionVoice}>
        <ChoiceGroup<Lang>
          legend={L.language}
          currentWord={L.current}
          value={s.language}
          onChange={setLanguage}
          note={L.languageNote}
          options={[
            { value: 'hi', label: L.langHi, lang: 'hi' },
            { value: 'en', label: L.langEn, lang: 'en' },
          ]}
        />
        <ChoiceGroup<Speed>
          legend={L.voiceSpeed}
          currentWord={L.current}
          value={speedChoice(s.voiceSpeed)}
          onChange={setSpeed}
          options={[
            { value: '0.9', label: `${L.speedSlow} · 0.9×` },
            { value: '1', label: `${L.speedNormal} · 1.0×` },
            { value: '1.15', label: `${L.speedFast} · 1.15×` },
          ]}
        />
        <div className="border-y border-line">
          {/* Sent as hello.private and, inside a session, as a `settings` message (the root layout watches it). */}
          <Switch
            checked={s.privateMode}
            onCheckedChange={(v) => s.set('privateMode', v)}
            label={L.privateMode}
            description={L.privateModeNote}
            stateWords={[L.on, L.off]}
          />
        </div>
      </Section>

      <Section id="set-look" title={L.sectionLook}>
        <ChoiceGroup<TextSize>
          legend={L.textSize}
          currentWord={L.current}
          value={s.textSize}
          onChange={(v) => s.set('textSize', v)}
          options={[
            { value: 'normal', label: L.sizeNormal },
            { value: 'large', label: L.sizeLarge },
            { value: 'xlarge', label: L.sizeXLarge },
          ]}
        />
        <ChoiceGroup<Theme>
          legend={L.theme}
          currentWord={L.current}
          value={s.theme}
          onChange={(v) => s.set('theme', v)}
          options={[
            { value: 'light', label: L.themeLight },
            { value: 'dark', label: L.themeDark },
            { value: 'system', label: L.themeSystem },
          ]}
        />
        <div className="border-y border-line">
          <Switch
            checked={s.highContrast}
            onCheckedChange={(v) => s.set('highContrast', v)}
            label={L.highContrast}
            description={L.highContrastNote}
            stateWords={[L.on, L.off]}
          />
        </div>
      </Section>

      <Section id="set-mic" title={L.sectionMic}>
        <ChoiceGroup<MicMode>
          legend={L.micMode}
          currentWord={L.current}
          value={s.micMode}
          onChange={(v) => s.set('micMode', v)}
          options={[
            { value: 'hold', label: L.micHold, sub: L.micHoldSub },
            { value: 'toggle', label: L.micToggle, sub: L.micToggleSub },
          ]}
        />
      </Section>

      <Section id="set-shop" title={L.sectionShop}>
        <ShopName L={L} />
      </Section>

      <Section id="set-reminders" title={L.sectionReminders}>
        <RemindersList L={L} />
      </Section>

      <Section id="set-offline" title={L.sectionOffline}>
        <p className="max-w-prose text-body text-ink-2">{L.offlineNote}</p>
      </Section>

      <Section id="set-data" title={L.sectionData}>
        <ExportButtons L={L} />
      </Section>

      <Section id="set-demo" title={L.sectionDemo}>
        <p className="max-w-prose text-body text-ink-2">{L.demoNote}</p>
        <Link
          to="/demo"
          className="inline-flex min-h-12 items-center self-start rounded-control border border-line-strong bg-surface px-5 text-label text-ink hover:bg-fill"
        >
          {L.demoOpen}
        </Link>
      </Section>
    </main>
  );
}

function Section({ id, title, children }: { id: string; title: string; children: ReactNode }) {
  return (
    <section aria-labelledby={id} className="mt-12 flex flex-col gap-8">
      <h2 id={id} className="eyebrow">
        {title}
      </h2>
      {children}
    </section>
  );
}

function ShopName({ L }: { L: SettingsLabels }) {
  const shopName = useSettings((st) => st.shopName);
  const set = useSettings((st) => st.set);
  const [draft, setDraft] = useState(shopName);
  const commit = () => {
    const v = draft.trim().slice(0, 40);
    if (v) set('shopName', v);
    else setDraft(shopName);
  };
  return (
    <div className="flex flex-col gap-1">
      <label htmlFor="shop-name" className="text-label text-ink">
        {L.shopName}
      </label>
      <p id="shop-name-note" className="text-meta text-ink-2">
        {L.shopNameNote}
      </p>
      <input
        id="shop-name"
        value={draft}
        maxLength={40}
        autoComplete="organization"
        aria-describedby="shop-name-note"
        onChange={(e) => {
          setDraft(e.target.value);
          if (e.target.value.trim()) set('shopName', e.target.value.trim());
        }}
        onBlur={commit}
        className="mt-1 block min-h-12 w-full max-w-md rounded-control border border-line-strong bg-surface px-3 text-body text-ink"
      />
    </div>
  );
}

type ExportState = { kind: 'idle' } | { kind: 'busy' } | { kind: 'done'; name: string } | { kind: 'failed' };

function ExportButtons({ L }: { L: SettingsLabels }) {
  const lang = useLang();
  const [state, setState] = useState<ExportState>({ kind: 'idle' });

  const run = async (ext: 'csv' | 'json') => {
    setState({ kind: 'busy' });
    try {
      const ledger = await queryClient.fetchQuery({ ...ledgerQuery(500), staleTime: 0 });
      const name = exportFileName(ext, ymd());
      if (ext === 'csv') {
        const labels = { credit: L.csvKindCredit, payment: L.csvKindPayment, writeoff: L.csvKindWriteoff };
        downloadFile(ledgerCsv(ledger.entries, labels), name, 'text/csv;charset=utf-8');
      } else {
        const customers = await queryClient.fetchQuery({ ...customersQuery(), staleTime: 0 });
        downloadFile(ledgerJson(ledger, customers, new Date().toISOString()), name, 'application/json');
      }
      setState({ kind: 'done', name });
    } catch {
      setState({ kind: 'failed' });
    }
  };

  return (
    <div className="flex flex-col gap-4">
      <p className="max-w-prose text-body text-ink-2">{L.exportNote}</p>
      <div className="flex flex-wrap gap-3">
        <Button icon={<Download size={20} strokeWidth={1.75} />} onClick={() => void run('csv')} disabled={state.kind === 'busy'}>
          {L.exportCsv}
        </Button>
        <Button icon={<Download size={20} strokeWidth={1.75} />} onClick={() => void run('json')} disabled={state.kind === 'busy'}>
          {L.exportJson}
        </Button>
      </div>
      <p role="status" className="min-h-[1.4em] text-meta text-ink" lang={lang}>
        {state.kind === 'busy' ? L.exportBusy : state.kind === 'done' ? `${L.exportDone}: ${state.name}` : state.kind === 'failed' ? L.exportFailed : ''}
      </p>
    </div>
  );
}
