/**
 * App - Main application component with routing
 */

import { useEffect } from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { QueryClientProvider, QueryClient } from '@tanstack/react-query';
import { Toaster } from 'sonner';
import { AuthProvider, useAuth } from './contexts/AuthContext';
import { ThemeProvider } from './contexts/ThemeContext';
import ProjectsPage from './pages/ProjectsPage';
import ProjectDetailPage from './pages/ProjectDetailPage';
import ProjectDetailPopout from './pages/ProjectDetailPopout';
import PartDetail from './pages/PartDetail';
import DfmPopout from './pages/DfmPopout';
import WorkflowDesignerPage from './pages/WorkflowDesignerPage';
import MyTasksPage from './pages/MyTasksPage';
import CatalogPage from './pages/CatalogPage';
import PaintsPage from './pages/PaintsPage';
import Dashboard from './pages/Dashboard';
import SuppliersPage from './pages/SuppliersPage';
import LessonsLearnedPage from './pages/LessonsLearnedPage';
import LessonsKpiBoardPage from './pages/LessonsKpiBoardPage';
import ChangesPage from './pages/ChangesPage';
import ChangeDetailPage from './pages/ChangeDetailPage';
import ReportsPage from './pages/ReportsPage';
import PnlPage from './pages/PnlPage';
import ProcessMapPage from './pages/ProcessMapPage';
import AppLayout from './components/layout/AppLayout';

const queryClient = new QueryClient();

function ProtectedRoute({ children, bare = false }: { children: React.ReactNode; bare?: boolean }) {
  const { isAuthenticated, loading } = useAuth();
  if (loading) return null; // or a spinner
  if (!isAuthenticated) {
    window.location.href = '/';
    return null;
  }
  return bare ? <>{children}</> : <AppLayout>{children}</AppLayout>;
}

function AppRoutes() {
  return (
    <Routes>
      <Route
        path="/dashboard"
        element={
          <ProtectedRoute>
            <Dashboard />
          </ProtectedRoute>
        }
      />
      <Route
        path="/projects"
        element={
          <ProtectedRoute>
            <ProjectsPage />
          </ProtectedRoute>
        }
      />
      <Route
        path="/projects/:projectId"
        element={
          <ProtectedRoute>
            <ProjectDetailPage />
          </ProtectedRoute>
        }
      />
      {/* Pop-out detail window: the detail pane alone, no sidebar. */}
      <Route
        path="/projects/:projectId/detail"
        element={
          <ProtectedRoute bare>
            <ProjectDetailPopout />
          </ProtectedRoute>
        }
      />
      <Route
        path="/parts/:partId"
        element={
          <ProtectedRoute>
            <PartDetail />
          </ProtectedRoute>
        }
      />
      {/* Pop-out DFM window: a tool's DFM archive alone, no sidebar. */}
      <Route
        path="/parts/:partId/dfm"
        element={
          <ProtectedRoute bare>
            <DfmPopout />
          </ProtectedRoute>
        }
      />
      <Route
        path="/workflows"
        element={
          <ProtectedRoute>
            <WorkflowDesignerPage />
          </ProtectedRoute>
        }
      />
      <Route
        path="/my-tasks"
        element={
          <ProtectedRoute>
            <MyTasksPage />
          </ProtectedRoute>
        }
      />
      <Route
        path="/catalog"
        element={
          <ProtectedRoute>
            <CatalogPage />
          </ProtectedRoute>
        }
      />
      <Route
        path="/paints"
        element={
          <ProtectedRoute>
            <PaintsPage />
          </ProtectedRoute>
        }
      />
      <Route
        path="/suppliers"
        element={
          <ProtectedRoute>
            <SuppliersPage />
          </ProtectedRoute>
        }
      />
      <Route
        path="/lessons"
        element={
          <ProtectedRoute>
            <LessonsLearnedPage />
          </ProtectedRoute>
        }
      />
      <Route
        path="/lessons/kpis"
        element={
          <ProtectedRoute>
            <LessonsKpiBoardPage />
          </ProtectedRoute>
        }
      />
      <Route
        path="/changes"
        element={
          <ProtectedRoute>
            <ChangesPage />
          </ProtectedRoute>
        }
      />
      <Route
        path="/changes/:id"
        element={
          <ProtectedRoute>
            <ChangeDetailPage />
          </ProtectedRoute>
        }
      />
      <Route
        path="/reports"
        element={
          <ProtectedRoute>
            <ReportsPage />
          </ProtectedRoute>
        }
      />
      <Route
        path="/pnl"
        element={
          <ProtectedRoute>
            <PnlPage />
          </ProtectedRoute>
        }
      />
      {/* The ECR process map — the team's shared picture of the flow. */}
      <Route
        path="/process-map"
        element={
          <ProtectedRoute>
            <ProcessMapPage />
          </ProtectedRoute>
        }
      />
      <Route path="/" element={<Navigate to="/dashboard" />} />
    </Routes>
  );
}

export default function App() {
  // A file dropped anywhere outside an explicit drop zone would otherwise make
  // the browser navigate to open the file, blanking the SPA. Swallow stray
  // file-drops at the window level. Real drop zones still receive and handle
  // their own drop event; this only cancels the browser's default navigation.
  useEffect(() => {
    const swallow = (e: DragEvent) => {
      if (e.dataTransfer?.types?.includes('Files')) e.preventDefault();
    };
    window.addEventListener('dragover', swallow);
    window.addEventListener('drop', swallow);
    return () => {
      window.removeEventListener('dragover', swallow);
      window.removeEventListener('drop', swallow);
    };
  }, []);

  return (
    <QueryClientProvider client={queryClient}>
      <ThemeProvider>
        <AuthProvider>
          <BrowserRouter basename="/plm2">
            <AppRoutes />
            <Toaster position="top-right" />
          </BrowserRouter>
        </AuthProvider>
      </ThemeProvider>
    </QueryClientProvider>
  );
}
