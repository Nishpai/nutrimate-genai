import { useState } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Bar, BarChart, CartesianGrid, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts"
import { CalendarDays, CalendarPlus, ClipboardCheck, Eye, Loader2, RefreshCw, Save, ShieldCheck, Sparkles, Trash2, Wand2 } from "lucide-react"
import { toast } from "sonner"
import { PageHeader, SectionTitle } from "@/components/app/page-header"
import { RecipeDialog } from "@/components/app/recipe"
import { EmptyState, ErrorState, LoadingGrid } from "@/components/app/states"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Switch } from "@/components/ui/switch"
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group"
import { api } from "@/lib/api"
import { dateTime, dayName, fmt, shortDate } from "@/lib/format"
import type { Plan, PlanDay } from "@/lib/types"
import { cn } from "@/lib/utils"

type SavedPlan = { id: number; name: string; start_date: string; days: number; summary: Plan["summary"]; narrative_mode: string; created_at: string }
const tip = { contentStyle: { borderRadius: 10, border: "1px solid var(--border)", fontSize: 12 } }

function DayCard({ day, onSwap, swapping, onOpen, onLog }: {
  day: PlanDay; onSwap?: (slot: string) => void; swapping?: string | null; onOpen: (id: number) => void; onLog?: () => void
}) {
  const diff = day.kcal_diff_pct
  return (
    <Card className="gap-0 py-0">
      <div className="flex items-center justify-between border-b px-4 py-3">
        <div><p className="font-semibold">{dayName(day.date)}</p><p className="text-xs text-muted-foreground">{fmt(day.totals.calories_kcal)} kcal, {fmt(day.totals.protein_g)} g protein</p></div>
        <div className="flex items-center gap-1">
          {diff !== undefined && <Badge variant="outline" className={cn(Math.abs(diff) <= 10 ? "border-emerald-300 text-emerald-700" : "border-amber-300 text-amber-700")}>{diff > 0 ? "+" : ""}{diff}%</Badge>}
          {onLog && <Button size="sm" variant="ghost" onClick={onLog}><ClipboardCheck /> Log</Button>}
        </div>
      </div>
      <div className="divide-y">
        {day.meals.map((m) => (
          <div key={m.slot + m.recipe.recipe_id} className="flex items-start gap-3 px-4 py-3">
            <div className="w-16 shrink-0 pt-0.5 text-[11px] font-semibold tracking-wide text-primary uppercase">{m.slot}</div>
            <button className="min-w-0 flex-1 text-left" onClick={() => onOpen(m.recipe.recipe_id)}>
              <p className="line-clamp-2 text-sm leading-snug font-medium hover:text-primary">{m.recipe.name}</p>
              <p className="mt-0.5 text-xs text-muted-foreground">{m.servings} serving{m.servings === 1 ? "" : "s"} · {fmt(m.nutrition.calories_kcal)} kcal · {fmt(m.nutrition.protein_g)} g protein{m.recipe.cuisine && m.recipe.cuisine !== "Unspecified" ? ` · ${m.recipe.cuisine}` : ""}</p>
              {m.added_to_reach_target && <Badge variant="secondary" className="mt-1 h-4 text-[10px]">added to reach target</Badge>}
              {m.breakfast_fallback && <Badge variant="outline" className="mt-1 h-4 border-amber-300 text-[10px] text-amber-700" title="Few breakfast recipes pass your rules, so a light dish not tagged as breakfast was used">fallback breakfast</Badge>}
            </button>
            {onSwap && (
              <Button size="icon-sm" variant="ghost" aria-label={`Swap ${m.slot}`} disabled={!!swapping} onClick={() => onSwap(m.slot)}>
                {swapping === m.slot ? <Loader2 className="animate-spin" /> : <RefreshCw />}
              </Button>
            )}
          </div>
        ))}
      </div>
    </Card>
  )
}

