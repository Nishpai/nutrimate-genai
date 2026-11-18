import { useEffect, useRef, useState, type FormEvent } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { ArrowUp, Bot, ChevronDown, Database, Loader2, ShieldAlert, ShieldCheck, Sparkles, Trash2, User } from "lucide-react"
import { toast } from "sonner"
import { RecipeDialog } from "@/components/app/recipe"
import { ErrorState, LoadingBlock } from "@/components/app/states"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"
import { Textarea } from "@/components/ui/textarea"
import { api } from "@/lib/api"
import { fmt, titleCase } from "@/lib/format"
import { cn } from "@/lib/utils"

type CardItem = { type: string; id: string; name: string; portion: string; calories_kcal: number | null; protein_g: number | null; carbs_g: number | null; fat_g: number | null; fiber_g: number | null }
type Meta = { mode: string; model: string | null; intent: string; validation: { ok: boolean; reason?: string; unsupported?: string[] }; steps: { node: string; ms: number; detail: string }[]; cards: CardItem[] }
type Msg = { id: number; role: "user" | "assistant"; content: string; meta: Meta | null; created_at?: string }

const SUGGESTIONS = [
  "How many calories are in 150 g of cooked rice and a bowl of dal?",
  "Suggest a high protein vegetarian dinner under 600 kcal",
  "Compare paneer tikka and chicken tikka",
  "How much protein do I have left today?",
  "Something quick with spinach",
]

function Steps({ meta }: { meta: Meta }) {
  const [open, setOpen] = useState(false)
  const total = meta.steps.reduce((a, s) => a + s.ms, 0)
  return (
    <div className="mt-3 text-xs">
      <button onClick={() => setOpen(!open)} className="flex items-center gap-1 text-muted-foreground hover:text-foreground">
        <ChevronDown className={cn("size-3.5 transition", open && "rotate-180")} /> How this was answered ({fmt(total)} ms)
      </button>
      {open && (
        <ol className="mt-2 space-y-1 border-l-2 border-emerald-200 pl-3">
          {meta.steps.map((s) => (
            <li key={s.node} className="flex justify-between gap-4"><span><b className="font-medium">{titleCase(s.node)}</b> <span className="text-muted-foreground">{s.detail}</span></span><span className="text-muted-foreground tabular-nums">{fmt(s.ms, 1)} ms</span></li>
          ))}
        </ol>
      )}
    </div>
  )
}

function Bubble({ m, onOpen }: { m: Msg; onOpen: (id: number) => void }) {
  if (m.role === "user") {
    return (
      <div className="flex justify-end gap-3">
        <div className="max-w-[80%] rounded-2xl rounded-tr-sm bg-primary px-4 py-2.5 text-sm text-primary-foreground shadow-sm">{m.content}</div>
        <div className="flex size-8 shrink-0 items-center justify-center rounded-full bg-muted"><User className="size-4" /></div>
      </div>
    )
  }
  const meta = m.meta
  return (
    <div className="flex gap-3">
      <div className="flex size-8 shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-emerald-500 to-teal-600 text-white"><Bot className="size-4" /></div>
      <div className="max-w-[85%] min-w-0 flex-1">
        <div className="rounded-2xl rounded-tl-sm border bg-card px-4 py-3 text-sm leading-relaxed shadow-sm">
          <p className="whitespace-pre-wrap">{m.content}</p>
          {meta && meta.cards.length > 0 && (
            <div className="mt-3 grid gap-2 sm:grid-cols-2">
              {meta.cards.slice(0, 6).map((c) => (
                <button key={c.type + c.id} disabled={c.type !== "recipe"} onClick={() => onOpen(Number(c.id))}
                  className={cn("rounded-lg border bg-muted/30 p-2.5 text-left text-xs", c.type === "recipe" && "hover:border-primary/40 hover:bg-secondary")}>
                  <div className="flex items-center gap-1.5"><Badge variant="secondary" className="h-4 px-1.5 text-[10px]">{c.type}</Badge><span className="truncate font-medium">{c.name}</span></div>
                  <p className="mt-1 text-muted-foreground">{c.portion}: {fmt(c.calories_kcal)} kcal, {fmt(c.protein_g, 1)} g protein, {fmt(c.carbs_g, 1)} g carbs, {fmt(c.fat_g, 1)} g fat</p>
                </button>
              ))}
            </div>
          )}
        </div>
        {meta && (
          <div className="mt-1.5 flex flex-wrap items-center gap-1.5 text-xs">
            <Badge variant="outline" className={cn(meta.mode === "gemini" ? "border-emerald-300 text-emerald-700" : "border-amber-300 text-amber-700")}>
              <Sparkles className="size-3" />{meta.mode === "gemini" ? `Written by ${meta.model}` : "Template answer"}
            </Badge>
            <Badge variant="outline"><Database className="size-3" />Values from MySQL</Badge>
            {meta.validation.ok ? (
              meta.mode === "gemini" && <Badge variant="outline" className="text-emerald-700"><ShieldCheck className="size-3" />Numbers checked</Badge>
            ) : (
              <Badge variant="outline" className="text-amber-700" title={meta.validation.unsupported?.join(", ")}><ShieldAlert className="size-3" />AI reply rejected, template used</Badge>
            )}
            <span className="text-muted-foreground">intent: {meta.intent}</span>
          </div>
        )}
        {meta && meta.validation.reason && meta.mode !== "gemini" && <p className="mt-1 text-[11px] text-muted-foreground">{meta.validation.reason}</p>}
        {meta && <Steps meta={meta} />}
      </div>
    </div>
  )
}

