// "/khata" : the ledger. On a phone the list is the whole screen; on wider screens this is the empty right pane.
import { createFileRoute } from '@tanstack/react-router';
import { KhataIndexPane } from '../features/khata/KhataLayout';
import { khataLabels } from '../features/khata/labels';
import { useSession } from '../state/session';

function KhataIndex() {
  const lang = useSession((s) => s.lang);
  return <KhataIndexPane text={khataLabels(lang).pickCustomer} />;
}

export const Route = createFileRoute('/khata/')({ component: KhataIndex });
