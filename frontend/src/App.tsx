import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { isLoggedIn } from './api'
import LoginPage from './pages/LoginPage'
import ProjectsPage from './pages/ProjectsPage'
import ProjectDetailPage from './pages/ProjectDetailPage'
import CallDetailPage from './pages/CallDetailPage'
import CallsPage from './pages/CallsPage'
import ManagersPage from './pages/ManagersPage'
import ManagerDetailPage from './pages/ManagerDetailPage'
import AnalyticsPage from './pages/AnalyticsPage'
import ManagerRankingPage from './pages/ManagerRankingPage'
import Layout from './components/Layout'

function RequireAuth({ children }: { children: React.ReactNode }) {
  return isLoggedIn() ? <>{children}</> : <Navigate to="/login" replace />
}

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route
          path="/"
          element={
            <RequireAuth>
              <Layout />
            </RequireAuth>
          }
        >
          <Route index element={<Navigate to="/projects" replace />} />
          <Route path="projects" element={<ProjectsPage />} />
          <Route path="projects/:id" element={<ProjectDetailPage />} />
          <Route path="calls" element={<CallsPage />} />
          <Route path="calls/:id" element={<CallDetailPage />} />
          <Route path="managers" element={<ManagersPage />} />
          <Route path="managers/:id" element={<ManagerDetailPage />} />
          <Route path="analytics" element={<AnalyticsPage />} />
          <Route path="analytics/ranking" element={<ManagerRankingPage />} />
        </Route>
      </Routes>
    </BrowserRouter>
  )
}
