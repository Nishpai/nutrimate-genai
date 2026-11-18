import { useState, type FormEvent, type ReactNode } from "react"
import { Link, useLocation, useNavigate } from "react-router-dom"
import { Bot, CalendarDays, Loader2, ShieldCheck, Sparkles } from "lucide-react"
import { toast } from "sonner"
import { Logo } from "@/components/app/shell"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { useAuth } from "@/lib/auth"

function Layout({ title, subtitle, children }: { title: string; subtitle: string; children: ReactNode }) {
  return (
    <div className="grid min-h-svh lg:grid-cols-[1.05fr_1fr]">
      <div className="relative hidden overflow-hidden bg-gradient-to-br from-emerald-700 via-emerald-600 to-teal-600 p-10 text-white lg:flex lg:flex-col">
        <div className="bg-grid absolute inset-0 opacity-30" />
        <div className="absolute -right-24 -bottom-24 size-96 rounded-full bg-white/10 blur-3xl" />
        <div className="relative"><Logo light /></div>
        <div className="relative mt-auto max-w-md space-y-6">
          <h2 className="text-3xl leading-tight font-semibold">Personal food recommendations that respect your diet, every time.</h2>
          <div className="space-y-3 text-sm text-emerald-50">
            {[
              [<Sparkles key="a" className="size-4" />, "Hybrid recommender: content similarity, LightFM collaborative filtering and popularity"],
              [<ShieldCheck key="b" className="size-4" />, "Allergies and diet rules are applied before ranking, so they always win"],
              [<Bot key="c" className="size-4" />, "Ask questions in plain language; numbers come from the database, not the AI"],
              [<CalendarDays key="d" className="size-4" />, "Daily and weekly meal plans fitted to your calorie target"],
            ].map(([icon, text], i) => (
              <div key={i} className="flex gap-3"><div className="mt-0.5 flex size-7 shrink-0 items-center justify-center rounded-lg bg-white/15">{icon}</div><p>{text}</p></div>
            ))}
          </div>
        </div>
      </div>
      <div className="flex items-center justify-center p-6 sm:p-10">
        <div className="w-full max-w-sm">
          <div className="mb-8 lg:hidden"><Logo /></div>
          <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
          <p className="mt-1 mb-6 text-sm text-muted-foreground">{subtitle}</p>
          {children}
        </div>
      </div>
    </div>
  )
}

export function Login() {
  const { login } = useAuth()
  const nav = useNavigate()
  const loc = useLocation() as { state?: { from?: string } }
  const [email, setEmail] = useState("")
  const [password, setPassword] = useState("")
  const [busy, setBusy] = useState(false)
  const submit = async (e: FormEvent) => {
    e.preventDefault()
    setBusy(true)
    try {
      const u = await login(email, password)
      nav(u.onboarded ? loc.state?.from ?? "/dashboard" : "/onboarding", { replace: true })
    } catch (err) {
      toast.error((err as Error).message)
    } finally {
      setBusy(false)
    }
  }
  return (
    <Layout title="Welcome back" subtitle="Sign in to see your plan, log and recommendations.">
      <form onSubmit={submit} className="space-y-4">
        <div className="space-y-1.5"><Label htmlFor="email">Email</Label><Input id="email" type="email" autoComplete="email" required value={email} onChange={(e) => setEmail(e.target.value)} className="h-10" /></div>
        <div className="space-y-1.5"><Label htmlFor="password">Password</Label><Input id="password" type="password" autoComplete="current-password" required value={password} onChange={(e) => setPassword(e.target.value)} className="h-10" /></div>
        <Button type="submit" className="h-10 w-full" disabled={busy}>{busy && <Loader2 className="animate-spin" />}Sign in</Button>
      </form>
      <p className="mt-6 text-center text-sm text-muted-foreground">New here? <Link to="/register" className="font-medium text-primary hover:underline">Create an account</Link></p>
    </Layout>
  )
}

export function Register() {
  const { register } = useAuth()
  const nav = useNavigate()
  const [form, setForm] = useState({ name: "", email: "", password: "" })
  const [busy, setBusy] = useState(false)
  const submit = async (e: FormEvent) => {
    e.preventDefault()
    if (form.password.length < 8) return toast.error("Password must be at least 8 characters")
    setBusy(true)
    try {
      await register(form.name, form.email, form.password)
      nav("/onboarding", { replace: true })
    } catch (err) {
      toast.error((err as Error).message)
    } finally {
      setBusy(false)
    }
  }
  return (
    <Layout title="Create your account" subtitle="It takes a minute. Next we will ask about your diet and goals.">
      <form onSubmit={submit} className="space-y-4">
        <div className="space-y-1.5"><Label htmlFor="name">Full name</Label><Input id="name" required value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} className="h-10" /></div>
        <div className="space-y-1.5"><Label htmlFor="email">Email</Label><Input id="email" type="email" required value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} className="h-10" /></div>
        <div className="space-y-1.5"><Label htmlFor="password">Password</Label><Input id="password" type="password" required minLength={8} value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} className="h-10" /><p className="text-xs text-muted-foreground">At least 8 characters.</p></div>
        <Button type="submit" className="h-10 w-full" disabled={busy}>{busy && <Loader2 className="animate-spin" />}Create account</Button>
      </form>
      <p className="mt-6 text-center text-sm text-muted-foreground">Already have an account? <Link to="/login" className="font-medium text-primary hover:underline">Sign in</Link></p>
    </Layout>
  )
}
