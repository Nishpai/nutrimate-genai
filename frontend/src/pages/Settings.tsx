import { useEffect, useState } from "react"
import { useQuery, useQueryClient } from "@tanstack/react-query"
import { Loader2, Save } from "lucide-react"
import { toast } from "sonner"
import { PageHeader } from "@/components/app/page-header"
import { BodyFields, DietFields, EMPTY_PROFILE, PreferenceFields, TargetFields } from "@/components/app/profile-fields"
import { ErrorState, LoadingBlock } from "@/components/app/states"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { api } from "@/lib/api"
import type { Profile } from "@/lib/types"

export default function SettingsPage() {
  const q = useQuery({ queryKey: ["profile"], queryFn: () => api<{ profile: Profile }>("/api/profile") })
  const [p, setP] = useState<Profile>(EMPTY_PROFILE)
  const [busy, setBusy] = useState(false)
  const qc = useQueryClient()
  useEffect(() => { if (q.data) setP(q.data.profile) }, [q.data])
  const save = async () => {
    setBusy(true)
    try {
      await api("/api/profile", { method: "PUT", body: p })
      await qc.invalidateQueries()
      toast.success("Settings saved. Recommendations and plans now use them.")
    } catch (e) {
      toast.error((e as Error).message)
    } finally {
      setBusy(false)
    }
  }
  const saveBtn = <Button onClick={save} disabled={busy || !q.data}>{busy ? <Loader2 className="animate-spin" /> : <Save />} Save changes</Button>
  if (q.isError) return <ErrorState error={q.error} onRetry={() => q.refetch()} />
  return (
    <>
      <PageHeader title="Settings" description="Your profile drives every recommendation, plan and assistant answer. Changes are kept in your history." actions={saveBtn} />
      {q.isLoading ? <LoadingBlock /> : (
        <div className="grid gap-6 lg:grid-cols-2">
          <Card><CardHeader><CardTitle>Body and goal</CardTitle><CardDescription>For the calorie estimate.</CardDescription></CardHeader><CardContent><BodyFields value={p} onChange={setP} /></CardContent></Card>
          <Card><CardHeader><CardTitle>Daily targets</CardTitle><CardDescription>What the planner and dashboard aim for.</CardDescription></CardHeader><CardContent><TargetFields value={p} onChange={setP} /></CardContent></Card>
          <Card><CardHeader><CardTitle>Diet, allergies and restrictions</CardTitle><CardDescription>Hard rules, applied before any ranking.</CardDescription></CardHeader><CardContent><DietFields value={p} onChange={setP} /></CardContent></Card>
          <Card><CardHeader><CardTitle>Preferences</CardTitle><CardDescription>Soft signals for personalisation.</CardDescription></CardHeader><CardContent><PreferenceFields value={p} onChange={setP} /></CardContent></Card>
        </div>
      )}
      <div className="mt-6 flex justify-end">{saveBtn}</div>
    </>
  )
}
