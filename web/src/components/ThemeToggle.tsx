import { useEffect, useState } from 'react';

import { Icon, type IconName } from './Icon';
import styles from './Layout.module.css';

type Theme = 'system' | 'light' | 'dark';

export const THEME_STORAGE_KEY = 'dora-theme';
const NEXT: Record<Theme, Theme> = { system: 'light', light: 'dark', dark: 'system' };
const ICONS: Record<Theme, IconName> = { system: 'system', light: 'sun', dark: 'moon' };

function readTheme(): Theme {
  try {
    const stored = window.localStorage.getItem(THEME_STORAGE_KEY);
    return stored === 'light' || stored === 'dark' ? stored : 'system';
  } catch {
    return 'system';
  }
}

/** Cycles system -> light -> dark. index.html applies the saved choice before first paint. */
export function ThemeToggle() {
  const [theme, setTheme] = useState<Theme>(readTheme);

  useEffect(() => {
    const root = document.documentElement;
    if (theme === 'system') delete root.dataset.theme;
    else root.dataset.theme = theme;
    try {
      if (theme === 'system') window.localStorage.removeItem(THEME_STORAGE_KEY);
      else window.localStorage.setItem(THEME_STORAGE_KEY, theme);
    } catch {
      // Storage can be unavailable (private mode); the choice then lasts this visit.
    }
  }, [theme]);

  const label = `Theme: ${theme}. Switch to ${NEXT[theme]}.`;
  return (
    <button
      type="button"
      className={styles.iconButton}
      aria-label={label}
      title={label}
      onClick={() => {
        setTheme(NEXT[theme]);
      }}
    >
      <Icon name={ICONS[theme]} />
    </button>
  );
}
