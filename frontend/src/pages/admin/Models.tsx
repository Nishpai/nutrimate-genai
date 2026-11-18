import { useState } from "react"
import { useQuery } from "@tanstack/react-query"
import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Scatter, ScatterChart, Tooltip, XAxis, YAxis, ZAxis } from "recharts"
import { FlaskConical, Gauge, HardDrive, ShieldCheck, Timer } from "lucide-react"
import { PageHeader } from "@/components/app/page-header"
import { StatCard } from "@/components/app/stat"
import { EmptyState, ErrorState, LoadingGrid } from "@/components/app/states"
import { Badge } from "@/components/ui/badge"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group"
import { api } from "@/lib/api"
import { fmt, titleCase } from "@/lib/format"

type M = { "precision@10": number; "recall@10": number; "ndcg@10": number; "hit_rate@10": number; coverage: number; users: number }
type Metrics = {
  protocol: string; k: number; test_users: number; candidate_items: number; train_interactions: number; val_interactions: number; test_interactions: number
  lightfm_params: Record<string, number | string>; hybrid_weights: Record<string, number>
  reranker: { objective: string; candidates: number; train_rows: number; train_positives: number; holdout_ndcg_hybrid_order: number; chosen: Record<string, number>; enabled_in_app: boolean; selection: { params: Record<string, number>; holdout_ndcg: number }[] }
  ncf_train_seconds: number; models: Record<string, M>; cold_start_3_likes: Record<string, M>
  constraints: { profiles: number; violations_with_filter: number; recommendations_with_filter: number; violations_without_filter: number; recommendations_without_filter: number; violation_rate_without_filter: number }
  seconds: number
}
type Bench = { file?: string; source_mb: number; rows: number; columns?: number; seconds: number; rows_per_second: number; peak_rss_mb: number; output_mb: number; batch_rows?: number; null_cells?: number; machine?: string }
type ModelsResp = {
  metrics: Metrics | null; best_params: { val_ndcg10_lightfm: number; val_ndcg10_hybrid: number; lightfm_trials: { params: Record<string, number>; value: number }[]; hybrid_trials?: { params: Record<string, number>; value: number }[] } | null
  feature_importance: Record<string, number> | null; train_info: Record<string, unknown> | null
  faiss: { documents: number; dimension: number; model: string; seconds: number } | null
  ingest_benchmark: Bench | null
  mlflow_runs: ({ run_id: string; name: string; status: string; start_time: string; metrics: Record<string, number> } | { error: string })[]
}

const LABEL: Record<string, string> = { popularity: "Popularity", content: "Content (TF-IDF)", lightfm: "LightFM", lightfm_foldin: "LightFM fold-in", ncf_pytorch: "NCF (PyTorch)", hybrid: "Hybrid", hybrid_xgb_rerank: "Hybrid + XGBoost" }
const METRIC = ["ndcg@10", "precision@10", "recall@10", "hit_rate@10", "coverage"] as const
const tip = { contentStyle: { borderRadius: 10, border: "1px solid var(--border)", fontSize: 12 } }

