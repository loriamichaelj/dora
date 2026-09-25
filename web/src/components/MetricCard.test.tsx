import { render, screen } from '@testing-library/react';

import { BandBadge } from './BandBadge';
import { MetricCard } from './MetricCard';

test('shows the value, band text, and sample detail', () => {
  render(
    <MetricCard
      title="Change fail rate"
      value="50.0%"
      band="low"
      detail="2 of 4 deployments caused a failure"
      definition="Share of deployments that caused a production failure."
    />,
  );
  const card = screen.getByRole('article', { name: 'Change fail rate' });
  expect(card).toHaveTextContent('50.0%');
  expect(card).toHaveTextContent('Low');
  expect(card).toHaveTextContent('Benchmark band: Low'); // spelled out for screen readers
  expect(card).toHaveTextContent('2 of 4 deployments caused a failure');
});

test('a null band says so in words', () => {
  render(<BandBadge band={null} />);
  expect(screen.getByText('No band')).toBeInTheDocument();
});

test('rework rate names why it has no band', () => {
  render(<BandBadge band={null} emptyLabel="No published benchmark" />);
  expect(screen.getByText('No published benchmark')).toBeInTheDocument();
});