export default function Assistant() {
  const qc = useQueryClient()
  const [text, setText] = useState("")
  const [open, setOpen] = useState<number | null>(null)
  const end = useRef<HTMLDivElement>(null)
  const status = useQuery({ queryKey: ["assistant-status"], queryFn: () => api<{ gemini: boolean; retriever: boolean; engine: boolean; documents: number }>("/api/assistant/status"), refetchInterval: (q) => (q.state.data?.retriever ? false : 3000) })
  const history = useQuery({ queryKey: ["chats"], queryFn: () => api<Msg[]>("/api/history/chats?limit=60") })
  const ask = useMutation({
    mutationFn: (message: string) => api<{ id: number; answer: string } & Meta>("/api/assistant/ask", { body: { message } }),
    onMutate: (message) => {
      qc.setQueryData<Msg[]>(["chats"], (old) => [...(old ?? []), { id: -Date.now(), role: "user", content: message, meta: null }])
    },
    onSuccess: (r) => {
      qc.setQueryData<Msg[]>(["chats"], (old) => [...(old ?? []), { id: r.id, role: "assistant", content: r.answer, meta: { mode: r.mode, model: r.model, intent: r.intent, validation: r.validation, steps: r.steps, cards: r.cards } }])
    },
    onError: (e) => { toast.error((e as Error).message); qc.invalidateQueries({ queryKey: ["chats"] }) },
  })
  const clear = useMutation({
    mutationFn: () => api("/api/assistant/history", { method: "DELETE" }),
    onSuccess: () => { qc.setQueryData(["chats"], []); toast.success("Conversation cleared") },
  })
  useEffect(() => { end.current?.scrollIntoView({ behavior: "smooth" }) }, [history.data, ask.isPending])
  const send = (e?: FormEvent, msg?: string) => {
    e?.preventDefault()
    const m = (msg ?? text).trim()
    if (m.length < 2 || ask.isPending) return
    setText("")
    ask.mutate(m)
  }
  const s = status.data
  const msgs = history.data ?? []
  return (
    <div className="flex h-[calc(100svh-7rem)] flex-col">
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">AI nutrition assistant</h1>
          <p className="text-sm text-muted-foreground">LangGraph flow: parse, FAISS retrieval, MySQL lookup, Python maths, then Gemini writes the reply. Gemini never supplies numbers.</p>
        </div>
        <div className="flex items-center gap-2">
          <Badge variant="outline" className={s?.gemini ? "border-emerald-300 text-emerald-700" : "text-amber-700"}>{s ? (s.gemini ? "Gemini connected" : "Template mode (no key)") : "Checking..."}</Badge>
          {s && <Badge variant="outline">{s.retriever ? `${s.documents.toLocaleString()} indexed docs` : "Index loading"}</Badge>}
          <Button variant="ghost" size="sm" onClick={() => clear.mutate()} disabled={!msgs.length || clear.isPending}><Trash2 /> Clear</Button>
        </div>
      </div>
      <Card className="flex min-h-0 flex-1 flex-col gap-0 overflow-hidden py-0">
        <div className="min-h-0 flex-1 space-y-6 overflow-y-auto p-4 sm:p-6">
          {history.isLoading && <LoadingBlock className="h-40" />}
          {history.isError && <ErrorState error={history.error} onRetry={() => history.refetch()} />}
          {history.data && msgs.length === 0 && (
            <div className="mx-auto flex max-w-xl flex-col items-center py-10 text-center">
              <div className="mb-4 flex size-14 items-center justify-center rounded-2xl bg-gradient-to-br from-emerald-500 to-teal-600 text-white shadow-lg shadow-emerald-600/20"><Bot className="size-7" /></div>
              <h2 className="text-lg font-semibold">Ask about food, portions or your day</h2>
              <p className="mt-1 text-sm text-muted-foreground">Nutrition values come from the database and your profile rules are always applied.</p>
              <div className="mt-6 grid w-full gap-2 sm:grid-cols-2">
                {SUGGESTIONS.map((x) => <button key={x} onClick={() => send(undefined, x)} className="rounded-xl border bg-card p-3 text-left text-sm transition hover:border-primary/40 hover:bg-secondary">{x}</button>)}
              </div>
            </div>
          )}
          {msgs.map((m) => <Bubble key={m.id} m={m} onOpen={setOpen} />)}
          {ask.isPending && (
            <div className="flex gap-3">
              <div className="flex size-8 items-center justify-center rounded-full bg-gradient-to-br from-emerald-500 to-teal-600 text-white"><Bot className="size-4" /></div>
              <div className="flex items-center gap-2 rounded-2xl border bg-card px-4 py-3 text-sm text-muted-foreground"><Loader2 className="size-4 animate-spin" /> Looking up the database...</div>
            </div>
          )}
          <div ref={end} />
        </div>
        <form onSubmit={send} className="border-t bg-muted/20 p-3">
          <div className="flex items-end gap-2 rounded-xl border bg-background p-2 focus-within:ring-3 focus-within:ring-ring/30">
            <Textarea value={text} onChange={(e) => setText(e.target.value)} rows={1} maxLength={600}
              placeholder="e.g. How much protein is in 200 g of chickpeas?" className="max-h-32 min-h-9 resize-none border-0 shadow-none focus-visible:ring-0"
              onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send() } }} />
            <Button type="submit" size="icon" disabled={ask.isPending || text.trim().length < 2} aria-label="Send"><ArrowUp /></Button>
          </div>
          <p className="mt-1.5 px-1 text-[11px] text-muted-foreground">General information, not medical advice. Allergy checks are text based.</p>
        </form>
      </Card>
      <RecipeDialog id={open} onClose={() => setOpen(null)} />
    </div>
  )
}
