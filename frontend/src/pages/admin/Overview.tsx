import { Link } from "react-router-dom"
import { useQuery } from "@tanstack/react-query"
import { BarChart3, Boxes, ChefHat, ClipboardList, Database, FileBox, MessageSquare, MousePointerClick, Users } from "lucide-react"
import { PageHeader } from "@/components/app/page-header"
import { StatCard } from "@/components/app/stat"
import { ErrorState, LoadingGrid } from "@/components/app/states"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { api } from "@/lib/api"
import { fmt, titleCase } from "@/lib/format"

type Overview = {
  counts: Record<string, number>
  engine: { ready: boolean; error?: string; recipes?: number; weights?: Record<string, number>; reranker?: boolean; cf_items?: number; candidates?: number }
  retriever: { ready: boolean; info: { documents?: number; dimension?: number; model?: string; seconds?: number } | null }
  artifacts: { name: string; mb: number }[]
  processed_summary: Record<string, unknown> | null
}

export default function AdminOverview() {
  const q = useQuery({ queryKey: ["admin-overview"], queryFn: () => api<Overview>("/api/admin/overview"), refetchInterval: 15000 })
  const d = q.data
  return (
    <>
      <PageHeader eyebrow="Admin" title="System overview" description="Live counts from MySQL and the state of the loaded models."
        actions={<><Button variant="outline" asChild><Link to="/admin/datasets"><Database /> Datasets</Link></Button><Button asChild><Link to="/admin/models"><BarChart3 /> Model performance</Link></Button></>} />
      {q.isLoading && <LoadingGrid count={8} className="sm:grid-cols-2 lg:grid-cols-4" itemClass="h-24" />}
      {q.isError && <ErrorState error={q.error} onRetry={() => q.refetch()} />}
      {d && (
        <div className="space-y-6">
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <StatCard icon={<Users className="size-5" />} label="Users" value={fmt(d.counts.users)} />
            <StatCard icon={<ChefHat className="size-5" />} label="Recipes" value={fmt(d.counts.recipes)} />
            <StatCard icon={<Boxes className="size-5" />} label="Foods" value={fmt(d.counts.foods)} />
            <StatCard icon={<FileBox className="size-5" />} label="Datasets" value={fmt(d.counts.datasets)} sub={`${d.counts.running_jobs} jobs running`} />
            <StatCard icon={<MousePointerClick className="size-5" />} label="Interactions" value={fmt(d.counts.interactions)} />
            <StatCard icon={<ClipboardList className="size-5" />} label="Meal log entries" value={fmt(d.counts.meal_logs)} />
            <StatCard icon={<BarChart3 className="size-5" />} label="Saved plans" value={fmt(d.counts.meal_plans)} />
            <StatCard icon={<MessageSquare className="size-5" />} label="Chat messages" value={fmt(d.counts.chat_messages)} />
          </div>
          <div className="grid gap-6 lg:grid-cols-3">
            <Card>
              <CardHeader><CardTitle>Recommender</CardTitle><CardDescription>Loaded from the model artifacts at startup.</CardDescription></CardHeader>
              <CardContent className="space-y-2 text-sm">
                <Badge variant={d.engine.ready ? "default" : "destructive"}>{d.engine.ready ? "Ready" : `Not ready: ${d.engine.error}`}</Badge>
                {d.engine.ready && <>
                  <p>{fmt(d.engine.recipes)} recipes, {fmt(d.engine.cf_items)} with LightFM embeddings</p>
                  <p>Blend weights: {Object.entries(d.engine.weights ?? {}).map(([k, v]) => `${k} ${v}`).join(", ")}</p>
                  <p>XGBoost reranker: {d.engine.reranker ? "on" : "off (did not beat the hybrid order on validation)"}</p>
                </>}
              </CardContent>
            </Card>
            <Card>
              <CardHeader><CardTitle>Semantic index</CardTitle><CardDescription>FAISS over recipe and food descriptions.</CardDescription></CardHeader>
              <CardContent className="space-y-2 text-sm">
                <Badge variant={d.retriever.ready ? "default" : "secondary"}>{d.retriever.ready ? "Ready" : "Loading"}</Badge>
                {d.retriever.info && <>
                  <p>{fmt(d.retriever.info.documents)} documents, dimension {d.retriever.info.dimension}</p>
                  <p className="break-all text-muted-foreground">{d.retriever.info.model}</p>
                  {d.retriever.info.seconds !== undefined && <p className="text-muted-foreground">Built in {d.retriever.info.seconds} s</p>}
                </>}
              </CardContent>
            </Card>
            <Card>
              <CardHeader><CardTitle>Processed data</CardTitle><CardDescription>From data/processed/summary.json.</CardDescription></CardHeader>
              <CardContent className="space-y-1 text-sm">
                {d.processed_summary ? Object.entries(d.processed_summary).filter(([, v]) => typeof v === "number").slice(0, 9).map(([k, v]) => (
                  <div key={k} className="flex justify-between gap-2"><span className="text-muted-foreground">{titleCase(k)}</span><b className="tabular-nums">{fmt(v as number)}</b></div>
                )) : <p className="text-muted-foreground">No summary file.</p>}
              </CardContent>
            </Card>
          </div>
          <Card className="py-0">
            <CardHeader className="pt-6"><CardTitle>Model artifacts</CardTitle></CardHeader>
            <Table><TableHeader><TableRow><TableHead className="pl-6">File</TableHead><TableHead className="pr-6 text-right">Size</TableHead></TableRow></TableHeader>
              <TableBody>{d.artifacts.map((a) => <TableRow key={a.name}><TableCell className="pl-6 font-mono text-xs">{a.name}</TableCell><TableCell className="pr-6 text-right tabular-nums">{a.mb} MB</TableCell></TableRow>)}</TableBody></Table>
          </Card>
        </div>
      )}
    </>
  )
}
