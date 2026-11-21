// "/" : Bolo, the talk screen.
import { createFileRoute } from '@tanstack/react-router';
import { BoloScreen } from '../features/bolo/BoloScreen';

export const Route = createFileRoute('/')({ component: BoloScreen });
