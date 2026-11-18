import { useState } from "react"
import { useQuery } from "@tanstack/react-query"
import { Bookmark, Clock, Flame, Leaf, Loader2, Star, ThumbsDown, ThumbsUp, TriangleAlert, Dumbbell, Sparkles } from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { ScrollArea } from "@/components/ui/scroll-area"
import { api } from "@/lib/api"
import { fmt, titleCase } from "@/lib/format"
import type { RecItem, RecipeCard } from "@/lib/types"
import { cn } from "@/lib/utils"
import { ErrorState, LoadingBlock } from "./states"

const GRADIENTS = [
  "from-emerald-500/90 to-teal-500/80", "from-lime-500/80 to-emerald-600/80", "from-teal-500/85 to-cyan-600/75",
  "from-emerald-600/90 to-green-500/75", "from-green-500/80 to-teal-600/80",
]

export function DietBadge({ r }: { r: Pick<RecipeCard, "is_vegan" | "is_vegetarian" | "is_eggetarian"> }) {
  const label = r.is_vegan ? "Vegan" : r.is_vegetarian ? "Vegetarian" : r.is_eggetarian ? "Eggetarian" : null
  if (!label) return null
  return <Badge variant="secondary" className="gap-1 bg-emerald-50 text-emerald-700"><Leaf className="size-3" />{label}</Badge>
}

export function NutrientStrip({ r, compact }: { r: Partial<RecipeCard>; compact?: boolean }) {
  const items = [
    { label: "kcal", v: r.calories_kcal, d: 0 },
    { label: "protein", v: r.protein_g, d: 0, u: "g" },
    { label: "carbs", v: r.carbs_g, d: 0, u: "g" },
    { label: "fat", v: r.fat_g, d: 0, u: "g" },
  ]
  return (
    <div className={cn("grid grid-cols-4 divide-x rounded-lg border bg-muted/30 text-center", compact && "text-xs")}>
      {items.map((i) => (
        <div key={i.label} className="px-1 py-1.5">
          <p className="font-semibold tabular-nums">{fmt(i.v ?? null, i.d)}{i.u && i.v !== null && i.v !== undefined ? i.u : ""}</p>
          <p className="text-[10px] text-muted-foreground uppercase">{i.label}</p>
        </div>
      ))}
    </div>
  )
}

export function RecipeTile({ item, onFeedback, onOpen, busy }: {
  item: RecItem; onFeedback?: (action: string) => void; onOpen: () => void; busy?: boolean
}) {
  const r = item.recipe
  const g = GRADIENTS[r.recipe_id % GRADIENTS.length]
  return (
    <Card className="group gap-0 overflow-hidden py-0 transition hover:-translate-y-0.5 hover:shadow-lg hover:shadow-emerald-900/5">
      <button onClick={onOpen} className="text-left">
        <div className={cn("relative h-24 bg-gradient-to-br p-4 text-white", g)}>
          <div className="bg-grid absolute inset-0 opacity-40" />
          <div className="relative flex items-start justify-between gap-2">
            <Badge className="border-white/30 bg-white/20 text-white backdrop-blur">{titleCase(r.meal_type)}</Badge>
            {r.cuisine !== "Unspecified" && <span className="text-xs font-medium text-white/90">{r.cuisine}</span>}
          </div>
          <div className="relative mt-3 flex items-center gap-3 text-xs text-white/90">
            {r.total_minutes !== null && <span className="flex items-center gap-1"><Clock className="size-3.5" />{fmt(r.total_minutes)} min</span>}
            {r.mean_rating !== null && r.n_ratings > 0 && <span className="flex items-center gap-1"><Star className="size-3.5" />{r.mean_rating.toFixed(1)} ({r.n_ratings})</span>}
          </div>
        </div>
        <div className="space-y-3 p-4">
          <div className="flex items-start justify-between gap-2">
            <h3 className="line-clamp-2 leading-snug font-semibold">{r.name}</h3>
          </div>
          <div className="flex flex-wrap gap-1.5">
            <DietBadge r={r} />
            {r.protein_g !== null && r.protein_g >= 20 && <Badge variant="secondary" className="gap-1"><Dumbbell className="size-3" />High protein</Badge>}
            {r.nutrition_status !== "listed" && <Badge variant="outline" className="gap-1 text-amber-700"><TriangleAlert className="size-3" />Nutrition unknown</Badge>}
            {item.breakfast_fallback && <Badge variant="outline" className="gap-1 border-amber-300 text-amber-700" title="Few breakfast recipes pass your rules, so this light dish is not tagged as breakfast">Fallback breakfast</Badge>}
          </div>
          <NutrientStrip r={r} compact />
          {item.reasons.length > 0 && (
            <ul className="space-y-1 text-xs text-muted-foreground">
              {item.reasons.slice(0, 2).map((x) => (
                <li key={x} className="flex gap-1.5"><Sparkles className="mt-0.5 size-3 shrink-0 text-primary" /><span className="line-clamp-2">{x}</span></li>
              ))}
            </ul>
          )}
        </div>
      </button>
      {onFeedback && (
        <div className="mt-auto flex items-center justify-between border-t px-3 py-2">
          <span className="text-[11px] text-muted-foreground tabular-nums">score {item.score.toFixed(2)}</span>
          <div className="flex gap-1">
            <Button size="icon-sm" variant="ghost" aria-label="Like" disabled={busy} onClick={() => onFeedback("like")}><ThumbsUp /></Button>
            <Button size="icon-sm" variant="ghost" aria-label="Not for me" disabled={busy} onClick={() => onFeedback("dislike")}><ThumbsDown /></Button>
            <Button size="icon-sm" variant={item.saved ? "secondary" : "ghost"} aria-label="Save" disabled={busy}
              onClick={() => onFeedback(item.saved ? "unsave" : "save")}><Bookmark className={cn(item.saved && "fill-current text-primary")} /></Button>
          </div>
        </div>
      )}
    </Card>
  )
}

