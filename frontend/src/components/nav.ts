// The four main destinations, shared by BottomTabs (mobile and tablet) and SideRail (desktop).
import { BookOpen, ChartColumn, Mic, SlidersVertical } from 'lucide-react';
import type { LabelKey } from '../i18n';

export interface NavItem {
  to: '/' | '/khata' | '/hisaab' | '/settings';
  labelKey: LabelKey;
  icon: typeof Mic;
  /** Exact match for "/" so it is not active on every route. */
  exact?: boolean;
}

export const NAV_ITEMS: NavItem[] = [
  { to: '/', labelKey: 'tabBolo', icon: Mic, exact: true },
  { to: '/khata', labelKey: 'tabKhata', icon: BookOpen },
  { to: '/hisaab', labelKey: 'tabHisaab', icon: ChartColumn },
  { to: '/settings', labelKey: 'tabSettings', icon: SlidersVertical },
];
