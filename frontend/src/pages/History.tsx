import { useState } from "react"
import { useQuery } from "@tanstack/react-query"
import { Bookmark, Bot, Eye, History as HistoryIcon, Sparkles, ThumbsDown, ThumbsUp, User } from "lucide-react"
import { PageHeader } from "@/components/app/page-header"
import { RecipeDialog } from "@/components/app/recipe"
import { EmptyState, ErrorState, LoadingBlock } from "@/components/app/states"
import { Badge } from "@/components/ui/badge"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { api } from "@/lib/api"
import { dateTime, dayName, fmt, titleCase } from "@/lib/format"

type Interaction = { id: number; item_type: string; item_id: string; action: string; created_at: string; name: string | null }
type RecLog = { id: number; source: string; created_at: string; context: { constraints?: string[] }; model_info: { mode?: string; passed?: number }; items: { rank_pos: number; recipe_id: number; score: number; name: string; calories_kcal: number | null; protein_g: number | null }[] }
type Chat = { id: number; role: string; content: string; meta: { mode?: string; intent?: string } | null; created_at: string }
type LogDay = { log_date: string; entries: number; calories_kcal: number | null; protein_g: number | null }
type ProfChange = { id: number; changed_at: string; snapshot: Record<string, unknown> }
type Prefs = Record<"liked" | "disliked" | "saved", { recipe_id: number; name: string | null }[]>

const ICON: Record<string, React.ReactNode> = { like: <ThumbsUp className="size-3.5" />, dislike: <ThumbsDown className="size-3.5" />, save: <Bookmark className="size-3.5" />, unsave: <Bookmark className="size-3.5" />, view: <Eye className="size-3.5" /> }

function useList<T>(key: string, path: string) {
  return useQuery({ queryKey: ["history", key], queryFn: () => api<T>(path) })
}

function Wrap<T>({ q, empty, children }: { q: { isLoading: boolean; isError: boolean; error: unknown; data?: T[]; refetch: () => void }; empty: string; children: (d: T[]) => React.ReactNode }) {
  if (q.isLoading) return <LoadingBlock className="h-72" />
  if (q.isError) return <ErrorState error={q.error} onRetry={q.refetch} />
  if (!q.data?.length) return <EmptyState icon={<HistoryIcon className="size-5" />} title={empty} />
  return <>{children(q.data)}</>
}

