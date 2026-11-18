import { useRef, useState } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Database, FileUp, FolderInput, Loader2, Play, RefreshCw, Trash2, Upload, Wand2 } from "lucide-react"
import { toast } from "sonner"
import { PageHeader, SectionTitle } from "@/components/app/page-header"
import { EmptyState, ErrorState, LoadingBlock } from "@/components/app/states"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Progress } from "@/components/ui/progress"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { api, tokenStore } from "@/lib/api"
import { dateTime, fmt, titleCase } from "@/lib/format"

type Column = { name: string; type: string; nulls: number; null_pct: number; min?: number | null; max?: number | null }
type Dataset = { id: number; name: string; original_filename: string; file_format: string; size_bytes: number; status: string; row_count: number | null; created_at: string; cleaned_path: string | null; profile: { rows?: number; columns?: Column[]; seconds?: number; source_bytes?: number; output_bytes?: number; suggested_food_mapping?: Record<string, string> } | null }
type Job = { id: number; job_type: string; dataset_id: number | null; dataset_name: string | null; status: string; progress: number; message: string | null; result: Record<string, unknown> | null; error: string | null; created_at: string; started_at: string | null; finished_at: string | null }

const size = (b: number) => (b >= 1e9 ? `${(b / 1e9).toFixed(2)} GB` : b >= 1e6 ? `${(b / 1e6).toFixed(1)} MB` : `${(b / 1e3).toFixed(1)} KB`)
const STATUS: Record<string, string> = { succeeded: "bg-emerald-100 text-emerald-800", failed: "bg-rose-100 text-rose-800", running: "bg-blue-100 text-blue-800", queued: "bg-muted text-muted-foreground", cleaned: "bg-emerald-100 text-emerald-800", imported: "bg-emerald-100 text-emerald-800", registered: "bg-muted text-muted-foreground", processing: "bg-blue-100 text-blue-800" }

function uploadWithProgress(file: File, name: string, onProgress: (p: number) => void) {
  return new Promise<Dataset>((resolve, reject) => {
    const xhr = new XMLHttpRequest()
    const form = new FormData()
    form.append("file", file)
    form.append("name", name)
    xhr.open("POST", "/api/admin/datasets/upload")
    const t = tokenStore.get()
    if (t) xhr.setRequestHeader("Authorization", `Bearer ${t}`)
    xhr.upload.onprogress = (e) => e.lengthComputable && onProgress((100 * e.loaded) / e.total)
    xhr.onload = () => {
      let body: { detail?: string } = {}
      try { body = JSON.parse(xhr.responseText) } catch { /* not json */ }
      if (xhr.status >= 200 && xhr.status < 300) resolve(body as Dataset)
      else reject(new Error(body.detail ?? `Upload failed (${xhr.status})`))
    }
    xhr.onerror = () => reject(new Error("Upload failed: server not reachable"))
    xhr.send(form)
  })
}

function ProfileDialog({ ds, onClose }: { ds: Dataset | null; onClose: () => void }) {
  const cols = ds?.profile?.columns ?? []
  return (
    <Dialog open={!!ds} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="sm:max-w-3xl">
        <DialogHeader><DialogTitle>{ds?.name}</DialogTitle><DialogDescription>{fmt(ds?.profile?.rows ?? ds?.row_count)} rows, {cols.length} columns{ds?.profile?.seconds ? `, cleaned in ${ds.profile.seconds} s` : ""}{ds?.profile?.output_bytes ? `, Parquet output ${size(ds.profile.output_bytes)}` : ""}. Unknown values are stored as NULL.</DialogDescription></DialogHeader>
        <div className="max-h-[60vh] overflow-auto">
          <Table><TableHeader><TableRow><TableHead>Column</TableHead><TableHead>Type</TableHead><TableHead className="text-right">Nulls</TableHead><TableHead className="text-right">Min</TableHead><TableHead className="text-right">Max</TableHead></TableRow></TableHeader>
            <TableBody>{cols.map((c) => <TableRow key={c.name}><TableCell className="font-mono text-xs">{c.name}{ds?.profile?.suggested_food_mapping && Object.values(ds.profile.suggested_food_mapping).includes(c.name) && <Badge variant="secondary" className="ml-1 h-4 text-[10px]">mapped</Badge>}</TableCell><TableCell className="text-xs text-muted-foreground">{c.type}</TableCell><TableCell className="text-right tabular-nums">{fmt(c.nulls)} ({c.null_pct}%)</TableCell><TableCell className="text-right tabular-nums">{typeof c.min === "number" ? fmt(c.min, 2) : ""}</TableCell><TableCell className="text-right tabular-nums">{typeof c.max === "number" ? fmt(c.max, 2) : ""}</TableCell></TableRow>)}</TableBody></Table>
        </div>
      </DialogContent>
    </Dialog>
  )
}

