// "/khata" layout: the customer list, and the customer detail next to it on wider screens (features/khata).
import { createFileRoute } from '@tanstack/react-router';
import { KhataLayout } from '../features/khata/KhataLayout';

export const Route = createFileRoute('/khata')({ component: KhataLayout });
