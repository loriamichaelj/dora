import { EmptyState } from '../components/States';

/** Placeholder until the management pages land (BOOO M9). */
export function ComingSoonPage({ title }: { title: string }) {
  return (
    <>
      <h1>{title}</h1>
      <EmptyState title="Coming soon">
        <p>This page is being built.</p>
      </EmptyState>
    </>
  );
}
