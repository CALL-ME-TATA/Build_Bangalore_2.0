// Labels in the current language: the session language, which follows the latest result's `lang`.
import { labels, type Labels, type Lang } from '../i18n';
import { useSession } from '../state/session';

export function useLang(): Lang {
  return useSession((s) => s.lang);
}

export function useLabels(): Labels {
  return labels(useLang());
}
