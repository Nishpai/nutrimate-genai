import { useState } from "react"
import { Link } from "react-router-dom"
import { useQuery } from "@tanstack/react-query"
import { Area, AreaChart, Bar, BarChart, CartesianGrid, Cell, Pie, PieChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts"
import { Bot, CalendarDays, ClipboardList, Flame, Plus, Sparkles, Target } from "lucide-react"
import { PageHeader, SectionTitle } from "@/components/app/page-header"
import { MacroBar, StatCard } from "@/components/app/stat"
import { EmptyState, ErrorState, LoadingGrid } from "@/components/app/states"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card"
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group"
import { api } from "@/lib/api"
import { useAuth } from "@/lib/auth"
import { fmt, MACRO_COLORS, shortDate, titleCase } from "@/lib/format"
import type { Nutrients } from "@/lib/types"

type Day = Nutrients & { date: string; logged: boolean }
export type DashboardData = {
  range: { start: string; end: string; days: number }
  targets: Nutrients
  today: Day
  today_percent: Record<keyof Nutrients, number | null>
  series: Day[]
  averages: Nutrients
  days_logged: number
  days_within_10pct: number | null
  energy_split: { protein: number; carbs: number; fat: number } | null
  by_slot: { slot: string; kcal: number }[]
  top_items: { item_name: string; item_type: string; times: number; kcal: number | null }[]
  counts: { plans: number; likes: number; questions: number }
  streak_days: number
}

const tip = { contentStyle: { borderRadius: 10, border: "1px solid var(--border)", fontSize: 12 } }

export default function Dashboard() {
  const [days, setDays] = useState("14")
  const { user } = useAuth()
  const q = useQuery({ queryKey: ["dashboard", days], queryFn: () => api<DashboardData>(`/api/dashboard?days=${days}`) })
  const d = q.data
  const hour = new Date().getHours()
  const greet = hour < 12 ? "Good morning" : hour < 17 ? "Good afternoon" : "Good evening"
  return (
    <>
      <PageHeader eyebrow={new Date().toLocaleDateString(undefined, { weekday: "long", month: "long", day: "numeric" })}
        title={`${greet}, ${user?.full_name.split(" ")[0]}`}
        description="Your intake against your targets, computed from your nutrition log."
        actions={<>
          <ToggleGroup type="single" variant="outline" size="sm" value={days} onValueChange={(v) => v && setDays(v)}>
            <ToggleGroupItem value="7">7d</ToggleGroupItem><ToggleGroupItem value="14">14d</ToggleGroupItem><ToggleGroupItem value="30">30d</ToggleGroupItem>
          </ToggleGroup>
          <Button asChild size="sm"><Link to="/log"><Plus /> Log food</Link></Button>
        </>} />
      {q.isLoading && <LoadingGrid count={4} className="lg:grid-cols-4" itemClass="h-24" />}
      {q.isError && <ErrorState error={q.error} onRetry={() => q.refetch()} />}
      {d && (
        <div className="space-y-6">
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <StatCard label="Calories today" value={`${fmt(d.today.calories_kcal)} kcal`} sub={`of ${fmt(d.targets.calories_kcal)} kcal target`} ring={d.today_percent.calories_kcal} color={MACRO_COLORS.calories_kcal} />
            <StatCard label="Protein today" value={`${fmt(d.today.protein_g)} g`} sub={`of ${fmt(d.targets.protein_g)} g target`} ring={d.today_percent.protein_g} color={MACRO_COLORS.protein_g} />
            <StatCard icon={<Flame className="size-5" />} label="Logging streak" value={`${d.streak_days} day${d.streak_days === 1 ? "" : "s"}`} sub={`${d.days_logged} of ${d.range.days} days logged`} />
            <StatCard icon={<Target className="size-5" />} label="Days on target" value={d.days_within_10pct === null ? "n/a" : `${d.days_within_10pct} / ${d.days_logged}`} sub="within 10% of calorie target" />
          </div>

          <div className="grid gap-6 lg:grid-cols-3">
            <Card className="lg:col-span-2">
              <CardHeader><CardTitle>Calories per day</CardTitle><CardDescription>Dashed line is your target. Days with no log show as zero.</CardDescription></CardHeader>
              <CardContent className="h-72 pl-0">
                <ResponsiveContainer width="100%" height="100%">
                  <AreaChart data={d.series} margin={{ left: 0, right: 12 }}>
                    <defs><linearGradient id="kcal" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="var(--chart-1)" stopOpacity={0.35} /><stop offset="100%" stopColor="var(--chart-1)" stopOpacity={0} /></linearGradient></defs>
                    <CartesianGrid vertical={false} strokeDasharray="3 3" stroke="var(--border)" />
                    <XAxis dataKey="date" tickFormatter={shortDate} tickLine={false} axisLine={false} fontSize={11} minTickGap={16} />
                    <YAxis tickLine={false} axisLine={false} fontSize={11} width={48} />
                    <Tooltip {...tip} labelFormatter={(l) => shortDate(String(l))} formatter={(v) => [`${fmt(Number(v))} kcal`, "Calories"]} />
                    {d.targets.calories_kcal && <ReferenceLine y={d.targets.calories_kcal} stroke="var(--chart-2)" strokeDasharray="6 4" />}
                    <Area type="monotone" dataKey="calories_kcal" stroke="var(--chart-1)" strokeWidth={2} fill="url(#kcal)" />
                  </AreaChart>
                </ResponsiveContainer>
              </CardContent>
            </Card>
            <Card>
              <CardHeader><CardTitle>Today's macros</CardTitle><CardDescription>Logged so far against your targets.</CardDescription></CardHeader>
              <CardContent className="space-y-4">
                <MacroBar label="Protein" value={d.today.protein_g} target={d.targets.protein_g} unit="g" color={MACRO_COLORS.protein_g} />
                <MacroBar label="Carbs" value={d.today.carbs_g} target={d.targets.carbs_g} unit="g" color={MACRO_COLORS.carbs_g} />
                <MacroBar label="Fat" value={d.today.fat_g} target={d.targets.fat_g} unit="g" color={MACRO_COLORS.fat_g} />
                <MacroBar label="Fibre" value={d.today.fiber_g} target={d.targets.fiber_g} unit="g" color={MACRO_COLORS.fiber_g} />
                {!d.today.logged && <p className="rounded-lg bg-muted/60 p-3 text-xs text-muted-foreground">Nothing logged today yet.</p>}
              </CardContent>
            </Card>
          </div>

          <div className="grid gap-6 lg:grid-cols-3">
            <Card>
              <CardHeader><CardTitle>Energy split</CardTitle><CardDescription>Average share of calories from each macro on logged days.</CardDescription></CardHeader>
              <CardContent className="h-56">
                {d.energy_split ? (
                  <div className="flex h-full items-center gap-4">
                    <ResponsiveContainer width="55%" height="100%">
                      <PieChart>
                        <Pie data={[{ n: "Protein", v: d.energy_split.protein }, { n: "Carbs", v: d.energy_split.carbs }, { n: "Fat", v: d.energy_split.fat }]} dataKey="v" nameKey="n" innerRadius={48} outerRadius={78} paddingAngle={3} strokeWidth={0}>
                          {[MACRO_COLORS.protein_g, MACRO_COLORS.carbs_g, MACRO_COLORS.fat_g].map((c) => <Cell key={c} fill={c} />)}
                        </Pie>
                        <Tooltip {...tip} formatter={(v) => `${v}%`} />
                      </PieChart>
                    </ResponsiveContainer>
                    <div className="space-y-2 text-sm">
                      {(["protein", "carbs", "fat"] as const).map((k) => (
                        <div key={k} className="flex items-center gap-2"><span className="size-2.5 rounded-full" style={{ background: MACRO_COLORS[`${k}_g`] }} />{titleCase(k)} <b className="ml-auto pl-3">{d.energy_split![k]}%</b></div>
                      ))}
                    </div>
                  </div>
                ) : <EmptyState title="No logs in this range" className="h-full p-4" />}
              </CardContent>
            </Card>
            <Card>
              <CardHeader><CardTitle>Calories by meal</CardTitle><CardDescription>Total over the selected range.</CardDescription></CardHeader>
              <CardContent className="h-56 pl-0">
                {d.by_slot.length ? (
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart data={["breakfast", "lunch", "snack", "dinner"].map((s) => ({ slot: titleCase(s), kcal: d.by_slot.find((x) => x.slot === s)?.kcal ?? 0 }))}>
                      <CartesianGrid vertical={false} strokeDasharray="3 3" stroke="var(--border)" />
                      <XAxis dataKey="slot" tickLine={false} axisLine={false} fontSize={11} />
                      <YAxis tickLine={false} axisLine={false} fontSize={11} width={48} />
                      <Tooltip {...tip} formatter={(v) => [`${fmt(Number(v))} kcal`, "Calories"]} />
                      <Bar dataKey="kcal" fill="var(--chart-1)" radius={[6, 6, 0, 0]} />
                    </BarChart>
                  </ResponsiveContainer>
                ) : <EmptyState title="No logs in this range" className="ml-6 h-full p-4" />}
              </CardContent>
            </Card>
            <Card>
              <CardHeader><CardTitle>Most logged</CardTitle><CardDescription>Your most frequent items in this range.</CardDescription></CardHeader>
              <CardContent className="space-y-3">
                {d.top_items.length ? d.top_items.map((t, i) => (
                  <div key={t.item_name} className="flex items-center gap-3 text-sm">
                    <span className="flex size-6 items-center justify-center rounded-md bg-secondary text-xs font-semibold text-primary">{i + 1}</span>
                    <span className="min-w-0 flex-1 truncate">{t.item_name}</span>
                    <span className="text-xs text-muted-foreground">{t.times}x</span>
                  </div>
                )) : <EmptyState title="Nothing logged yet" className="p-4" />}
              </CardContent>
            </Card>
          </div>

          <div>
            <SectionTitle title="Quick actions" />
            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
              {[
                { to: "/recommendations", icon: <Sparkles />, title: "Get recommendations", sub: `${d.counts.likes} liked recipes shape your feed`, k: "rec" },
                { to: "/planner", icon: <CalendarDays />, title: "Plan your week", sub: `${d.counts.plans} saved plan${d.counts.plans === 1 ? "" : "s"}`, k: "plan" },
                { to: "/assistant", icon: <Bot />, title: "Ask the assistant", sub: `${d.counts.questions} questions asked`, k: "ask" },
                { to: "/log", icon: <ClipboardList />, title: "Log a meal", sub: `Average ${fmt(d.averages.calories_kcal)} kcal on logged days`, k: "log" },
              ].map((a) => (
                <Link key={a.k} to={a.to} className="group rounded-xl border bg-card p-4 transition hover:border-primary/40 hover:shadow-md hover:shadow-emerald-900/5">
                  <div className="mb-3 flex size-9 items-center justify-center rounded-lg bg-secondary text-primary transition group-hover:bg-primary group-hover:text-primary-foreground [&_svg]:size-4">{a.icon}</div>
                  <p className="font-medium">{a.title}</p>
                  <p className="text-xs text-muted-foreground">{a.sub}</p>
                </Link>
              ))}
            </div>
          </div>
        </div>
      )}
    </>
  )
}