function Summary({ plan }: { plan: Plan }) {
  const s = plan.summary
  return (
    <div className="grid gap-4 lg:grid-cols-3">
      <Card className="lg:col-span-2">
        <CardHeader><CardTitle>Calories per day</CardTitle><CardDescription>Target {fmt(s.target_kcal)} kcal. {s.days_within_10pct} of {s.days} days within 10%, largest gap {s.max_abs_kcal_diff_pct}%.</CardDescription></CardHeader>
        <CardContent className="h-56 pl-0">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={plan.days.map((d) => ({ day: shortDate(d.date), kcal: d.totals.calories_kcal, protein: d.totals.protein_g }))}>
              <CartesianGrid vertical={false} strokeDasharray="3 3" stroke="var(--border)" />
              <XAxis dataKey="day" tickLine={false} axisLine={false} fontSize={11} />
              <YAxis tickLine={false} axisLine={false} fontSize={11} width={48} />
              <Tooltip {...tip} formatter={(v, n) => [`${fmt(Number(v))}${n === "kcal" ? " kcal" : " g"}`, n === "kcal" ? "Calories" : "Protein"]} />
              <ReferenceLine y={s.target_kcal} stroke="var(--chart-2)" strokeDasharray="6 4" />
              <Bar dataKey="kcal" fill="var(--chart-1)" radius={[6, 6, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </CardContent>
      </Card>
      <Card>
        <CardHeader><CardTitle className="flex items-center gap-2"><Sparkles className="size-4 text-primary" /> Plan overview</CardTitle>
          <CardDescription>{plan.narrative_mode === "gemini" ? "Written by Gemini from the computed plan; numbers checked." : "Template summary from the computed plan."}</CardDescription></CardHeader>
        <CardContent className="space-y-3 text-sm">
          {plan.narrative && <p className="leading-relaxed">{plan.narrative}</p>}
          <div className="grid grid-cols-2 gap-2 text-center">
            <div className="rounded-lg bg-muted/50 p-2"><p className="text-lg font-semibold">{fmt(s.avg_kcal)}</p><p className="text-[11px] text-muted-foreground">avg kcal / day</p></div>
            <div className="rounded-lg bg-muted/50 p-2"><p className="text-lg font-semibold">{fmt(s.avg_protein_g)} g</p><p className="text-[11px] text-muted-foreground">avg protein / day</p></div>
          </div>
          {plan.rules && plan.rules.length > 0 && <div className="flex flex-wrap gap-1"><ShieldCheck className="size-4 text-emerald-600" />{plan.rules.map((r) => <Badge key={r} variant="outline" className="text-[11px]">{r}</Badge>)}</div>}
        </CardContent>
      </Card>
    </div>
  )
}

export default function Planner() {
  const qc = useQueryClient()
  const [days, setDays] = useState("1")
  const [narr, setNarr] = useState(true)
  const [kcal, setKcal] = useState("")
  const [plan, setPlan] = useState<Plan | null>(null)
  const [swapping, setSwapping] = useState<string | null>(null)
  const [saveOpen, setSaveOpen] = useState(false)
  const [name, setName] = useState("")
  const [viewing, setViewing] = useState<number | null>(null)
  const [open, setOpen] = useState<number | null>(null)
  const saved = useQuery({ queryKey: ["plans"], queryFn: () => api<SavedPlan[]>("/api/planner/plans") })
  const detail = useQuery({ queryKey: ["plan", viewing], queryFn: () => api<Plan>(`/api/planner/plans/${viewing}`), enabled: viewing !== null })
  const gen = useMutation({
    mutationFn: () => api<Plan>("/api/planner/generate", { body: { days: Number(days), with_narrative: narr, calorie_target: kcal ? Number(kcal) : null } }),
    onSuccess: (p) => { setPlan(p); setViewing(null) },
    onError: (e) => toast.error((e as Error).message),
  })
  const swap = async (dayIndex: number, slot: string) => {
    if (!plan) return
    setSwapping(`${dayIndex}:${slot}`)
    try {
      const p = await api<Plan>("/api/planner/swap", { body: { plan, day_index: dayIndex, slot } })
      setPlan({ ...p, narrative: plan.narrative, narrative_mode: plan.narrative_mode })
      toast.success(`Swapped ${slot}`)
    } catch (e) {
      toast.error((e as Error).message)
    } finally {
      setSwapping(null)
    }
  }
  const save = useMutation({
    mutationFn: () => api<{ id: number }>("/api/planner/save", { body: { plan, name: name.trim() || "My meal plan" } }),
    onSuccess: (r) => { setSaveOpen(false); qc.invalidateQueries({ queryKey: ["plans"] }); qc.invalidateQueries({ queryKey: ["dashboard"] }); toast.success("Plan saved"); setPlan(null); setViewing(r.id) },
    onError: (e) => toast.error((e as Error).message),
  })
  const del = useMutation({
    mutationFn: (id: number) => api(`/api/planner/plans/${id}`, { method: "DELETE" }),
    onSuccess: (_d, id) => { qc.invalidateQueries({ queryKey: ["plans"] }); if (viewing === id) setViewing(null); toast.success("Plan deleted") },
  })
  const logDay = useMutation({
    mutationFn: (v: { id: number; day_index: number }) => api<{ logged: number; date: string }>(`/api/planner/plans/${v.id}/log`, { body: { day_index: v.day_index } }),
    onSuccess: (r) => { qc.invalidateQueries({ queryKey: ["dashboard"] }); qc.invalidateQueries({ queryKey: ["logs"] }); toast.success(`Logged ${r.logged} meals for today`) },
    onError: (e) => toast.error((e as Error).message),
  })
  const shown = plan ?? detail.data ?? null
  return (
    <>
      <PageHeader eyebrow="AI meal planner" title="Meal planner"
        description="Plans use only recipes that pass your rules, ranked by your recommender, with portions fitted to your calorie target in Python."
        actions={plan && <Button onClick={() => { setName(Number(days) > 1 ? "Weekly plan" : "Daily plan"); setSaveOpen(true) }}><Save /> Save plan</Button>} />
      <Card className="mb-6 py-4">
        <CardContent className="flex flex-wrap items-end gap-4 px-4">
          <div className="space-y-1"><Label className="text-xs">Length</Label>
            <ToggleGroup type="single" variant="outline" value={days} onValueChange={(v) => v && setDays(v)}>
              <ToggleGroupItem value="1" className="px-4">One day</ToggleGroupItem><ToggleGroupItem value="7" className="px-4">One week</ToggleGroupItem>
            </ToggleGroup></div>
          <div className="space-y-1"><Label className="text-xs">Calorie target</Label><Input type="number" className="w-36" placeholder="From profile" value={kcal} onChange={(e) => setKcal(e.target.value)} /></div>
          <label className="flex items-center gap-2 pb-2 text-sm"><Switch checked={narr} onCheckedChange={setNarr} /> AI overview</label>
          <Button className="ml-auto" onClick={() => gen.mutate()} disabled={gen.isPending}>{gen.isPending ? <Loader2 className="animate-spin" /> : <Wand2 />} Generate plan</Button>
        </CardContent>
      </Card>

      {gen.isPending && <LoadingGrid count={Number(days) > 1 ? 6 : 3} className="md:grid-cols-2 xl:grid-cols-3" itemClass="h-64" />}
      {!gen.isPending && viewing !== null && detail.isLoading && <LoadingGrid count={3} className="md:grid-cols-3" itemClass="h-64" />}
      {detail.isError && <ErrorState error={detail.error} />}
      {!gen.isPending && shown && (
        <div className="space-y-5">
          {!plan && detail.data && (
            <div className="flex flex-wrap items-center justify-between gap-2 rounded-xl border bg-secondary/40 px-4 py-3 text-sm">
              <span>Viewing saved plan <b>{detail.data.name}</b>. Use Log on a day to add its meals to today's log.</span>
              <Button size="sm" variant="ghost" onClick={() => setViewing(null)}>Close</Button>
            </div>
          )}
          <Summary plan={shown} />
          {shown.breakfast_note && <div className="rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">{shown.breakfast_note}</div>}
          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
            {shown.days.map((d) => (
              <DayCard key={d.day_index} day={d} onOpen={setOpen}
                onSwap={plan ? (slot) => swap(d.day_index, slot) : undefined}
                swapping={swapping?.startsWith(`${d.day_index}:`) ? swapping.split(":")[1] : swapping ? "busy" : null}
                onLog={!plan && shown.id ? () => logDay.mutate({ id: shown.id!, day_index: d.day_index }) : undefined} />
            ))}
          </div>
        </div>
      )}
      {!gen.isPending && !shown && viewing === null && (
        <EmptyState icon={<CalendarDays className="size-5" />} title="No plan yet" description="Choose a length and generate. You can swap any meal, then save the plan." action={<Button onClick={() => gen.mutate()}><Wand2 /> Generate a plan</Button>} />
      )}

      <div className="mt-10">
        <SectionTitle title="Saved plans" description="Plans are stored in MySQL with their per-meal nutrition." />
        {saved.isLoading && <LoadingGrid count={3} className="md:grid-cols-3" itemClass="h-24" />}
        {saved.isError && <ErrorState error={saved.error} onRetry={() => saved.refetch()} />}
        {saved.data?.length === 0 && <EmptyState icon={<CalendarPlus className="size-5" />} title="No saved plans" description="Generate a plan and press Save plan." />}
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
          {saved.data?.map((p) => (
            <Card key={p.id} className={cn("gap-0 py-0", viewing === p.id && !plan && "ring-2 ring-primary/30")}>
              <CardContent className="flex items-center gap-3 p-4">
                <div className="flex size-10 items-center justify-center rounded-lg bg-secondary text-primary"><CalendarDays className="size-5" /></div>
                <div className="min-w-0 flex-1">
                  <p className="truncate font-medium">{p.name}</p>
                  <p className="text-xs text-muted-foreground">{p.days} day{p.days > 1 ? "s" : ""} from {shortDate(p.start_date)} · avg {fmt(p.summary?.avg_kcal)} kcal · saved {dateTime(p.created_at)}</p>
                </div>
                <Button size="icon-sm" variant="ghost" aria-label="View plan" onClick={() => { setPlan(null); setViewing(p.id) }}><Eye /></Button>
                <Button size="icon-sm" variant="ghost" aria-label="Delete plan" onClick={() => del.mutate(p.id)}><Trash2 /></Button>
              </CardContent>
            </Card>
          ))}
        </div>
      </div>

      <Dialog open={saveOpen} onOpenChange={setSaveOpen}>
        <DialogContent>
          <DialogHeader><DialogTitle>Save plan</DialogTitle><DialogDescription>The server recomputes every value from MySQL before saving.</DialogDescription></DialogHeader>
          <div className="space-y-1.5"><Label htmlFor="plan-name">Name</Label><Input id="plan-name" value={name} maxLength={120} onChange={(e) => setName(e.target.value)} /></div>
          <DialogFooter><Button variant="ghost" onClick={() => setSaveOpen(false)}>Cancel</Button><Button onClick={() => save.mutate()} disabled={save.isPending}>{save.isPending && <Loader2 className="animate-spin" />}Save</Button></DialogFooter>
        </DialogContent>
      </Dialog>
      <RecipeDialog id={open} onClose={() => setOpen(null)} />
    </>
  )
}
