import { useState, type ReactNode } from "react"
import { NavLink, Outlet, useLocation, useNavigate } from "react-router-dom"
import { useQuery } from "@tanstack/react-query"
import {
  BarChart3, Bot, CalendarDays, ChefHat, ClipboardList, Database, History, LayoutDashboard, LogOut, Menu,
  Search, Settings, ShieldCheck, Sparkles,
} from "lucide-react"
import { Avatar, AvatarFallback } from "@/components/ui/avatar"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuLabel, DropdownMenuSeparator, DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { Sheet, SheetContent, SheetTitle } from "@/components/ui/sheet"
import { api } from "@/lib/api"
import { useAuth } from "@/lib/auth"
import { cn } from "@/lib/utils"

type Item = { to: string; label: string; icon: ReactNode }
const GROUPS: { title: string; items: Item[]; admin?: boolean }[] = [
  { title: "Overview", items: [{ to: "/dashboard", label: "Dashboard", icon: <LayoutDashboard /> }] },
  {
    title: "Nutrition",
    items: [
      { to: "/recommendations", label: "For you", icon: <Sparkles /> },
      { to: "/assistant", label: "AI assistant", icon: <Bot /> },
      { to: "/planner", label: "Meal planner", icon: <CalendarDays /> },
      { to: "/explorer", label: "Food explorer", icon: <Search /> },
      { to: "/log", label: "Nutrition log", icon: <ClipboardList /> },
    ],
  },
  {
    title: "Account",
    items: [
      { to: "/history", label: "History", icon: <History /> },
      { to: "/settings", label: "Settings", icon: <Settings /> },
    ],
  },
  {
    title: "Admin", admin: true,
    items: [
      { to: "/admin", label: "Admin overview", icon: <ShieldCheck /> },
      { to: "/admin/datasets", label: "Datasets & jobs", icon: <Database /> },
      { to: "/admin/models", label: "Model performance", icon: <BarChart3 /> },
    ],
  },
]

export function Logo({ light }: { light?: boolean }) {
  return (
    <div className="flex items-center gap-2.5">
      <div className="flex size-9 items-center justify-center rounded-xl bg-gradient-to-br from-emerald-500 to-teal-600 text-white shadow-md shadow-emerald-600/20">
        <ChefHat className="size-5" />
      </div>
      <div className="leading-tight">
        <p className={cn("text-[15px] font-semibold tracking-tight", light && "text-white")}>NutriMate</p>
        <p className={cn("text-[11px] text-muted-foreground", light && "text-emerald-100")}>AI nutrition assistant</p>
      </div>
    </div>
  )
}

function Nav({ onNavigate }: { onNavigate?: () => void }) {
  const { user } = useAuth()
  return (
    <nav className="flex flex-1 flex-col gap-5 overflow-y-auto px-3 py-4">
      {GROUPS.filter((g) => !g.admin || user?.role === "admin").map((g) => (
        <div key={g.title}>
          <p className="mb-1.5 px-3 text-[11px] font-semibold tracking-wider text-muted-foreground/80 uppercase">{g.title}</p>
          <div className="flex flex-col gap-0.5">
            {g.items.map((it) => (
              <NavLink key={it.to} to={it.to} end={it.to === "/admin"} onClick={onNavigate}
                className={({ isActive }) => cn(
                  "flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium text-sidebar-foreground/80 transition [&_svg]:size-4",
                  isActive ? "bg-sidebar-accent text-sidebar-accent-foreground shadow-[inset_2px_0_0_var(--primary)]" : "hover:bg-muted hover:text-foreground",
                )}>
                {it.icon}{it.label}
              </NavLink>
            ))}
          </div>
        </div>
      ))}
    </nav>
  )
}

