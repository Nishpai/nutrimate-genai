import { lazy, Suspense, type ReactNode } from "react"
import { Navigate, Route, Routes, useLocation } from "react-router-dom"
import { Loader2 } from "lucide-react"
import { AppShell } from "@/components/app/shell"
import { useAuth } from "@/lib/auth"
const AdminDatasets = lazy(() => import("@/pages/admin/Datasets"))
const AdminModels = lazy(() => import("@/pages/admin/Models"))
const AdminOverview = lazy(() => import("@/pages/admin/Overview"))
const Assistant = lazy(() => import("@/pages/Assistant"))
const Login = lazy(() => import("@/pages/Auth").then((m) => ({ default: m.Login })))
const Register = lazy(() => import("@/pages/Auth").then((m) => ({ default: m.Register })))
const Dashboard = lazy(() => import("@/pages/Dashboard"))
const Explorer = lazy(() => import("@/pages/Explorer"))
const HistoryPage = lazy(() => import("@/pages/History"))
const NutritionLog = lazy(() => import("@/pages/NutritionLog"))
const Onboarding = lazy(() => import("@/pages/Onboarding"))
const Planner = lazy(() => import("@/pages/Planner"))
const Recommendations = lazy(() => import("@/pages/Recommendations"))
const SettingsPage = lazy(() => import("@/pages/Settings"))

function Splash() {
  return <div className="flex min-h-svh items-center justify-center"><Loader2 className="size-6 animate-spin text-primary" /></div>
}

function RequireAuth({ children, admin }: { children: ReactNode; admin?: boolean }) {
  const { user, loading } = useAuth()
  const loc = useLocation()
  if (loading) return <Splash />
  if (!user) return <Navigate to="/login" state={{ from: loc.pathname }} replace />
  if (!user.onboarded && loc.pathname !== "/onboarding") return <Navigate to="/onboarding" replace />
  if (admin && user.role !== "admin") return <Navigate to="/dashboard" replace />
  return <>{children}</>
}

function PublicOnly({ children }: { children: ReactNode }) {
  const { user, loading } = useAuth()
  if (loading) return <Splash />
  if (user) return <Navigate to={user.onboarded ? "/dashboard" : "/onboarding"} replace />
  return <>{children}</>
}

export default function App() {
  return (
    <Suspense fallback={<Splash />}>
    <Routes>
      <Route path="/login" element={<PublicOnly><Login /></PublicOnly>} />
      <Route path="/register" element={<PublicOnly><Register /></PublicOnly>} />
      <Route path="/onboarding" element={<RequireAuth><Onboarding /></RequireAuth>} />
      <Route element={<RequireAuth><AppShell /></RequireAuth>}>
        <Route path="/dashboard" element={<Dashboard />} />
        <Route path="/recommendations" element={<Recommendations />} />
        <Route path="/assistant" element={<Assistant />} />
        <Route path="/planner" element={<Planner />} />
        <Route path="/explorer" element={<Explorer />} />
        <Route path="/log" element={<NutritionLog />} />
        <Route path="/history" element={<HistoryPage />} />
        <Route path="/settings" element={<SettingsPage />} />
        <Route path="/admin" element={<RequireAuth admin><AdminOverview /></RequireAuth>} />
        <Route path="/admin/datasets" element={<RequireAuth admin><AdminDatasets /></RequireAuth>} />
        <Route path="/admin/models" element={<RequireAuth admin><AdminModels /></RequireAuth>} />
      </Route>
      <Route path="*" element={<Navigate to="/dashboard" replace />} />
    </Routes>
    </Suspense>
  )
}
