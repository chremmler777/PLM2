/**
 * App - Main application component with routing
 */

import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { QueryClientProvider, QueryClient } from '@tanstack/react-query';
import { Toaster } from 'sonner';
import { AuthProvider, useAuth } from './contexts/AuthContext';
import { ThemeProvider } from './contexts/ThemeContext';
import ProjectsPage from './pages/ProjectsPage';
import ProjectDetailPage from './pages/ProjectDetailPage';
import PartDetail from './pages/PartDetail';
import WorkflowDesignerPage from './pages/WorkflowDesignerPage';
import MyTasksPage from './pages/MyTasksPage';
import CatalogPage from './pages/CatalogPage';
import UsersPage from './pages/UsersPage';
import Dashboard from './pages/Dashboard';
import SuppliersPage from './pages/SuppliersPage';
import LessonsLearnedPage from './pages/LessonsLearnedPage';
import LessonsKpiBoardPage from './pages/LessonsKpiBoardPage';
import ChangesPage from './pages/ChangesPage';
import ChangeDetailPage from './pages/ChangeDetailPage';
import ReportsPage from './pages/ReportsPage';
import PnlPage from './pages/PnlPage';
import AppLayout from './components/layout/AppLayout';

const queryClient = new QueryClient();

function ProtectedRoute({ children }: { children: React.ReactNode }) {
  const { isAuthenticated, loading } = useAuth();
  if (loading) return null; // or a spinner
  if (!isAuthenticated) {
    window.location.href = '/';
    return null;
  }
  return <AppLayout>{children}</AppLayout>;
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
      <Route
        path="/parts/:partId"
        element={
          <ProtectedRoute>
            <PartDetail />
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
      <Route
        path="/users"
        element={
          <ProtectedRoute>
            <UsersPage />
          </ProtectedRoute>
        }
      />
      <Route path="/" element={<Navigate to="/dashboard" />} />
    </Routes>
  );
}

export default function App() {
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
