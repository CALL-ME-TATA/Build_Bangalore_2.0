// "/settings" : language, voice speed, display, mic mode, shop name, reminder opt-ins, data export, demo.
import { createFileRoute } from '@tanstack/react-router';
import { SettingsScreen } from '../features/settings/SettingsScreen';

export const Route = createFileRoute('/settings')({ component: SettingsScreen });
