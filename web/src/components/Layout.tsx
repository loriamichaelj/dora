import { NavLink, Outlet } from 'react-router';

import styles from './Layout.module.css';

const NAV = [
  { to: '/', label: 'Dashboard', end: true },
  { to: '/services', label: 'Services', end: false },
  { to: '/deployments', label: 'Deployments', end: false },
  { to: '/failures', label: 'Failures', end: false },
];

export function Layout() {
  return (
    <div className={styles.app}>
      <header className={styles.header}>
        <span className={styles.brand}>DORA Deployment Tracker</span>
        <nav aria-label="Main">
          <ul className={styles.nav}>
            {NAV.map((item) => (
              <li key={item.to}>
                <NavLink
                  to={item.to}
                  end={item.end}
                  className={({ isActive }) => (isActive ? styles.active : undefined)}
                >
                  {item.label}
                </NavLink>
              </li>
            ))}
          </ul>
        </nav>
      </header>
      <main className={styles.main}>
        <Outlet />
      </main>
    </div>
  );
}
