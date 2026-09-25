import type { RouteObject } from 'react-router';

import { Layout } from './components/Layout';
import { DashboardPage } from './pages/DashboardPage';
import { DeploymentDetailPage } from './pages/DeploymentDetailPage';
import { DeploymentNewPage } from './pages/DeploymentNewPage';
import { DeploymentsPage } from './pages/DeploymentsPage';
import { FailuresPage } from './pages/FailuresPage';
import { NotFoundPage } from './pages/NotFoundPage';
import { ServiceDetailPage } from './pages/ServiceDetailPage';
import { ServicesPage } from './pages/ServicesPage';

export const routes: RouteObject[] = [
  {
    element: <Layout />,
    children: [
      { index: true, element: <DashboardPage /> },
      { path: 'services', element: <ServicesPage /> },
      { path: 'services/:serviceId', element: <ServiceDetailPage /> },
      { path: 'deployments', element: <DeploymentsPage /> },
      { path: 'deployments/new', element: <DeploymentNewPage /> },
      { path: 'deployments/:deploymentId', element: <DeploymentDetailPage /> },
      { path: 'failures', element: <FailuresPage /> },
      { path: '*', element: <NotFoundPage /> },
    ],
  },
];
