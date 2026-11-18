import { useEffect, useState } from "react"
import { useQuery } from "@tanstack/react-query"
import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts"
import { Apple, ChefHat, ChevronLeft, ChevronRight, GitCompare, Plus, Search, Sparkles, X } from "lucide-react"
import { toast } from "sonner"
import { PageHeader } from "@/components/app/page-header"
import { useProfileOptions } from "@/components/app/profile-fields"
import { DietBadge, NutrientStrip, RecipeDialog } from "@/components/app/recipe"
import { EmptyState, ErrorState, LoadingBlock, LoadingGrid } from "@/components/app/states"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Switch } from "@/components/ui/switch"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { api } from "@/lib/api"
import { fmt, titleCase } from "@/lib/format"
import type { RecipeCard } from "@/lib/types"

type Food = { food_id: string; name: string; source: string; food_group: string | null; kcal_100g: number | null; protein_100g: number | null; carbs_100g: number | null; fat_100g: number | null; fiber_100g: number | null; sugar_100g: number | null; sodium_100g: number | null; serving_unit: string | null; kcal_serving: number | null; protein_serving: number | null; energy_split?: { protein: number; carbs: number; fat: number } | null }
type Page<T> = { items: T[]; total: number; page: number; page_size: number }
type CompareItem = { type: string; id: string; name: string; basis: string; calories_kcal: number | null; protein_g: number | null; carbs_g: number | null; fat_g: number | null; fiber_g: number | null; sugar_g: number | null; sodium_mg: number | null; source: string }
type Pick = { key: string; name: string }

function useDebounced<T>(v: T, ms = 300) {
  const [d, setD] = useState(v)
  useEffect(() => { const t = setTimeout(() => setD(v), ms); return () => clearTimeout(t) }, [v, ms])
  return d
}

function Pager({ page, total, size, onPage }: { page: number; total: number; size: number; onPage: (p: number) => void }) {
  const pages = Math.max(1, Math.ceil(total / size))
  return (
    <div className="mt-4 flex items-center justify-between text-sm text-muted-foreground">
      <span>{total.toLocaleString()} results</span>
      <div className="flex items-center gap-2">
        <Button size="icon-sm" variant="outline" disabled={page <= 1} onClick={() => onPage(page - 1)} aria-label="Previous page"><ChevronLeft /></Button>
        <span>Page {page} of {pages}</span>
        <Button size="icon-sm" variant="outline" disabled={page >= pages} onClick={() => onPage(page + 1)} aria-label="Next page"><ChevronRight /></Button>
      </div>
    </div>
  )
}

