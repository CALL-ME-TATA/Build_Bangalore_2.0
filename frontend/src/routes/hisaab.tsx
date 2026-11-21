// "/hisaab" : insights (today / week totals, one bar chart, top dues, spoken summary).
import { createFileRoute } from '@tanstack/react-router';
import { HisaabScreen } from '../features/hisaab/HisaabScreen';

export const Route = createFileRoute('/hisaab')({ component: HisaabScreen });
