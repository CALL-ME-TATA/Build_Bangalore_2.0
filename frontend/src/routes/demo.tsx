// "/demo" : one button auto-plays the pitch flow on the scripted mock session (never the real server).
import { createFileRoute } from '@tanstack/react-router';
import { DemoScreen } from '../features/demo/DemoScreen';

export const Route = createFileRoute('/demo')({ component: DemoScreen });
