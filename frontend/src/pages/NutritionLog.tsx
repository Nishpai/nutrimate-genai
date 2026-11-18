import { useEffect, useState } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Apple, ChefHat, ChevronLeft, ChevronRight, ClipboardList, Loader2, Plus, Search, Trash2, TriangleAlert } from "lucide-react"
import { toast } from "sonner"
import { PageHeader } from "@/components/app/page-header"
import { MacroBar } from "@/components/app/stat"
import { EmptyState, ErrorState, LoadingBlock } from "@/components/app/states"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { api } from "@/lib/api"
import { dayName, fmt, MACRO_COLORS, titleCase, todayIso } from "@/lib/format"
import type { Nutrients } from "@/lib/types"
import { cn } from "@/lib/utils"
import type { DashboardData } from "./Dashboard"

type LogRow = Nutrients & { id: number; slot: string; item_type: string; item_id: string; item_name: string; quantity: number; unit: string }
type DayLog = { date: string; items: LogRow[]; totals: Nutrients; items_with_unknown_values: string[] }
type Pickable = { type: "recipe" | "food"; id: string; name: string; sub: string; hasServing: boolean }
const SLOTS = ["breakfast", "lunch", "snack", "dinner"]

function shift(iso: string, n: number) {
  const d = new Date(iso + "T00:00:00")
  d.setDate(d.getDate() + n)
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`
}

function AddDialog({ open, onClose, date }: { open: boolean; onClose: () => void; date: string }) {
  const qc = useQueryClient()
  const [q, setQ] = useState("")
  const [dq, setDq] = useState("")
  const [pick, setPick] = useState<Pickable | null>(null)
  const [slot, setSlot] = useState("lunch")
  const [qty, setQty] = useState("1")
  const [unit, setUnit] = useState("serving")
  useEffect(() => { const t = setTimeout(() => setDq(q.trim()), 300); return () => clearTimeout(t) }, [q])
  useEffect(() => { if (!open) { setQ(""); setPick(null); setQty("1"); setUnit("serving") } }, [open])
  const results = useQuery({
    queryKey: ["log-search", dq], enabled: dq.length >= 2,
    queryFn: async () => {
      const [f, r] = await Promise.all([
        api<{ items: { food_id: string; name: string; kcal_100g: number | null; kcal_serving: number | null; serving_unit: string | null }[] }>(`/api/foods?q=${encodeURIComponent(dq)}&page_size=6`),
        api<{ items: { recipe_id: number; name: string; calories_kcal: number | null }[] }>(`/api/recipes?q=${encodeURIComponent(dq)}&page_size=6`),
      ])
      return [
        ...f.items.map((x): Pickable => ({ type: "food", id: x.food_id, name: x.name, sub: `${fmt(x.kcal_100g)} kcal / 100 g${x.kcal_serving !== null ? ` · ${fmt(x.kcal_serving)} kcal per ${x.serving_unit ?? "serving"}` : ""}`, hasServing: x.kcal_serving !== null })),
        ...r.items.map((x): Pickable => ({ type: "recipe", id: String(x.recipe_id), name: x.name, sub: `${fmt(x.calories_kcal)} kcal per serving`, hasServing: true })),
      ]
    },
  })
  const choose = (p: Pickable) => {
    setPick(p)
    if (p.type === "food" && !p.hasServing) { setUnit("g"); setQty("100") } else { setUnit("serving"); setQty("1") }
  }
  const add = useMutation({
    mutationFn: () => api("/api/logs", { body: { log_date: date, slot, item_type: pick!.type, item_id: pick!.id, quantity: Number(qty), unit } }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["logs"] }); qc.invalidateQueries({ queryKey: ["dashboard"] }); toast.success("Added to your log"); onClose() },
    onError: (e) => toast.error((e as Error).message),
  })
  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader><DialogTitle>Add to log</DialogTitle><DialogDescription>Nutrition is calculated on the server from the database for the amount you enter.</DialogDescription></DialogHeader>
        {!pick ? (
          <div className="space-y-3">
            <div className="relative"><Search className="absolute top-1/2 left-3 size-4 -translate-y-1/2 text-muted-foreground" /><Input autoFocus className="h-10 pl-9" placeholder="Search a food or recipe" value={q} onChange={(e) => setQ(e.target.value)} /></div>
            <div className="max-h-80 space-y-1 overflow-y-auto">
              {dq.length < 2 && <p className="py-6 text-center text-sm text-muted-foreground">Type at least two letters.</p>}
              {results.isLoading && <LoadingBlock className="h-40" />}
              {results.data?.length === 0 && <p className="py-6 text-center text-sm text-muted-foreground">Nothing found.</p>}
              {results.data?.map((p) => (
                <button key={p.type + p.id} onClick={() => choose(p)} className="flex w-full items-center gap-3 rounded-lg p-2 text-left hover:bg-secondary">
                  <div className="flex size-8 shrink-0 items-center justify-center rounded-md bg-muted text-primary">{p.type === "food" ? <Apple className="size-4" /> : <ChefHat className="size-4" />}</div>
                  <div className="min-w-0"><p className="truncate text-sm font-medium">{p.name}</p><p className="text-xs text-muted-foreground">{p.sub}</p></div>
                </button>
              ))}
            </div>
          </div>
        ) : (
          <div className="space-y-4">
            <div className="flex items-center justify-between rounded-lg border bg-muted/30 p-3"><div className="min-w-0"><p className="truncate text-sm font-medium">{pick.name}</p><p className="text-xs text-muted-foreground">{pick.sub}</p></div><Button size="sm" variant="ghost" onClick={() => setPick(null)}>Change</Button></div>
            <div className="grid grid-cols-3 gap-3">
              <div className="space-y-1.5"><Label>Meal</Label><Select value={slot} onValueChange={setSlot}><SelectTrigger className="w-full"><SelectValue /></SelectTrigger><SelectContent>{SLOTS.map((s) => <SelectItem key={s} value={s}>{titleCase(s)}</SelectItem>)}</SelectContent></Select></div>
              <div className="space-y-1.5"><Label>Amount</Label><Input type="number" step="0.25" min="0" value={qty} onChange={(e) => setQty(e.target.value)} /></div>
              <div className="space-y-1.5"><Label>Unit</Label>
                <Select value={unit} onValueChange={setUnit} disabled={pick.type === "recipe"}><SelectTrigger className="w-full"><SelectValue /></SelectTrigger>
                  <SelectContent>{(pick.type === "recipe" || pick.hasServing) && <SelectItem value="serving">Servings</SelectItem>}{pick.type === "food" && <SelectItem value="g">Grams</SelectItem>}</SelectContent></Select></div>
            </div>
          </div>
        )}
        <DialogFooter><Button variant="ghost" onClick={onClose}>Cancel</Button><Button disabled={!pick || !(Number(qty) > 0) || add.isPending} onClick={() => add.mutate()}>{add.isPending && <Loader2 className="animate-spin" />}Add entry</Button></DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

export default function NutritionLog() {
  const [date, setDate] = useState(todayIso())
  const [adding, setAdding] = useState(false)
  const qc = useQueryClient()
  const q = useQuery({ queryKey: ["logs", date], queryFn: () => api<DayLog>(`/api/logs?day=${date}`) })
  const dash = useQuery({ queryKey: ["dashboard", "7"], queryFn: () => api<DashboardData>("/api/dashboard?days=7") })
  const del = useMutation({
    mutationFn: (id: number) => api(`/api/logs/${id}`, { method: "DELETE" }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["logs"] }); qc.invalidateQueries({ queryKey: ["dashboard"] }); toast.success("Entry removed") },
  })
  const t = dash.data?.targets
  const d = q.data
  const isToday = date === todayIso()
  return (
    <>
      <PageHeader eyebrow="Nutrition log" title="What you ate" description="Each entry stores the nutrition computed from MySQL when it was logged. Unknown values are kept as unknown, never as zero."
        actions={<Button onClick={() => setAdding(true)}><Plus /> Add entry</Button>} />
      <div className="mb-6 flex flex-wrap items-center gap-2">
        <Button size="icon" variant="outline" onClick={() => setDate(shift(date, -1))} aria-label="Previous day"><ChevronLeft /></Button>
        <Input type="date" value={date} max={todayIso()} onChange={(e) => e.target.value && setDate(e.target.value)} className="w-44" />
        <Button size="icon" variant="outline" disabled={isToday} onClick={() => setDate(shift(date, 1))} aria-label="Next day"><ChevronRight /></Button>
        <span className="ml-2 text-sm text-muted-foreground">{isToday ? "Today" : dayName(date)}</span>
        {!isToday && <Button size="sm" variant="ghost" onClick={() => setDate(todayIso())}>Back to today</Button>}
      </div>
      {q.isError && <ErrorState error={q.error} onRetry={() => q.refetch()} />}
      <div className="grid gap-6 lg:grid-cols-3">
        <div className="space-y-4 lg:col-span-2">
          {q.isLoading && <LoadingBlock className="h-80" />}
          {d && d.items.length === 0 && <EmptyState icon={<ClipboardList className="size-5" />} title="Nothing logged for this day" description="Add a food or recipe, or log a day from a saved meal plan." action={<Button onClick={() => setAdding(true)}><Plus /> Add entry</Button>} />}
          {d && d.items.length > 0 && SLOTS.map((s) => {
            const rows = d.items.filter((r) => r.slot === s)
            if (!rows.length) return null
            const kcal = rows.reduce((a, r) => a + (r.calories_kcal ?? 0), 0)
            return (
              <Card key={s} className="gap-0 py-0">
                <div className="flex items-center justify-between border-b px-4 py-2.5"><p className="text-sm font-semibold">{titleCase(s)}</p><span className="text-xs text-muted-foreground">{fmt(kcal)} kcal</span></div>
                <div className="divide-y">
                  {rows.map((r) => (
                    <div key={r.id} className="flex items-center gap-3 px-4 py-3">
                      <div className="flex size-8 shrink-0 items-center justify-center rounded-md bg-muted text-primary">{r.item_type === "food" ? <Apple className="size-4" /> : <ChefHat className="size-4" />}</div>
                      <div className="min-w-0 flex-1">
                        <p className="truncate text-sm font-medium">{r.item_name}</p>
                        <p className="text-xs text-muted-foreground">{fmt(r.quantity, 2)} {r.unit === "g" ? "g" : `serving${r.quantity === 1 ? "" : "s"}`} · {fmt(r.protein_g, 1)} g protein · {fmt(r.carbs_g, 1)} g carbs · {fmt(r.fat_g, 1)} g fat</p>
                      </div>
                      <span className={cn("text-sm font-semibold tabular-nums", r.calories_kcal === null && "text-amber-600")}>{fmt(r.calories_kcal)} kcal</span>
                      <Button size="icon-sm" variant="ghost" aria-label="Delete entry" onClick={() => del.mutate(r.id)}><Trash2 /></Button>
                    </div>
                  ))}
                </div>
              </Card>
            )
          })}
        </div>
        <Card className="h-fit">
          <CardHeader><CardTitle>Day totals</CardTitle><CardDescription>Against your daily targets.</CardDescription></CardHeader>
          <CardContent className="space-y-4">
            {d && t ? (
              <>
                <MacroBar label="Calories" value={d.totals.calories_kcal} target={t.calories_kcal} unit="kcal" color={MACRO_COLORS.calories_kcal} />
                <MacroBar label="Protein" value={d.totals.protein_g} target={t.protein_g} unit="g" color={MACRO_COLORS.protein_g} />
                <MacroBar label="Carbs" value={d.totals.carbs_g} target={t.carbs_g} unit="g" color={MACRO_COLORS.carbs_g} />
                <MacroBar label="Fat" value={d.totals.fat_g} target={t.fat_g} unit="g" color={MACRO_COLORS.fat_g} />
                <MacroBar label="Fibre" value={d.totals.fiber_g} target={t.fiber_g} unit="g" color={MACRO_COLORS.fiber_g} />
                {d.items_with_unknown_values.length > 0 && (
                  <div className="flex gap-2 rounded-lg border border-amber-200 bg-amber-50 p-3 text-xs text-amber-800"><TriangleAlert className="size-4 shrink-0" />
                    <span>Totals are a lower bound. Some values are unknown for: {d.items_with_unknown_values.join(", ")}</span></div>
                )}
                <Badge variant="secondary">{d.items.length} entries</Badge>
              </>
            ) : <LoadingBlock className="h-48" />}
          </CardContent>
        </Card>
      </div>
      <AddDialog open={adding} onClose={() => setAdding(false)} date={date} />
    </>
  )
}