function FoodsTab({ onCompare, onOpen }: { onCompare: (p: Pick) => void; onOpen: (id: string) => void }) {
  const [q, setQ] = useState("")
  const [source, setSource] = useState("all")
  const [group, setGroup] = useState("all")
  const [sort, setSort] = useState("relevance")
  const [page, setPage] = useState(1)
  const dq = useDebounced(q)
  useEffect(() => setPage(1), [dq, source, group, sort])
  const groups = useQuery({ queryKey: ["food-groups"], queryFn: () => api<string[]>("/api/foods/groups"), staleTime: Infinity })
  const params = new URLSearchParams({ q: dq, source, sort, page: String(page), page_size: "20" })
  if (group !== "all") params.set("group", group)
  const res = useQuery({ queryKey: ["foods", params.toString()], queryFn: () => api<Page<Food>>(`/api/foods?${params}`), placeholderData: (p) => p })
  return (
    <>
      <div className="mb-4 grid gap-3 md:grid-cols-[1fr_auto_auto_auto]">
        <div className="relative"><Search className="absolute top-1/2 left-3 size-4 -translate-y-1/2 text-muted-foreground" /><Input className="h-10 pl-9" placeholder="Search foods, e.g. chickpeas, ragi, paneer" value={q} onChange={(e) => setQ(e.target.value)} /></div>
        <Select value={source} onValueChange={setSource}><SelectTrigger className="h-10 w-full md:w-40"><SelectValue /></SelectTrigger>
          <SelectContent><SelectItem value="all">All sources</SelectItem><SelectItem value="indb">Indian (INDB)</SelectItem><SelectItem value="usda">USDA SR Legacy</SelectItem><SelectItem value="imported">Imported by admin</SelectItem></SelectContent></Select>
        <Select value={group} onValueChange={setGroup}><SelectTrigger className="h-10 w-full md:w-48"><SelectValue /></SelectTrigger>
          <SelectContent><SelectItem value="all">All groups</SelectItem>{groups.data?.map((g) => <SelectItem key={g} value={g}>{g}</SelectItem>)}</SelectContent></Select>
        <Select value={sort} onValueChange={setSort}><SelectTrigger className="h-10 w-full md:w-40"><SelectValue /></SelectTrigger>
          <SelectContent><SelectItem value="relevance">Best match</SelectItem><SelectItem value="protein">Most protein</SelectItem><SelectItem value="calories">Fewest calories</SelectItem><SelectItem value="fiber">Most fibre</SelectItem></SelectContent></Select>
      </div>
      {res.isLoading && <LoadingBlock className="h-96" />}
      {res.isError && <ErrorState error={res.error} onRetry={() => res.refetch()} />}
      {res.data && res.data.items.length === 0 && <EmptyState icon={<Apple className="size-5" />} title="No foods match" description="Try a shorter search or another source." />}
      {res.data && res.data.items.length > 0 && (
        <Card className="py-0">
          <Table>
            <TableHeader><TableRow><TableHead className="pl-4">Food</TableHead><TableHead className="hidden md:table-cell">Group</TableHead><TableHead className="text-right">kcal</TableHead><TableHead className="text-right">Protein</TableHead><TableHead className="hidden text-right sm:table-cell">Carbs</TableHead><TableHead className="hidden text-right sm:table-cell">Fat</TableHead><TableHead className="hidden text-right lg:table-cell">Fibre</TableHead><TableHead className="w-12" /></TableRow></TableHeader>
            <TableBody>
              {res.data.items.map((f) => (
                <TableRow key={f.food_id} className="cursor-pointer" onClick={() => onOpen(f.food_id)}>
                  <TableCell className="max-w-72 pl-4"><p className="truncate font-medium">{f.name}</p><p className="text-xs text-muted-foreground">{f.food_id.startsWith("INDB") ? "INDB" : f.food_id.startsWith("USDA") ? "USDA" : f.source} · per 100 g</p></TableCell>
                  <TableCell className="hidden max-w-40 truncate text-muted-foreground md:table-cell">{f.food_group ?? "n/a"}</TableCell>
                  <TableCell className="text-right tabular-nums">{fmt(f.kcal_100g)}</TableCell>
                  <TableCell className="text-right tabular-nums">{fmt(f.protein_100g, 1, " g")}</TableCell>
                  <TableCell className="hidden text-right tabular-nums sm:table-cell">{fmt(f.carbs_100g, 1, " g")}</TableCell>
                  <TableCell className="hidden text-right tabular-nums sm:table-cell">{fmt(f.fat_100g, 1, " g")}</TableCell>
                  <TableCell className="hidden text-right tabular-nums lg:table-cell">{fmt(f.fiber_100g, 1, " g")}</TableCell>
                  <TableCell><Button size="icon-sm" variant="ghost" aria-label="Add to compare" onClick={(e) => { e.stopPropagation(); onCompare({ key: `food:${f.food_id}`, name: f.name }) }}><Plus /></Button></TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </Card>
      )}
      {res.data && <Pager page={page} total={res.data.total} size={20} onPage={setPage} />}
    </>
  )
}

function RecipesTab({ onCompare, onOpen }: { onCompare: (p: Pick) => void; onOpen: (id: number) => void }) {
  const opts = useProfileOptions().data
  const [q, setQ] = useState("")
  const [diet, setDiet] = useState("any")
  const [cuisine, setCuisine] = useState("all")
  const [meal, setMeal] = useState("all")
  const [sort, setSort] = useState("relevance")
  const [safe, setSafe] = useState(true)
  const [page, setPage] = useState(1)
  const dq = useDebounced(q)
  useEffect(() => setPage(1), [dq, diet, cuisine, meal, sort, safe])
  const params = new URLSearchParams({ q: dq, diet, sort, page: String(page), page_size: "18", apply_profile: String(safe) })
  if (cuisine !== "all") params.set("cuisine", cuisine)
  if (meal !== "all") params.set("meal_type", meal)
  const res = useQuery({ queryKey: ["recipes", params.toString()], queryFn: () => api<Page<RecipeCard>>(`/api/recipes?${params}`), placeholderData: (p) => p })
  return (
    <>
      <div className="mb-4 grid gap-3 md:grid-cols-2 xl:grid-cols-[1fr_auto_auto_auto_auto_auto]">
        <div className="relative md:col-span-2 xl:col-span-1"><Search className="absolute top-1/2 left-3 size-4 -translate-y-1/2 text-muted-foreground" /><Input className="h-10 pl-9" placeholder="Search recipes or ingredients" value={q} onChange={(e) => setQ(e.target.value)} /></div>
        <Select value={diet} onValueChange={setDiet}><SelectTrigger className="h-10 w-full xl:w-36"><SelectValue /></SelectTrigger><SelectContent>{["any", "eggetarian", "vegetarian", "vegan"].map((d) => <SelectItem key={d} value={d}>{d === "any" ? "Any diet" : titleCase(d)}</SelectItem>)}</SelectContent></Select>
        <Select value={cuisine} onValueChange={setCuisine}><SelectTrigger className="h-10 w-full xl:w-36"><SelectValue /></SelectTrigger><SelectContent><SelectItem value="all">All cuisines</SelectItem>{opts?.cuisines.map((c) => <SelectItem key={c} value={c}>{c}</SelectItem>)}</SelectContent></Select>
        <Select value={meal} onValueChange={setMeal}><SelectTrigger className="h-10 w-full xl:w-32"><SelectValue /></SelectTrigger><SelectContent><SelectItem value="all">All meals</SelectItem>{["breakfast", "lunch", "dinner", "snack", "dessert", "drink"].map((m) => <SelectItem key={m} value={m}>{titleCase(m)}</SelectItem>)}</SelectContent></Select>
        <Select value={sort} onValueChange={setSort}><SelectTrigger className="h-10 w-full xl:w-40"><SelectValue /></SelectTrigger><SelectContent><SelectItem value="relevance">Most rated</SelectItem><SelectItem value="rating">Best rated</SelectItem><SelectItem value="protein">Most protein</SelectItem><SelectItem value="calories">Fewest calories</SelectItem><SelectItem value="time">Quickest</SelectItem><SelectItem value="fiber">Most fibre</SelectItem></SelectContent></Select>
        <label className="flex h-10 items-center gap-2 rounded-md border px-3 text-sm"><Switch checked={safe} onCheckedChange={setSafe} /> My rules</label>
      </div>
      {res.isLoading && <LoadingGrid count={6} className="sm:grid-cols-2 xl:grid-cols-3" itemClass="h-44" />}
      {res.isError && <ErrorState error={res.error} onRetry={() => res.refetch()} />}
      {res.data && res.data.items.length === 0 && <EmptyState icon={<ChefHat className="size-5" />} title="No recipes match" description={safe ? "Your allergy and restriction rules are on. Try another search." : "Try another search."} />}
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
        {res.data?.items.map((r) => (
          <Card key={r.recipe_id} className="gap-0 py-0 transition hover:shadow-md">
            <button className="space-y-3 p-4 text-left" onClick={() => onOpen(r.recipe_id)}>
              <div className="flex flex-wrap gap-1.5"><Badge variant="secondary">{titleCase(r.meal_type)}</Badge>{r.cuisine !== "Unspecified" && <Badge variant="outline">{r.cuisine}</Badge>}<DietBadge r={r} /></div>
              <p className="line-clamp-2 font-semibold leading-snug">{r.name}</p>
              <NutrientStrip r={r} compact />
            </button>
            <div className="mt-auto flex items-center justify-between border-t px-4 py-2 text-xs text-muted-foreground">
              <span>{r.total_minutes !== null ? `${fmt(r.total_minutes)} min` : "time n/a"}{r.n_ratings > 0 && r.mean_rating !== null ? ` · ${r.mean_rating.toFixed(1)} stars (${r.n_ratings})` : ""}</span>
              <Button size="sm" variant="ghost" onClick={() => onCompare({ key: `recipe:${r.recipe_id}`, name: r.name })}><Plus /> Compare</Button>
            </div>
          </Card>
        ))}
      </div>
      {res.data && <Pager page={page} total={res.data.total} size={18} onPage={setPage} />}
    </>
  )
}

function SmartTab({ onOpenRecipe, onOpenFood, onCompare }: { onOpenRecipe: (id: number) => void; onOpenFood: (id: string) => void; onCompare: (p: Pick) => void }) {
  const [q, setQ] = useState("")
  const [submitted, setSubmitted] = useState("")
  const [type, setType] = useState("all")
  const res = useQuery({ queryKey: ["semantic", submitted, type], enabled: submitted.length >= 2,
    queryFn: () => api<{ items: { doc_type: string; item_id: string; name: string; text: string; score: number }[] }>(`/api/search/semantic?${new URLSearchParams({ q: submitted, doc_type: type, k: "18" })}`) })
  return (
    <>
      <form className="mb-2 flex flex-col gap-3 sm:flex-row" onSubmit={(e) => { e.preventDefault(); setSubmitted(q.trim()) }}>
        <div className="relative flex-1"><Sparkles className="absolute top-1/2 left-3 size-4 -translate-y-1/2 text-primary" /><Input className="h-10 pl-9" placeholder="Describe it: warm comforting lentil soup, crunchy high protein snack..." value={q} onChange={(e) => setQ(e.target.value)} /></div>
        <Select value={type} onValueChange={setType}><SelectTrigger className="h-10 w-full sm:w-36"><SelectValue /></SelectTrigger><SelectContent><SelectItem value="all">Everything</SelectItem><SelectItem value="recipe">Recipes</SelectItem><SelectItem value="food">Foods</SelectItem></SelectContent></Select>
        <Button type="submit" className="h-10">Search</Button>
      </form>
      <p className="mb-4 text-xs text-muted-foreground">Meaning-based search with Sentence Transformers (all-MiniLM-L6-v2) and FAISS. The index holds descriptions only; nutrition numbers are read from MySQL when you open an item.</p>
      {!submitted && <EmptyState icon={<Sparkles className="size-5" />} title="Search by meaning" description="Unlike keyword search, this finds items that are similar in meaning even if the words differ." />}
      {res.isLoading && <LoadingGrid count={6} className="sm:grid-cols-2" itemClass="h-24" />}
      {res.isError && <ErrorState error={res.error} onRetry={() => res.refetch()} />}
      {res.data?.items.length === 0 && <EmptyState title="No matches" />}
      <div className="grid gap-3 sm:grid-cols-2">
        {res.data?.items.map((h) => (
          <Card key={h.doc_type + h.item_id} className="gap-0 py-0">
            <CardContent className="flex items-start gap-3 p-4">
              <div className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-secondary text-primary">{h.doc_type === "recipe" ? <ChefHat className="size-4" /> : <Apple className="size-4" />}</div>
              <button className="min-w-0 flex-1 text-left" onClick={() => (h.doc_type === "recipe" ? onOpenRecipe(Number(h.item_id)) : onOpenFood(h.item_id))}>
                <p className="truncate font-medium hover:text-primary">{h.name}</p>
                <p className="line-clamp-2 text-xs text-muted-foreground">{h.text}</p>
              </button>
              <div className="flex flex-col items-end gap-1">
                <Badge variant="outline" className="tabular-nums">{h.score.toFixed(2)}</Badge>
                <Button size="icon-sm" variant="ghost" aria-label="Add to compare" onClick={() => onCompare({ key: `${h.doc_type}:${h.item_id}`, name: h.name })}><Plus /></Button>
              </div>
            </CardContent>
          </Card>
        ))}
      </div>
    </>
  )
}

function FoodDialog({ id, onClose }: { id: string | null; onClose: () => void }) {
  const q = useQuery({ queryKey: ["food", id], queryFn: () => api<Food>(`/api/foods/${encodeURIComponent(id!)}`), enabled: !!id })
  const f = q.data
  return (
    <Dialog open={!!id} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="sm:max-w-lg">
        {q.isLoading && <LoadingBlock className="h-60" />}
        {q.isError && <ErrorState error={q.error} />}
        {f && (
          <>
            <DialogHeader><DialogTitle>{f.name}</DialogTitle><DialogDescription>{f.source}{f.food_group ? ` · ${f.food_group}` : ""}</DialogDescription></DialogHeader>
            <div className="space-y-4">
              <div>
                <p className="mb-2 text-sm font-medium">Per 100 g</p>
                <NutrientStrip r={{ calories_kcal: f.kcal_100g, protein_g: f.protein_100g, carbs_g: f.carbs_100g, fat_g: f.fat_100g }} />
                <div className="mt-2 grid grid-cols-3 gap-2 text-center text-xs text-muted-foreground">
                  <span>Fibre <b className="text-foreground">{fmt(f.fiber_100g, 1, " g")}</b></span><span>Sugar <b className="text-foreground">{fmt(f.sugar_100g, 1, " g")}</b></span><span>Sodium <b className="text-foreground">{fmt(f.sodium_100g, 0, " mg")}</b></span>
                </div>
              </div>
              {f.kcal_serving !== null && <p className="rounded-lg bg-muted/50 p-3 text-sm">One serving ({f.serving_unit ?? "serving"}): <b>{fmt(f.kcal_serving)} kcal</b>, {fmt(f.protein_serving, 1)} g protein</p>}
              {f.energy_split && (
                <div><p className="mb-1.5 text-xs text-muted-foreground">Energy split: protein {f.energy_split.protein}%, carbs {f.energy_split.carbs}%, fat {f.energy_split.fat}%</p>
                  <div className="flex h-2.5 overflow-hidden rounded-full"><div style={{ width: `${f.energy_split.protein}%`, background: "var(--chart-3)" }} /><div style={{ width: `${f.energy_split.carbs}%`, background: "var(--chart-2)" }} /><div style={{ width: `${f.energy_split.fat}%`, background: "var(--chart-4)" }} /></div></div>
              )}
              <p className="text-xs text-muted-foreground">Missing values are shown as n/a. They are unknown in the source data, not zero.</p>
            </div>
          </>
        )}
      </DialogContent>
    </Dialog>
  )
}

const COLORS = ["var(--chart-1)", "var(--chart-2)", "var(--chart-3)", "var(--chart-4)"]

function CompareDialog({ picks, open, onClose }: { picks: Pick[]; open: boolean; onClose: () => void }) {
  const keys = picks.map((p) => p.key).join(",")
  const q = useQuery({ queryKey: ["compare", keys], queryFn: () => api<{ items: CompareItem[] }>(`/api/compare?items=${encodeURIComponent(keys)}`), enabled: open && picks.length >= 2 })
  const items = q.data?.items ?? []
  const metrics = [["protein_g", "Protein (g)"], ["carbs_g", "Carbs (g)"], ["fat_g", "Fat (g)"], ["fiber_g", "Fibre (g)"]] as const
  const data = metrics.map(([k, label]) => ({ metric: label, ...Object.fromEntries(items.map((it, i) => [`i${i}`, it[k] ?? 0])) }))
  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="sm:max-w-3xl">
        <DialogHeader><DialogTitle>Side by side</DialogTitle><DialogDescription>Recipes are per serving, foods per 100 g. All values from MySQL.</DialogDescription></DialogHeader>
        {q.isLoading && <LoadingBlock className="h-72" />}
        {q.isError && <ErrorState error={q.error} />}
        {items.length > 0 && (
          <div className="space-y-4">
            <div className="h-60">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={data}>
                  <CartesianGrid vertical={false} strokeDasharray="3 3" stroke="var(--border)" />
                  <XAxis dataKey="metric" tickLine={false} axisLine={false} fontSize={11} />
                  <YAxis tickLine={false} axisLine={false} fontSize={11} width={36} />
                  <Tooltip contentStyle={{ borderRadius: 10, fontSize: 12 }} />
                  <Legend wrapperStyle={{ fontSize: 11 }} />
                  {items.map((it, i) => <Bar key={it.id} dataKey={`i${i}`} name={it.name.length > 28 ? it.name.slice(0, 28) + "..." : it.name} fill={COLORS[i]} radius={[4, 4, 0, 0]} />)}
                </BarChart>
              </ResponsiveContainer>
            </div>
            <div className="overflow-x-auto">
              <Table>
                <TableHeader><TableRow><TableHead />{items.map((it) => <TableHead key={it.id} className="max-w-40 text-right whitespace-normal">{it.name}<span className="block text-[10px] font-normal text-muted-foreground">{it.basis}</span></TableHead>)}</TableRow></TableHeader>
                <TableBody>
                  {([["calories_kcal", "Calories", " kcal"], ["protein_g", "Protein", " g"], ["carbs_g", "Carbs", " g"], ["fat_g", "Fat", " g"], ["fiber_g", "Fibre", " g"], ["sugar_g", "Sugar", " g"], ["sodium_mg", "Sodium", " mg"]] as const).map(([k, label, u]) => (
                    <TableRow key={k}><TableCell className="font-medium">{label}</TableCell>{items.map((it) => <TableCell key={it.id} className="text-right tabular-nums">{fmt(it[k], 1, u)}</TableCell>)}</TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          </div>
        )}
      </DialogContent>
    </Dialog>
  )
}

export default function Explorer() {
  const [picks, setPicks] = useState<Pick[]>([])
  const [cmp, setCmp] = useState(false)
  const [recipe, setRecipe] = useState<number | null>(null)
  const [food, setFood] = useState<string | null>(null)
  const add = (p: Pick) => {
    if (picks.some((x) => x.key === p.key)) return toast.info("Already in the comparison")
    if (picks.length >= 4) return toast.error("You can compare up to 4 items")
    setPicks([...picks, p])
    toast.success(`Added ${p.name.slice(0, 40)} to compare`)
  }
  return (
    <>
      <PageHeader eyebrow="Food explorer" title="Explore foods and recipes" description="7,903 recipes and 8,807 foods (Indian INDB and USDA SR Legacy) stored in MySQL. Search, filter, compare and open any item." />
      <Tabs defaultValue="foods">
        <TabsList className="mb-4"><TabsTrigger value="foods"><Apple /> Foods</TabsTrigger><TabsTrigger value="recipes"><ChefHat /> Recipes</TabsTrigger><TabsTrigger value="smart"><Sparkles /> Smart search</TabsTrigger></TabsList>
        <TabsContent value="foods"><FoodsTab onCompare={add} onOpen={setFood} /></TabsContent>
        <TabsContent value="recipes"><RecipesTab onCompare={add} onOpen={setRecipe} /></TabsContent>
        <TabsContent value="smart"><SmartTab onCompare={add} onOpenRecipe={setRecipe} onOpenFood={setFood} /></TabsContent>
      </Tabs>
      {picks.length > 0 && (
        <div className="fixed inset-x-0 bottom-4 z-30 flex justify-center px-4 lg:pl-64">
          <div className="flex max-w-3xl flex-wrap items-center gap-2 rounded-2xl border bg-background/95 p-2 pl-4 shadow-xl backdrop-blur">
            <GitCompare className="size-4 text-primary" />
            {picks.map((p) => (
              <Badge key={p.key} variant="secondary" className="max-w-44 gap-1 py-1"><span className="truncate">{p.name}</span>
                <button aria-label={`Remove ${p.name}`} onClick={() => setPicks(picks.filter((x) => x.key !== p.key))}><X className="size-3" /></button></Badge>
            ))}
            <Button size="sm" disabled={picks.length < 2} onClick={() => setCmp(true)}>Compare {picks.length}</Button>
          </div>
        </div>
      )}
      <CompareDialog picks={picks} open={cmp} onClose={() => setCmp(false)} />
      <RecipeDialog id={recipe} onClose={() => setRecipe(null)} />
      <FoodDialog id={food} onClose={() => setFood(null)} />
    </>
  )
}
