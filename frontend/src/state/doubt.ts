// Doubt sheet state (Zustand), driven by session results through the pure sheetReduce in lib/doubtSheet.ts.
// Mount useDoubtSync() once in the root layout.
import { useEffect } from 'react';
import { create } from 'zustand';
import { sheetClosed, sheetReduce, type SheetEvent, type SheetState } from '../lib/doubtSheet';
import { useSession } from './session';

export const useDoubt = create<SheetState>()(() => sheetClosed);

export function doubtDispatch(e: SheetEvent): void {
  useDoubt.setState(sheetReduce(useDoubt.getState(), e), true);
}

/** Feeds every new `result` of the session into the sheet. */
export function useDoubtSync(): void {
  useEffect(
    () =>
      useSession.subscribe((s, prev) => {
        if (s.resultCount === prev.resultCount || !s.result) return;
        doubtDispatch({
          type: 'result',
          turnId: s.turnId,
          status: s.result.status,
          reason: s.result.reason,
          question: s.result.question,
          entries: s.result.entries,
          replyText: s.result.replyText,
          lang: s.lang,
          said: s.transcript,
          candidates: s.result.candidates,
          confirm: s.result.confirm,
        });
      }),
    [],
  );
}