export default function HistoryPage() {
  const [open, setOpen] = useState<number | null>(null)
  const inter = useList<Interaction[]>("interactions", "/api/history/interactions?limit=100")
  const recs = useList<RecLog[]>("recs", "/api/history/recommendations?limit=20")
  const chats = useList<Chat[]>("chats", "/api/history/chats?limit=100")
  const logs = useList<LogDay[]>("logs", "/api/history/logs?days=60")
  const prof = useList<ProfChange[]>("profile", "/api/history/preferences")
  const prefs = useQuery({ queryKey: ["preferences"], queryFn: () => api<Prefs>("/api/preferences") })
  return (
    <>
      <PageHeader eyebrow="History" title="Your history" description="Everything NutriMate stored about your activity. Likes and dislikes feed the recommender; logs feed the dashboard." />
      <Tabs defaultValue="activity">
        <TabsList className="mb-4 flex-wrap">
          <TabsTrigger value="activity">Activity</TabsTrigger><TabsTrigger value="taste">Taste profile</TabsTrigger><TabsTrigger value="recs">Recommendations</TabsTrigger>
          <TabsTrigger value="chats">Conversations</TabsTrigger><TabsTrigger value="logs">Logged days</TabsTrigger><TabsTrigger value="profile">Profile changes</TabsTrigger>
        </TabsList>
        <TabsContent value="activity">
          <Wrap q={inter} empty="No activity yet">{(rows) => (
            <Card className="py-0"><Table><TableHeader><TableRow><TableHead className="pl-4">Action</TableHead><TableHead>Recipe</TableHead><TableHead className="text-right pr-4">When</TableHead></TableRow></TableHeader>
              <TableBody>{rows.map((r) => (
                <TableRow key={r.id} className="cursor-pointer" onClick={() => r.item_type === "recipe" && setOpen(Number(r.item_id))}>
                  <TableCell className="pl-4"><Badge variant={r.action === "like" ? "default" : "secondary"} className="gap-1">{ICON[r.action]}{titleCase(r.action)}</Badge></TableCell>
                  <TableCell className="max-w-md truncate">{r.name ?? r.item_id}</TableCell>
                  <TableCell className="pr-4 text-right text-muted-foreground">{dateTime(r.created_at)}</TableCell>
                </TableRow>))}</TableBody></Table></Card>
          )}</Wrap>
        </TabsContent>
        <TabsContent value="taste">
          {prefs.isLoading ? <LoadingBlock className="h-60" /> : prefs.isError ? <ErrorState error={prefs.error} /> : (
            <div className="grid gap-4 md:grid-cols-3">
              {(["liked", "saved", "disliked"] as const).map((k) => (
                <Card key={k}><CardHeader><CardTitle className="flex items-center gap-2 text-base">{k === "liked" ? <ThumbsUp className="size-4 text-primary" /> : k === "saved" ? <Bookmark className="size-4 text-primary" /> : <ThumbsDown className="size-4 text-rose-500" />}{titleCase(k)} <Badge variant="secondary">{prefs.data?.[k].length}</Badge></CardTitle></CardHeader>
                  <CardContent className="space-y-1">{prefs.data?.[k].length ? prefs.data[k].map((r) => <button key={r.recipe_id} onClick={() => setOpen(r.recipe_id)} className="block w-full truncate rounded-md px-2 py-1.5 text-left text-sm hover:bg-secondary">{r.name}</button>) : <p className="text-sm text-muted-foreground">None yet.</p>}</CardContent></Card>
              ))}
            </div>
          )}
        </TabsContent>
        <TabsContent value="recs">
          <Wrap q={recs} empty="No recommendations yet">{(rows) => (
            <div className="space-y-3">{rows.map((lg) => (
              <Card key={lg.id} className="gap-3 py-4"><CardContent className="space-y-2 px-4">
                <div className="flex flex-wrap items-center gap-2 text-sm"><Sparkles className="size-4 text-primary" /><b>{titleCase(lg.source)}</b><span className="text-muted-foreground">{dateTime(lg.created_at)}</span>
                  {lg.model_info.mode && <Badge variant="outline">{lg.model_info.mode}</Badge>}{lg.model_info.passed !== undefined && <Badge variant="secondary">{lg.model_info.passed} passed rules</Badge>}</div>
                {lg.context.constraints && lg.context.constraints.length > 0 && <div className="flex flex-wrap gap-1">{lg.context.constraints.map((c) => <Badge key={c} variant="outline" className="text-[11px]">{c}</Badge>)}</div>}
                <ol className="grid gap-1 text-sm sm:grid-cols-2">{lg.items.slice(0, 6).map((it) => <li key={it.rank_pos}><button onClick={() => setOpen(it.recipe_id)} className="truncate text-left hover:text-primary"><span className="text-muted-foreground">{it.rank_pos}.</span> {it.name} <span className="text-xs text-muted-foreground">({fmt(it.calories_kcal)} kcal)</span></button></li>)}</ol>
              </CardContent></Card>))}</div>
          )}</Wrap>
        </TabsContent>
        <TabsContent value="chats">
          <Wrap q={chats} empty="No conversations yet">{(rows) => (
            <Card><CardContent className="space-y-3">{rows.map((m) => (
              <div key={m.id} className="flex gap-3 text-sm">
                <div className="mt-0.5 flex size-7 shrink-0 items-center justify-center rounded-full bg-secondary text-primary">{m.role === "user" ? <User className="size-3.5" /> : <Bot className="size-3.5" />}</div>
                <div className="min-w-0 flex-1"><p className="line-clamp-3 whitespace-pre-wrap">{m.content}</p>
                  <p className="text-xs text-muted-foreground">{dateTime(m.created_at)}{m.meta?.mode ? ` · ${m.meta.mode}` : ""}{m.meta?.intent ? ` · ${m.meta.intent}` : ""}</p></div>
              </div>))}</CardContent></Card>
          )}</Wrap>
        </TabsContent>
        <TabsContent value="logs">
          <Wrap q={logs} empty="No logged days in the last 60 days">{(rows) => (
            <Card className="py-0"><Table><TableHeader><TableRow><TableHead className="pl-4">Day</TableHead><TableHead className="text-right">Entries</TableHead><TableHead className="text-right">Calories</TableHead><TableHead className="pr-4 text-right">Protein</TableHead></TableRow></TableHeader>
              <TableBody>{rows.map((r) => <TableRow key={r.log_date}><TableCell className="pl-4">{dayName(r.log_date)}</TableCell><TableCell className="text-right">{r.entries}</TableCell><TableCell className="text-right tabular-nums">{fmt(r.calories_kcal)} kcal</TableCell><TableCell className="pr-4 text-right tabular-nums">{fmt(r.protein_g, 1)} g</TableCell></TableRow>)}</TableBody></Table></Card>
          )}</Wrap>
        </TabsContent>
        <TabsContent value="profile">
          <Wrap q={prof} empty="No profile changes yet">{(rows) => (
            <div className="space-y-3">{rows.map((r) => {
              const s = r.snapshot as Record<string, unknown>
              return (
                <Card key={r.id} className="py-4"><CardContent className="px-4 text-sm">
                  <p className="mb-2 font-medium">{dateTime(r.changed_at)}</p>
                  <div className="flex flex-wrap gap-1.5">
                    <Badge variant="secondary">Diet: {String(s.diet)}</Badge>
                    {s.calorie_target != null && <Badge variant="secondary">{String(s.calorie_target)} kcal</Badge>}
                    {s.protein_target_g != null && <Badge variant="secondary">{String(s.protein_target_g)} g protein</Badge>}
                    {(s.allergies as string[]).map((a) => <Badge key={a} variant="outline" className="text-rose-700">allergy: {a}</Badge>)}
                    {(s.restrictions as string[]).map((a) => <Badge key={a} variant="outline">avoid: {a}</Badge>)}
                    {(s.cuisines as string[]).map((a) => <Badge key={a} variant="outline" className="text-emerald-700">{a}</Badge>)}
                  </div>
                </CardContent></Card>
              )
            })}</div>
          )}</Wrap>
        </TabsContent>
      </Tabs>
      <RecipeDialog id={open} onClose={() => setOpen(null)} />
    </>
  )
}
