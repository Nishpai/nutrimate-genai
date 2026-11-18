import { useState } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Filter, RefreshCw, ShieldCheck, SlidersHorizontal, Sparkles, X } from "lucide-react"
import { toast } from "sonner"
import { PageHeader } from "@/components/app/page-header"
import { RecipeDialog, RecipeTile } from "@/components/app/recipe"
import { EmptyState, ErrorState, LoadingGrid } from "@/components/app/states"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { useProfileOptions } from "@/components/app/profile-fields"
import { api } from "@/lib/api"
import { titleCase } from "@/lib/format"
import type { RecResponse } from "@/lib/types"

type Filters = { meal_type: string; cuisine: string; max_calories: string; min_protein_g: string; max_minutes: string; avoid: string }
const EMPTY: Filters = { meal_type: "any", cuisine: "any", max_calories: "", min_protein_g: "", max_minutes: "", avoid: "" }
const num = (s: string) => (s.trim() === "" ? null : Number(s))

export default function Recommendations() {
  const [draft, setDraft] = useState<Filters>(EMPTY)
  const [applied, setApplied] = useState<Filters>(EMPTY)
  const [open, setOpen] = useState<number | null>(null)
  const [nonce, setNonce] = useState(0)
  const opts = useProfileOptions().data
  const qc = useQueryClient()
  const key = ["recommendations", applied, nonce]
  const q = useQuery({
    queryKey: key,
    queryFn: () => api<RecResponse>("/api/recommendations", { body: {
      meal_type: applied.meal_type === "any" ? null : applied.meal_type,
      cuisine: applied.cuisine === "any" ? null : applied.cuisine,
      max_calories: num(applied.max_calories), min_protein_g: num(applied.min_protein_g), max_minutes: num(applied.max_minutes),
      extra_exclude: applied.avoid.split(",").map((s) => s.trim()).filter(Boolean), k: 18,
    } }),
  })
  const fb = useMutation({
    mutationFn: (v: { recipe_id: number; action: string }) => api("/api/feedback", { body: v }),
    onSuccess: (_d, v) => {
      if (v.action === "save" || v.action === "unsave") {
        qc.setQueryData<RecResponse>(key, (old) => old && { ...old, items: old.items.map((it) => it.recipe.recipe_id === v.recipe_id ? { ...it, saved: v.action === "save" } : it) })
        toast.success(v.action === "save" ? "Saved" : "Removed from saved")
      } else {
        qc.setQueryData<RecResponse>(key, (old) => old && { ...old, items: old.items.filter((it) => it.recipe.recipe_id !== v.recipe_id) })
        toast.success(v.action === "like" ? "Liked. Your next refresh will use it." : "Got it, we will show fewer like this.")
      }
      qc.invalidateQueries({ queryKey: ["dashboard"] })
    },
    onError: (e) => toast.error((e as Error).message),
  })
  const d = q.data
  const removed = d ? Object.entries(d.removed).filter(([, n]) => n > 0) : []
  const active = JSON.stringify(applied) !== JSON.stringify(EMPTY)
  return (
    <>
      <PageHeader eyebrow="Hybrid recommender" title="Recommended for you"
        description="Ranked by a blend of content similarity, LightFM collaborative filtering and popularity. Your diet and allergy rules remove recipes before any scoring."
        actions={<Button variant="outline" onClick={() => setNonce(nonce + 1)} disabled={q.isFetching}><RefreshCw className={q.isFetching ? "animate-spin" : ""} /> Refresh</Button>} />
      <Card className="mb-6 py-4">
        <CardContent className="px-4">
          <div className="mb-3 flex items-center gap-2 text-sm font-medium"><SlidersHorizontal className="size-4 text-primary" /> Filters for this search</div>
          <div className="grid gap-3 sm:grid-cols-3 lg:grid-cols-6">
            <div className="space-y-1"><Label className="text-xs">Meal</Label>
              <Select value={draft.meal_type} onValueChange={(v) => setDraft({ ...draft, meal_type: v })}>
                <SelectTrigger className="w-full"><SelectValue /></SelectTrigger>
                <SelectContent>{["any", "breakfast", "lunch", "dinner", "snack", "dessert", "drink"].map((m) => <SelectItem key={m} value={m}>{m === "any" ? "Any meal" : titleCase(m)}</SelectItem>)}</SelectContent>
              </Select></div>
            <div className="space-y-1"><Label className="text-xs">Cuisine</Label>
              <Select value={draft.cuisine} onValueChange={(v) => setDraft({ ...draft, cuisine: v })}>
                <SelectTrigger className="w-full"><SelectValue /></SelectTrigger>
                <SelectContent><SelectItem value="any">Any cuisine</SelectItem>{(opts?.cuisines ?? []).map((c) => <SelectItem key={c} value={c}>{c}</SelectItem>)}</SelectContent>
              </Select></div>
            <div className="space-y-1"><Label className="text-xs">Max kcal / serving</Label><Input type="number" value={draft.max_calories} onChange={(e) => setDraft({ ...draft, max_calories: e.target.value })} placeholder="Any" /></div>
            <div className="space-y-1"><Label className="text-xs">Min protein (g)</Label><Input type="number" value={draft.min_protein_g} onChange={(e) => setDraft({ ...draft, min_protein_g: e.target.value })} placeholder="Any" /></div>
            <div className="space-y-1"><Label className="text-xs">Max minutes</Label><Input type="number" value={draft.max_minutes} onChange={(e) => setDraft({ ...draft, max_minutes: e.target.value })} placeholder="Profile" /></div>
            <div className="space-y-1"><Label className="text-xs">Also avoid</Label><Input value={draft.avoid} onChange={(e) => setDraft({ ...draft, avoid: e.target.value })} placeholder="e.g. garlic, onion" /></div>
          </div>
          <div className="mt-3 flex flex-wrap items-center justify-end gap-2">
            {active && <Button variant="ghost" size="sm" onClick={() => { setDraft(EMPTY); setApplied(EMPTY) }}><X /> Clear</Button>}
            <Button size="sm" onClick={() => setApplied(draft)}><Filter /> Apply filters</Button>
          </div>
        </CardContent>
      </Card>
      {d && (
        <div className="mb-5 flex flex-col gap-3 rounded-xl border border-emerald-200 bg-emerald-50/60 p-4 text-sm sm:flex-row sm:items-start">
          <ShieldCheck className="size-5 shrink-0 text-emerald-700" />
          <div className="space-y-2">
            <p className="text-emerald-900">
              <b>{d.passed.toLocaleString()}</b> recipes passed your rules.{" "}
              {d.personalised ? `Personalised from ${d.liked_count} liked recipes and your profile.` : "Like a few recipes to personalise this further."}
              <span className="text-emerald-800/80"> Mode: {d.mode}.</span>
            </p>
            <div className="flex flex-wrap gap-1.5">
              {d.applied_rules.map((r) => <Badge key={r} variant="outline" className="border-emerald-300 bg-white text-emerald-800">{r}</Badge>)}
              {removed.map(([k, n]) => <Badge key={k} variant="secondary" className="bg-white text-muted-foreground">{n.toLocaleString()} removed: {k}</Badge>)}
            </div>
            {d.breakfast_note && <p className="text-amber-800">{d.breakfast_note}</p>}
          </div>
        </div>
      )}
      {q.isLoading && <LoadingGrid count={9} className="sm:grid-cols-2 xl:grid-cols-3" itemClass="h-80" />}
      {q.isError && <ErrorState error={q.error} onRetry={() => q.refetch()} />}
      {d && d.items.length === 0 && <EmptyState icon={<Sparkles className="size-5" />} title="No recipe passed every rule" description="Try removing a filter or relaxing a limit." />}
      {d && d.items.length > 0 && (
        <div className="grid gap-5 sm:grid-cols-2 xl:grid-cols-3">
          {d.items.map((it) => (
            <RecipeTile key={it.recipe.recipe_id} item={it} onOpen={() => setOpen(it.recipe.recipe_id)} busy={fb.isPending}
              onFeedback={(action) => fb.mutate({ recipe_id: it.recipe.recipe_id, action })} />
          ))}
        </div>
      )}
      <RecipeDialog id={open} onClose={() => setOpen(null)} />
    </>
  )
}
