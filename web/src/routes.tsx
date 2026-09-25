import type { RouteObject } from 'react-router';

import { Layout } from './components/Layout';
import { ComingSoonPage } from './pages/ComingSoonPage';
import { DashboardPage } from './pages/DashboardPage';
import { NotFoundPage } from './pages/NotFoundPage';

export const routes: RouteObject[] = [
  {
    element: <Layout />,
    children: [
      { index: true, element: <DashboardPage /> },
      { path: 'services/*', element: <ComingSoonPage title="Services" /> },
      { path: 'deployments/*', element: <ComingSoonPage title="Deployments" /> },
      { path: 'failures/*', element: <ComingSoonPage title="Failures" /> },
      { path: '*', element: <NotFoundPage /> },
    ],
  },
];