function SidebarFooter() {
  const status = useQuery({ queryKey: ["assistant-status"], queryFn: () => api<{ gemini: boolean; retriever: boolean; engine: boolean }>("/api/assistant/status"), staleTime: 60_000 })
  const s = status.data
  return (
    <div className="m-3 rounded-xl border bg-gradient-to-br from-emerald-50 to-white p-3 text-xs">
      <p className="mb-2 font-semibold text-emerald-900">System status</p>
      {[["Recommender", s?.engine], ["FAISS retrieval", s?.retriever], ["Gemini", s?.gemini]].map(([label, ok]) => (
        <div key={label as string} className="flex items-center justify-between py-0.5 text-muted-foreground">
          <span>{label}</span>
          <span className="flex items-center gap-1.5">
            <span className={cn("size-1.5 rounded-full", ok ? "bg-emerald-500" : s ? "bg-amber-500" : "bg-muted-foreground/40")} />
            {s ? (ok ? "online" : label === "Gemini" ? "fallback" : "loading") : "..."}
          </span>
        </div>
      ))}
    </div>
  )
}

const TITLES: Record<string, string> = {
  "/dashboard": "Dashboard", "/recommendations": "Recommendations", "/assistant": "AI assistant",
  "/planner": "Meal planner", "/explorer": "Food explorer", "/log": "Nutrition log", "/history": "History",
  "/settings": "Settings", "/admin": "Admin", "/admin/datasets": "Datasets & jobs", "/admin/models": "Model performance",
}

export function AppShell() {
  const [open, setOpen] = useState(false)
  const { user, logout } = useAuth()
  const nav = useNavigate()
  const loc = useLocation()
  const initials = (user?.full_name ?? "?").split(" ").map((p) => p[0]).slice(0, 2).join("").toUpperCase()
  return (
    <div className="flex min-h-svh bg-background">
      <aside className="sticky top-0 hidden h-svh w-64 shrink-0 flex-col border-r bg-sidebar lg:flex">
        <div className="flex h-16 items-center border-b px-5"><Logo /></div>
        <Nav />
        <SidebarFooter />
      </aside>
      <Sheet open={open} onOpenChange={setOpen}>
        <SheetContent side="left" className="w-72 gap-0 p-0">
          <SheetTitle className="sr-only">Navigation</SheetTitle>
          <div className="flex h-16 items-center border-b px-5"><Logo /></div>
          <Nav onNavigate={() => setOpen(false)} />
          <SidebarFooter />
        </SheetContent>
      </Sheet>
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-20 flex h-16 items-center gap-3 border-b bg-background/80 px-4 backdrop-blur sm:px-6">
          <Button variant="ghost" size="icon" className="lg:hidden" onClick={() => setOpen(true)} aria-label="Open menu"><Menu /></Button>
          <p className="text-sm font-medium text-muted-foreground">{TITLES[loc.pathname] ?? "NutriMate"}</p>
          <div className="ml-auto flex items-center gap-2">
            {user?.role === "admin" && <Badge variant="secondary" className="hidden sm:inline-flex">Admin</Badge>}
            <Button variant="outline" size="sm" className="hidden sm:inline-flex" onClick={() => nav("/assistant")}><Bot /> Ask NutriMate</Button>
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <button className="rounded-full outline-none focus-visible:ring-3 focus-visible:ring-ring/50" aria-label="Account menu">
                  <Avatar className="size-9 border"><AvatarFallback className="bg-secondary font-semibold text-primary">{initials}</AvatarFallback></Avatar>
                </button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end" className="w-56">
                <DropdownMenuLabel>
                  <p className="font-medium">{user?.full_name}</p>
                  <p className="text-xs font-normal text-muted-foreground">{user?.email}</p>
                </DropdownMenuLabel>
                <DropdownMenuSeparator />
                <DropdownMenuItem onClick={() => nav("/settings")}><Settings /> Settings</DropdownMenuItem>
                <DropdownMenuItem onClick={() => nav("/history")}><History /> History</DropdownMenuItem>
                <DropdownMenuSeparator />
                <DropdownMenuItem onClick={() => { logout(); nav("/login") }}><LogOut /> Sign out</DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          </div>
        </header>
        <main className="mx-auto w-full max-w-7xl flex-1 px-4 py-6 sm:px-6 lg:px-8">
          <Outlet />
        </main>
      </div>
    </div>
  )
}