export default function AdminModels() {
  const q = useQuery({ queryKey: ["admin-models"], queryFn: () => api<ModelsResp>("/api/admin/models") })
  const [metric, setMetric] = useState<(typeof METRIC)[number]>("ndcg@10")
  const d = q.data
  const m = d?.metrics
  return (
    <>
      <PageHeader eyebrow="Admin" title="Model performance" description="Offline evaluation from reports/metrics.json, produced by ml/evaluate.py and logged to MLflow. Numbers come from real runs on held-out data." />
      {q.isLoading && <LoadingGrid count={4} className="lg:grid-cols-4" itemClass="h-24" />}
      {q.isError && <ErrorState error={q.error} onRetry={() => q.refetch()} />}
      {d && !m && <EmptyState icon={<FlaskConical className="size-5" />} title="No evaluation yet" description="Run python -m ml.evaluate (or dvc repro) to create reports/metrics.json." />}
      {d && m && (
        <Tabs defaultValue="ranking">
          <TabsList className="mb-4 flex-wrap"><TabsTrigger value="ranking">Ranking quality</TabsTrigger><TabsTrigger value="cold">Cold start & rules</TabsTrigger><TabsTrigger value="tuning">Tuning & reranker</TabsTrigger><TabsTrigger value="mlflow">MLflow runs</TabsTrigger><TabsTrigger value="data">Data & index</TabsTrigger></TabsList>
          <TabsContent value="ranking" className="space-y-6">
            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
              <StatCard icon={<Gauge className="size-5" />} label="Hybrid NDCG@10" value={fmt(m.models.hybrid?.["ndcg@10"], 4)} sub={`popularity ${fmt(m.models.popularity?.["ndcg@10"], 4)}`} />
              <StatCard icon={<FlaskConical className="size-5" />} label="Test users" value={fmt(m.test_users)} sub={`${fmt(m.candidate_items)} candidate recipes`} />
              <StatCard icon={<ShieldCheck className="size-5" />} label="Rule violations" value={`${m.constraints.violations_with_filter} / ${fmt(m.constraints.recommendations_with_filter)}`} sub={`${fmt(100 * m.constraints.violation_rate_without_filter, 1)}% without the filter`} />
              <StatCard icon={<Timer className="size-5" />} label="Evaluation time" value={`${fmt(m.seconds, 1)} s`} sub={`NCF trained in ${m.ncf_train_seconds} s`} />
            </div>
            <Card>
              <CardHeader className="flex flex-row flex-wrap items-start justify-between gap-3">
                <div><CardTitle>Models compared at k = {m.k}</CardTitle><CardDescription>{m.protocol}</CardDescription></div>
                <ToggleGroup type="single" size="sm" variant="outline" value={metric} onValueChange={(v) => v && setMetric(v as typeof metric)}>
                  {METRIC.map((x) => <ToggleGroupItem key={x} value={x} className="px-2.5 text-xs">{x}</ToggleGroupItem>)}
                </ToggleGroup>
              </CardHeader>
              <CardContent className="h-72 pl-0">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={Object.entries(m.models).map(([k, v]) => ({ model: LABEL[k] ?? k, value: v[metric] }))}>
                    <CartesianGrid vertical={false} strokeDasharray="3 3" stroke="var(--border)" />
                    <XAxis dataKey="model" tickLine={false} axisLine={false} fontSize={11} interval={0} />
                    <YAxis tickLine={false} axisLine={false} fontSize={11} width={52} />
                    <Tooltip {...tip} formatter={(v) => [Number(v).toFixed(4), metric]} />
                    <Bar dataKey="value" fill="var(--chart-1)" radius={[6, 6, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </CardContent>
            </Card>
            <Card className="py-0"><Table><TableHeader><TableRow><TableHead className="pl-4">Model</TableHead>{METRIC.map((x) => <TableHead key={x} className="text-right">{x}</TableHead>)}</TableRow></TableHeader>
              <TableBody>{Object.entries(m.models).map(([k, v]) => <TableRow key={k}><TableCell className="pl-4 font-medium">{LABEL[k] ?? k}{k === "hybrid" && <Badge className="ml-2">used in app</Badge>}</TableCell>{METRIC.map((x) => <TableCell key={x} className="text-right tabular-nums">{v[x].toFixed(4)}</TableCell>)}</TableRow>)}</TableBody></Table></Card>
            <p className="text-xs text-muted-foreground">Absolute values are low because each user's relevant test items are a handful out of {fmt(m.candidate_items)} recipes. The useful comparison is between rows. Small gaps (around 0.001 to 0.002 NDCG) are within run-to-run noise.</p>
          </TabsContent>
          <TabsContent value="cold" className="space-y-6">
            <div className="grid gap-6 lg:grid-cols-2">
              <Card>
                <CardHeader><CardTitle>Cold start: 3 liked recipes</CardTitle><CardDescription>Each test user is reduced to three liked recipes, like a new account after onboarding.</CardDescription></CardHeader>
                <CardContent className="h-64 pl-0">
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart data={Object.entries(m.cold_start_3_likes).map(([k, v]) => ({ model: LABEL[k] ?? k, ndcg: v["ndcg@10"], hit: v["hit_rate@10"] }))}>
                      <CartesianGrid vertical={false} strokeDasharray="3 3" stroke="var(--border)" />
                      <XAxis dataKey="model" tickLine={false} axisLine={false} fontSize={11} /><YAxis tickLine={false} axisLine={false} fontSize={11} width={52} />
                      <Tooltip {...tip} formatter={(v) => Number(v).toFixed(4)} /><Legend wrapperStyle={{ fontSize: 11 }} />
                      <Bar dataKey="ndcg" name="NDCG@10" fill="var(--chart-1)" radius={[4, 4, 0, 0]} /><Bar dataKey="hit" name="Hit rate@10" fill="var(--chart-3)" radius={[4, 4, 0, 0]} />
                    </BarChart>
                  </ResponsiveContainer>
                </CardContent>
              </Card>
              <Card>
                <CardHeader><CardTitle>Dietary constraint check</CardTitle><CardDescription>{m.constraints.profiles} random profiles with diets and allergies, 10 recommendations each.</CardDescription></CardHeader>
                <CardContent className="space-y-4">
                  {[["With the constraint filter (as in the app)", m.constraints.violations_with_filter, m.constraints.recommendations_with_filter, "bg-emerald-500"], ["Same ranking without the filter", m.constraints.violations_without_filter, m.constraints.recommendations_without_filter, "bg-rose-500"]].map(([label, v, n, c]) => (
                    <div key={label as string}>
                      <div className="mb-1 flex justify-between text-sm"><span>{label}</span><b className="tabular-nums">{fmt(v as number)} / {fmt(n as number)} violate</b></div>
                      <div className="h-3 overflow-hidden rounded-full bg-muted"><div className={`h-full ${c}`} style={{ width: `${(100 * (v as number)) / (n as number)}%` }} /></div>
                    </div>
                  ))}
                  <p className="text-xs text-muted-foreground">Hard rules are applied before scoring, so a recipe that breaks a rule can never be ranked. The check uses the same text rules as the app, so it proves the filter is applied, not that the text rules catch every ingredient.</p>
                </CardContent>
              </Card>
            </div>
          </TabsContent>
          <TabsContent value="tuning" className="space-y-6">
            <div className="grid gap-6 lg:grid-cols-2">
              <Card>
                <CardHeader><CardTitle>Optuna: LightFM trials</CardTitle><CardDescription>Validation NDCG@10 by number of components. Best {fmt(d.best_params?.val_ndcg10_lightfm, 4)}.</CardDescription></CardHeader>
                <CardContent className="h-64 pl-0">
                  <ResponsiveContainer width="100%" height="100%">
                    <ScatterChart>
                      <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
                      <XAxis type="number" dataKey="epochs" name="epochs" tickLine={false} fontSize={11} />
                      <YAxis type="number" dataKey="value" name="NDCG@10" tickLine={false} fontSize={11} width={52} domain={["auto", "auto"]} />
                      <ZAxis type="number" dataKey="no_components" range={[30, 220]} name="components" />
                      <Tooltip {...tip} />
                      <Scatter data={(d.best_params?.lightfm_trials ?? []).map((t) => ({ ...t.params, value: t.value }))} fill="var(--chart-1)" />
                    </ScatterChart>
                  </ResponsiveContainer>
                </CardContent>
              </Card>
              <Card>
                <CardHeader><CardTitle>Chosen settings</CardTitle><CardDescription>Selected on the validation split, then evaluated once on test.</CardDescription></CardHeader>
                <CardContent className="space-y-3 text-sm">
                  <div><p className="mb-1 font-medium">LightFM</p><div className="flex flex-wrap gap-1.5">{Object.entries(m.lightfm_params).map(([k, v]) => <Badge key={k} variant="secondary" className="font-normal">{k}: {typeof v === "number" ? Number(v.toPrecision(3)) : v}</Badge>)}</div></div>
                  <div><p className="mb-1 font-medium">Hybrid blend weights</p><div className="flex h-3 overflow-hidden rounded-full">{Object.entries(m.hybrid_weights).map(([k, v], i) => <div key={k} style={{ width: `${100 * v}%`, background: `var(--chart-${i + 1})` }} title={k} />)}</div>
                    <p className="mt-1 text-xs text-muted-foreground">{Object.entries(m.hybrid_weights).map(([k, v]) => `${k} ${v}`).join(" · ")} (validation NDCG {fmt(d.best_params?.val_ndcg10_hybrid, 4)})</p></div>
                  <div className="rounded-lg border bg-muted/30 p-3">
                    <p className="font-medium">XGBoost reranker ({m.reranker.objective}): {m.reranker.enabled_in_app ? "enabled" : "disabled in the app"}</p>
                    <p className="mt-1 text-xs text-muted-foreground">Trained on {fmt(m.reranker.train_rows)} candidate rows. On a holdout of validation users the best grid setting scored {fmt(m.reranker.selection[0]?.holdout_ndcg, 4)} against {fmt(m.reranker.holdout_ndcg_hybrid_order, 4)} for the plain hybrid order, so it is switched off. On the test split it scored slightly higher; that gap is within noise and test results were not used to decide.</p>
                  </div>
                </CardContent>
              </Card>
            </div>
            {d.feature_importance && (
              <Card>
                <CardHeader><CardTitle>Reranker feature importance</CardTitle><CardDescription>XGBoost gain, normalised.</CardDescription></CardHeader>
                <CardContent className="h-72 pl-0">
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart layout="vertical" data={Object.entries(d.feature_importance).sort((a, b) => b[1] - a[1]).map(([k, v]) => ({ f: k, v }))} margin={{ left: 24 }}>
                      <CartesianGrid horizontal={false} strokeDasharray="3 3" stroke="var(--border)" />
                      <XAxis type="number" tickLine={false} fontSize={11} /><YAxis type="category" dataKey="f" tickLine={false} axisLine={false} fontSize={11} width={110} />
                      <Tooltip {...tip} /><Bar dataKey="v" fill="var(--chart-3)" radius={[0, 4, 4, 0]} />
                    </BarChart>
                  </ResponsiveContainer>
                </CardContent>
              </Card>
            )}
          </TabsContent>
          <TabsContent value="mlflow">
            <Card className="py-0">
              <CardHeader className="pt-6"><CardTitle>Recent MLflow runs</CardTitle><CardDescription>Experiment nutrimate-recommender. Open the full UI with: mlflow ui --backend-store-uri sqlite:///mlflow.db</CardDescription></CardHeader>
              {d.mlflow_runs.length === 0 ? <div className="p-6"><EmptyState title="No runs logged" /></div> : "error" in d.mlflow_runs[0] ? <p className="p-6 text-sm text-muted-foreground">{(d.mlflow_runs[0] as { error: string }).error}</p> : (
                <Table><TableHeader><TableRow><TableHead className="pl-6">Run</TableHead><TableHead>Status</TableHead><TableHead>Started</TableHead><TableHead className="pr-6">Key metrics</TableHead></TableRow></TableHeader>
                  <TableBody>{d.mlflow_runs.map((r) => "run_id" in r && (
                    <TableRow key={r.run_id}><TableCell className="pl-6 font-medium">{r.name}</TableCell><TableCell><Badge variant="secondary">{r.status}</Badge></TableCell><TableCell className="text-xs text-muted-foreground">{r.start_time.slice(0, 16)}</TableCell>
                      <TableCell className="max-w-lg pr-6"><div className="flex flex-wrap gap-1">{Object.entries(r.metrics).filter(([k]) => k.includes("ndcg")).slice(0, 5).map(([k, v]) => <Badge key={k} variant="outline" className="font-mono text-[10px]">{k}: {v.toFixed(4)}</Badge>)}</div></TableCell></TableRow>
                  ))}</TableBody></Table>
              )}
            </Card>
          </TabsContent>
          <TabsContent value="data" className="space-y-6">
            <div className="grid gap-6 lg:grid-cols-2">
              <Card>
                <CardHeader><CardTitle className="flex items-center gap-2"><HardDrive className="size-4 text-primary" /> Large file ingest benchmark</CardTitle><CardDescription>Streaming clean of a large CSV through the same code the admin job uses.</CardDescription></CardHeader>
                <CardContent className="text-sm">
                  {d.ingest_benchmark ? (
                    <div className="grid grid-cols-2 gap-3">
                      {[["Input size", `${fmt(d.ingest_benchmark.source_mb / 1000, 2)} GB`], ["Rows", fmt(d.ingest_benchmark.rows)], ["Time", `${fmt(d.ingest_benchmark.seconds, 1)} s`], ["Throughput", `${fmt(d.ingest_benchmark.rows_per_second)} rows/s`], ["Peak memory", `${fmt(d.ingest_benchmark.peak_rss_mb)} MB`], ["Parquet output", `${fmt(d.ingest_benchmark.output_mb)} MB`]].map(([k, v]) => (
                        <div key={k} className="rounded-lg bg-muted/40 p-3"><p className="text-xs text-muted-foreground">{k}</p><p className="text-lg font-semibold">{v}</p></div>
                      ))}
                      {d.ingest_benchmark.machine && <p className="col-span-2 text-xs text-muted-foreground">{d.ingest_benchmark.machine}</p>}
                    </div>
                  ) : <EmptyState title="No benchmark yet" description="Run python -m ml.benchmark_ingest" className="p-6" />}
                </CardContent>
              </Card>
              <Card>
                <CardHeader><CardTitle>Training data and index</CardTitle><CardDescription>From reports/train_info.json and models/faiss_info.json.</CardDescription></CardHeader>
                <CardContent className="space-y-1 text-sm">
                  {[["Train interactions", m.train_interactions], ["Validation interactions", m.val_interactions], ["Test interactions", m.test_interactions], ...Object.entries(d.train_info ?? {}).filter(([, v]) => typeof v === "number")].map(([k, v]) => (
                    <div key={k as string} className="flex justify-between"><span className="text-muted-foreground">{titleCase(String(k))}</span><b className="tabular-nums">{fmt(v as number, 1)}</b></div>
                  ))}
                  {d.faiss && <div className="flex justify-between"><span className="text-muted-foreground">FAISS documents ({d.faiss.dimension}-d)</span><b className="tabular-nums">{fmt(d.faiss.documents)}</b></div>}
                </CardContent>
              </Card>
            </div>
          </TabsContent>
        </Tabs>
      )}
    </>
  )
}
