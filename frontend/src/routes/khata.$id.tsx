// "/khata/$id" : one customer's khata. `id` is the customer id from GET /api/customers.
import { createFileRoute } from '@tanstack/react-router';
import { CustomerDetail } from '../features/customer/CustomerDetail';

function CustomerRoute() {
  const { id } = Route.useParams();
  return <CustomerDetail key={id} id={id} />;
}

export const Route = createFileRoute('/khata/$id')({ component: CustomerRoute });
