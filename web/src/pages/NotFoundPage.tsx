import { Link } from 'react-router';

import { EmptyState } from '../components/States';

export function NotFoundPage() {
  return (
    <EmptyState title="Page not found">
      <p>
        <Link to="/">Go to the dashboard</Link>
      </p>
    </EmptyState>
  );
}
