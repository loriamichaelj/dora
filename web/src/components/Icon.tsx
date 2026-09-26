/** A small inline icon set: 24px grid, 2px strokes, `currentColor`. Decorative only. */

const PATHS = {
  dashboard: 'M4 4h7v9H4zM13 4h7v5h-7zM13 11h7v9h-7zM4 15h7v5H4z',
  services: 'M4 4h16v6H4zM4 14h16v6H4zM8 7h.01M8 17h.01',
  deployments:
    'M5 15c-1.5 1.5-2 5-2 5s3.5-.5 5-2M9 15l-3-3 3-5c2.5-3.5 6.5-5 11-5 0 4.5-1.5 8.5-5 11l-6 2zM15 9h.01',
  failures: 'M12 3 2 20h20L12 3zM12 10v4M12 17h.01',
  plus: 'M12 5v14M5 12h14',
  search: 'M11 18a7 7 0 1 0 0-14 7 7 0 0 0 0 14zM20 20l-4-4',
  back: 'M19 12H5M11 6l-6 6 6 6',
  chart: 'M4 20V10M10 20V4M16 20v-7M22 20H2',
  resolve: 'M5 12l5 5 9-10',
  prev: 'M15 6l-6 6 6 6',
  next: 'M9 6l6 6-6 6',
  close: 'M6 6l12 12M18 6 6 18',
  sun: 'M12 16a4 4 0 1 0 0-8 4 4 0 0 0 0 8zM12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4',
  moon: 'M20 14.5A8 8 0 0 1 9.5 4 8 8 0 1 0 20 14.5z',
  system: 'M3 5h18v11H3zM8 20h8M12 16v4',
} as const;

export type IconName = keyof typeof PATHS;

export function Icon({ name, size = 16 }: { name: IconName; size?: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={2}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
      style={{ flex: 'none' }}
    >
      <path d={PATHS[name]} />
    </svg>
  );
}

/** The DORA mark: rising bars, for delivery getting better. */
export function DoraLogo({ size = 28 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" aria-hidden="true" focusable="false">
      <rect width="32" height="32" rx="8" fill="var(--color-primary)" />
      <g fill="var(--color-primary-text)">
        <rect x="8" y="17" width="3.5" height="7" rx="1.2" opacity="0.55" />
        <rect x="14.25" y="12.5" width="3.5" height="11.5" rx="1.2" opacity="0.8" />
        <rect x="20.5" y="8" width="3.5" height="16" rx="1.2" />
      </g>
    </svg>
  );
}