export default function AdminDatasets() {
  const qc = useQueryClient()
  const fileRef = useRef<HTMLInputElement>(null)
  const [file, setFile] = useState<File | null>(null)
  const [name, setName] = useState("")
  const [pct, setPct] = useState<number | null>(null)
  const [path, setPath] = useState("")
  const [view, setView] = useState<Dataset | null>(null)
  const ds = useQuery({ queryKey: ["datasets"], queryFn: () => api<Dataset[]>("/api/admin/datasets") })
  const jobs = useQuery({ queryKey: ["jobs"], queryFn: () => api<Job[]>("/api/admin/jobs"),
    refetchInterval: (q) => (q.state.data?.some((j) => j.status === "running" || j.status === "queued") ? 1500 : 10000) })
  const running = jobs.data?.some((j) => j.status === "running" || j.status === "queued")
  const refresh = () => { qc.invalidateQueries({ queryKey: ["datasets"] }); qc.invalidateQueries({ queryKey: ["jobs"] }) }
  const upload = async () => {
    if (!file) return
    setPct(0)
    try {
      await uploadWithProgress(file, name, setPct)
      toast.success("Uploaded. Run Clean & profile next.")
      setFile(null); setName("")
      if (fileRef.current) fileRef.current.value = ""
      refresh()
    } catch (e) {
      toast.error((e as Error).message)
    } finally {
      setPct(null)
    }
  }
  const register = useMutation({ mutationFn: () => api("/api/admin/datasets/register", { body: { path, name: "" } }), onSuccess: () => { setPath(""); toast.success("Registered"); refresh() }, onError: (e) => toast.error((e as Error).message) })
  const action = useMutation({
    mutationFn: (v: { kind: "process" | "import" | "delete" | "rebuild"; id?: number }) =>
      v.kind === "process" ? api(`/api/admin/datasets/${v.id}/process`, { method: "POST" })
        : v.kind === "import" ? api(`/api/admin/datasets/${v.id}/import-foods`, { body: {} })
          : v.kind === "rebuild" ? api("/api/admin/index/rebuild", { method: "POST" })
            : api(`/api/admin/datasets/${v.id}`, { method: "DELETE" }),
    onSuccess: (_d, v) => { toast.success(v.kind === "delete" ? "Dataset deleted" : "Job started"); refresh() },
    onError: (e) => toast.error((e as Error).message),
  })
  return (
    <>
      <PageHeader eyebrow="Admin" title="Datasets and jobs" description="Upload or register CSV, TSV, JSON, JSON Lines or Parquet files. Cleaning streams the file in batches to Parquet, so files over 1 GB work without loading them into memory."
        actions={<Button variant="outline" onClick={() => action.mutate({ kind: "rebuild" })} disabled={action.isPending}><Wand2 /> Rebuild FAISS index</Button>} />
      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader><CardTitle className="flex items-center gap-2"><Upload className="size-4 text-primary" /> Upload a file</CardTitle><CardDescription>Streamed to disk in 1 MB chunks. Good for files up to a few GB.</CardDescription></CardHeader>
          <CardContent className="space-y-3">
            <button type="button" onClick={() => fileRef.current?.click()} className="flex w-full flex-col items-center gap-2 rounded-xl border-2 border-dashed p-6 text-sm text-muted-foreground transition hover:border-primary/50 hover:bg-secondary/40">
              <FileUp className="size-6 text-primary" />{file ? <span className="font-medium text-foreground">{file.name} ({size(file.size)})</span> : "Choose a .csv, .tsv, .json, .jsonl or .parquet file"}
            </button>
            <input ref={fileRef} type="file" accept=".csv,.tsv,.txt,.json,.jsonl,.ndjson,.parquet" className="hidden" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
            <div className="flex gap-2"><Input placeholder="Display name (optional)" value={name} onChange={(e) => setName(e.target.value)} /><Button onClick={upload} disabled={!file || pct !== null}>{pct !== null ? <Loader2 className="animate-spin" /> : <Upload />} Upload</Button></div>
            {pct !== null && <div className="space-y-1"><Progress value={pct} /><p className="text-xs text-muted-foreground">{pct.toFixed(0)}% uploaded</p></div>}
          </CardContent>
        </Card>
        <Card>
          <CardHeader><CardTitle className="flex items-center gap-2"><FolderInput className="size-4 text-primary" /> Register a file on the server</CardTitle><CardDescription>For very large files already on this computer. Nothing is copied; the file is read in place.</CardDescription></CardHeader>
          <CardContent className="space-y-3">
            <div className="space-y-1.5"><Label htmlFor="path">Full path on the server</Label><Input id="path" placeholder="e.g. D:\\data\\nutrition_full.csv" value={path} onChange={(e) => setPath(e.target.value)} /></div>
            <Button onClick={() => register.mutate()} disabled={path.trim().length < 3 || register.isPending}>{register.isPending && <Loader2 className="animate-spin" />}Register</Button>
          </CardContent>
        </Card>
      </div>

      <div className="mt-8">
        <SectionTitle title="Datasets" description="Clean & profile creates a typed Parquet copy. Import foods maps nutrient columns per 100 g into the foods table." action={<Button size="sm" variant="ghost" onClick={refresh}><RefreshCw /> Refresh</Button>} />
        {ds.isLoading && <LoadingBlock className="h-40" />}
        {ds.isError && <ErrorState error={ds.error} onRetry={() => ds.refetch()} />}
        {ds.data?.length === 0 && <EmptyState icon={<Database className="size-5" />} title="No datasets yet" description="Upload or register a file to begin." />}
        {!!ds.data?.length && (
          <Card className="py-0"><Table><TableHeader><TableRow><TableHead className="pl-4">Name</TableHead><TableHead>Format</TableHead><TableHead className="text-right">Size</TableHead><TableHead className="text-right">Rows</TableHead><TableHead>Status</TableHead><TableHead className="pr-4 text-right">Actions</TableHead></TableRow></TableHeader>
            <TableBody>{ds.data.map((d) => (
              <TableRow key={d.id}>
                <TableCell className="max-w-64 pl-4"><button className="truncate text-left font-medium hover:text-primary disabled:hover:text-foreground" disabled={!d.profile} onClick={() => setView(d)}>{d.name}</button><p className="text-xs text-muted-foreground">{dateTime(d.created_at)}</p></TableCell>
                <TableCell><Badge variant="outline">{d.file_format}</Badge></TableCell>
                <TableCell className="text-right tabular-nums">{size(d.size_bytes)}</TableCell>
                <TableCell className="text-right tabular-nums">{fmt(d.row_count)}</TableCell>
                <TableCell><span className={`rounded-full px-2 py-0.5 text-xs font-medium ${STATUS[d.status] ?? "bg-muted"}`}>{titleCase(d.status)}</span></TableCell>
                <TableCell className="pr-4 text-right">
                  <div className="flex justify-end gap-1">
                    <Button size="sm" variant="outline" disabled={action.isPending || !!running} onClick={() => action.mutate({ kind: "process", id: d.id })}><Play /> Clean & profile</Button>
                    <Button size="sm" variant="outline" disabled={!d.cleaned_path || action.isPending || !!running} onClick={() => action.mutate({ kind: "import", id: d.id })}><Database /> Import foods</Button>
                    <Button size="icon-sm" variant="ghost" aria-label="Delete dataset" onClick={() => action.mutate({ kind: "delete", id: d.id })}><Trash2 /></Button>
                  </div>
                </TableCell>
              </TableRow>))}</TableBody></Table></Card>
        )}
      </div>

      <div className="mt-8">
        <SectionTitle title="Background jobs" description={running ? "Refreshing every 1.5 seconds while a job runs." : "Jobs run in a background thread pool; progress is stored in MySQL."} />
        {jobs.isLoading && <LoadingBlock className="h-40" />}
        {jobs.isError && <ErrorState error={jobs.error} onRetry={() => jobs.refetch()} />}
        {jobs.data?.length === 0 && <EmptyState title="No jobs yet" />}
        <div className="space-y-3">
          {jobs.data?.map((j) => (
            <Card key={j.id} className="gap-0 py-0"><CardContent className="space-y-2 p-4">
              <div className="flex flex-wrap items-center gap-2 text-sm">
                <b>#{j.id} {titleCase(j.job_type)}</b>{j.dataset_name && <span className="text-muted-foreground">on {j.dataset_name}</span>}
                <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${STATUS[j.status]}`}>{j.status}</span>
                <span className="ml-auto text-xs text-muted-foreground">{dateTime(j.created_at)}</span>
              </div>
              {(j.status === "running" || j.status === "queued") && <Progress value={j.progress * 100} />}
              <p className="text-xs text-muted-foreground">{j.status === "failed" ? <span className="text-rose-700" title={j.error ?? undefined}>{j.message}</span> : j.message}</p>
              {j.result && j.status === "succeeded" && (
                <div className="flex flex-wrap gap-1.5">{Object.entries(j.result).filter(([, v]) => typeof v === "number" || typeof v === "string").slice(0, 8).map(([k, v]) => <Badge key={k} variant="secondary" className="font-normal">{titleCase(k)}: {typeof v === "number" ? fmt(v, 2) : String(v).slice(0, 40)}</Badge>)}</div>
              )}
            </CardContent></Card>
          ))}
        </div>
      </div>
      <ProfileDialog ds={view} onClose={() => setView(null)} />
    </>
  )
}
