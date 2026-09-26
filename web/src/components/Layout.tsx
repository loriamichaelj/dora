import { Link, NavLink, Outlet } from 'react-router';

import { cx } from '../lib/cx';
import { DoraLogo, Icon, type IconName } from './Icon';
import styles from './Layout.module.css';
import { ThemeToggle } from './ThemeToggle';

const NAV: { to: string; label: string; icon: IconName; end: boolean }[] = [
  { to: '/', label: 'Dashboard', icon: 'dashboard', end: true },
  { to: '/services', label: 'Services', icon: 'services', end: false },
  { to: '/deployments', label: 'Deployments', icon: 'deployments', end: false },
  { to: '/failures', label: 'Failures', icon: 'failures', end: false },
];

export function Layout() {
  return (
    <div className={styles.app}>
      <a className={styles.skipLink} href="#main">
        Skip to content
      </a>
      <header className={styles.header}>
        <div className={styles.headerInner}>
          <Link to="/" className={styles.brand} aria-label="DORA Tracker home">
            <DoraLogo />
            <span className={styles.brandName}>DORA Tracker</span>
          </Link>
          <nav aria-label="Main" className={styles.navWrap}>
            <ul className={styles.nav}>
              {NAV.map((item) => (
                <li key={item.to}>
                  <NavLink
                    to={item.to}
                    end={item.end}
                    className={({ isActive }) => cx(styles.navLink, isActive && styles.active)}
                  >
                    <Icon name={item.icon} />
                    <span className={styles.navText}>{item.label}</span>
                  </NavLink>
                </li>
              ))}
            </ul>
          </nav>
          <div className={styles.actions}>
            <ThemeToggle />
            <Link to="/deployments/new" className={styles.cta}>
              <Icon name="plus" />
              <span className={styles.ctaText}>New deployment</span>
            </Link>
          </div>
        </div>
      </header>
      <main id="main" tabIndex={-1} className={styles.main}>
        <Outlet />
      </main>
    </div>
  );
}
