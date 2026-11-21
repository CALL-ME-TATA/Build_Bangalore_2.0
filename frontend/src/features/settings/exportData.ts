// Data export, built in the browser from the API data: a CSV of the ledger and a JSON file of the ledger and
// customers. Pure, except downloadFile which hands a Blob to the browser (no request to any origin).
import type { Customer, LedgerView } from '../../services/api';
import type { Entry } from '../../services/session/types';

export const CSV_COLUMNS = ['id', 'date', 'recorded_at', 'kind', 'kind_label', 'customer', 'tag', 'amount', 'signed_amount', 'reversed'] as const;

/**
 * One CSV cell. Strings are quoted when needed, and a leading = + - @ (or tab / CR) is neutralised with an
 * apostrophe so a spreadsheet never runs a name as a formula. Numbers and booleans are written as they are.
 */
export function csvCell(v: string | number | boolean | null | undefined): string {
  if (v === null || v === undefined) return '';
  if (typeof v === 'number') return Number.isFinite(v) ? String(v) : '';
  if (typeof v === 'boolean') return v ? 'true' : 'false';
  let s = v;
  if (/^[=+\-@\t\r]/.test(s)) s = `'${s}`;
  return /[",\r\n]/.test(s) || s !== s.trim() ? `"${s.replace(/"/g, '""')}"` : s;
}

/** CSV of the entries, oldest first, CRLF line ends (RFC 4180). Reversed entries are kept and marked. */
export function ledgerCsv(entries: readonly Entry[], kindLabels: { credit: string; payment: string; writeoff?: string }): string {
  const rows = [...entries]
    .sort((a, b) => (a.ts < b.ts ? -1 : a.ts > b.ts ? 1 : Number(a.id) - Number(b.id)))
    .map((e) =>
      [
        typeof e.id === 'number' ? e.id : String(e.id),
        e.date,
        e.ts,
        e.kind,
        e.kind === 'credit' ? kindLabels.credit : e.kind === 'payment' ? kindLabels.payment : (kindLabels.writeoff ?? 'writeoff'),
        e.customer.display,
        e.customer.tags[0] ?? '',
        e.amount,
        e.kind === 'credit' ? e.amount : -e.amount,
        e.reversed,
      ]
        .map(csvCell)
        .join(','),
    );
  return [CSV_COLUMNS.join(','), ...rows].join('\r\n') + '\r\n';
}

export interface ExportJson {
  app: 'KhataVaani';
  exported_at: string;
  /** Amounts are whole rupees. Positive balance: the customer owes the shop. */
  entries: Entry[];
  totals: LedgerView['totals'];
  customers: Customer[];
}

export function ledgerJson(ledger: LedgerView, customers: readonly Customer[], exportedAt: string): string {
  const out: ExportJson = { app: 'KhataVaani', exported_at: exportedAt, entries: ledger.entries, totals: ledger.totals, customers: [...customers] };
  return JSON.stringify(out, null, 2);
}

export function exportFileName(ext: 'csv' | 'json', date: string): string {
  return `khatavaani-khata-${date}.${ext}`;
}

/** Saves `content` as a file through a temporary object URL. */
export function downloadFile(content: string, name: string, type: string): void {
  const prefix = type.startsWith('text/csv') ? '﻿' : ''; // BOM so spreadsheets read Devanagari names as UTF-8
  const url = URL.createObjectURL(new Blob([prefix + content], { type }));
  const a = document.createElement('a');
  a.href = url;
  a.download = name;
  a.rel = 'noopener';
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