type Detail = RecipeCard & {
  ingredients: string[]; instructions: string[]; keywords: string[]; description: string; sugar_g: number | null;
  sodium_mg: number | null; source: string; energy_split: { protein: number; carbs: number; fat: number } | null;
  profile_check: string[]
}

export function RecipeDialog({ id, onClose }: { id: number | null; onClose: () => void }) {
  const q = useQuery({ queryKey: ["recipe", id], queryFn: () => api<Detail>(`/api/recipes/${id}`), enabled: id !== null })
  const [tab, setTab] = useState<"ingredients" | "steps">("ingredients")
  const r = q.data
  return (
    <Dialog open={id !== null} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-2xl gap-0 p-0 sm:max-w-2xl">
        {q.isLoading && <div className="p-6"><LoadingBlock className="h-80" /></div>}
        {q.isError && <div className="p-6"><ErrorState error={q.error} onRetry={() => q.refetch()} /></div>}
        {r && (
          <>
            <DialogHeader className="border-b p-6 pb-4">
              <div className="mb-1 flex flex-wrap gap-1.5">
                <Badge variant="secondary">{titleCase(r.meal_type)}</Badge>
                {r.cuisine !== "Unspecified" && <Badge variant="outline">{r.cuisine}</Badge>}
                <DietBadge r={r} />
              </div>
              <DialogTitle className="text-xl">{r.name}</DialogTitle>
              <DialogDescription className="line-clamp-2">{r.description || r.category}</DialogDescription>
            </DialogHeader>
            <ScrollArea className="max-h-[65vh]">
              <div className="space-y-5 p-6">
                {r.profile_check.length > 0 ? (
                  <div className="flex gap-2 rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800">
                    <TriangleAlert className="mt-0.5 size-4 shrink-0" />
                    <span>Does not fit your profile: {r.profile_check.join(", ")}</span>
                  </div>
                ) : (
                  <div className="flex gap-2 rounded-lg border border-emerald-200 bg-emerald-50 p-3 text-sm text-emerald-800">
                    <Leaf className="mt-0.5 size-4 shrink-0" /> Fits your diet. Your allergens and restrictions were not found in the listed ingredients or steps. This is a text check, so read the label of anything you buy.
                  </div>
                )}
                <p className="text-xs text-muted-foreground">
                  {r.allergens.length > 0
                    ? <>Allergen groups mentioned in the recipe text: {r.allergens.map((a) => a.replace("_", " ")).join(", ")}.</>
                    : <>No tracked allergen group was found in the listed ingredients.</>}
                </p>
                <div>
                  <p className="mb-2 text-sm font-medium">Nutrition per serving <span className="font-normal text-muted-foreground">({r.source})</span></p>
                  <NutrientStrip r={r} />
                  <div className="mt-2 grid grid-cols-3 gap-2 text-center text-xs text-muted-foreground">
                    <span>Fibre <b className="text-foreground">{fmt(r.fiber_g, 1, " g")}</b></span>
                    <span>Sugar <b className="text-foreground">{fmt(r.sugar_g, 1, " g")}</b></span>
                    <span>Sodium <b className="text-foreground">{fmt(r.sodium_mg, 0, " mg")}</b></span>
                  </div>
                  {r.energy_split && (
                    <div className="mt-3">
                      <div className="flex h-2.5 overflow-hidden rounded-full">
                        <div style={{ width: `${r.energy_split.protein}%`, background: "var(--chart-3)" }} />
                        <div style={{ width: `${r.energy_split.carbs}%`, background: "var(--chart-2)" }} />
                        <div style={{ width: `${r.energy_split.fat}%`, background: "var(--chart-4)" }} />
                      </div>
                      <p className="mt-1 text-xs text-muted-foreground">Energy from protein {r.energy_split.protein}%, carbs {r.energy_split.carbs}%, fat {r.energy_split.fat}%</p>
                    </div>
                  )}
                </div>
                <div className="flex gap-2 text-sm">
                  <Button size="sm" variant={tab === "ingredients" ? "secondary" : "ghost"} onClick={() => setTab("ingredients")}>Ingredients ({r.ingredients.length})</Button>
                  <Button size="sm" variant={tab === "steps" ? "secondary" : "ghost"} onClick={() => setTab("steps")}>Steps ({r.instructions.length})</Button>
                  <span className="ml-auto flex items-center gap-3 text-xs text-muted-foreground">
                    {r.total_minutes !== null && <span className="flex items-center gap-1"><Clock className="size-3.5" />{fmt(r.total_minutes)} min</span>}
                    {r.servings && <span className="flex items-center gap-1"><Flame className="size-3.5" />{r.servings} servings</span>}
                  </span>
                </div>
                {tab === "ingredients" ? (
                  <ul className="grid gap-1.5 text-sm sm:grid-cols-2">
                    {r.ingredients.map((i) => <li key={i} className="flex gap-2"><span className="mt-2 size-1.5 shrink-0 rounded-full bg-primary" />{i}</li>)}
                  </ul>
                ) : (
                  <ol className="space-y-2 text-sm">
                    {r.instructions.map((s, n) => (
                      <li key={n} className="flex gap-3"><span className="flex size-6 shrink-0 items-center justify-center rounded-full bg-secondary text-xs font-semibold text-primary">{n + 1}</span><span>{s}</span></li>
                    ))}
                  </ol>
                )}
              </div>
            </ScrollArea>
          </>
        )}
        {q.isFetching && !r && <Loader2 className="m-6 animate-spin" />}
      </DialogContent>
    </Dialog>
  )
}
