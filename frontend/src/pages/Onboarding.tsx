import { useState } from "react"
import { useNavigate } from "react-router-dom"
import { ArrowLeft, ArrowRight, Check, Loader2 } from "lucide-react"
import { toast } from "sonner"
import { BodyFields, DietFields, EMPTY_PROFILE, PreferenceFields, TargetFields } from "@/components/app/profile-fields"
import { Logo } from "@/components/app/shell"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { api } from "@/lib/api"
import { useAuth } from "@/lib/auth"
import type { Profile } from "@/lib/types"
import { cn } from "@/lib/utils"

const STEPS = [
  { title: "About you", desc: "Used only to estimate your daily calorie and protein needs." },
  { title: "Diet and allergies", desc: "These are hard rules. A recipe that breaks one is never shown." },
  { title: "Preferences", desc: "Cuisines you enjoy and how you like to eat." },
  { title: "Daily targets", desc: "Estimate them from your details, or type your own numbers." },
]

export default function Onboarding() {
  const [step, setStep] = useState(0)
  const [p, setP] = useState<Profile>(EMPTY_PROFILE)
  const [busy, setBusy] = useState(false)
  const { refresh, user } = useAuth()
  const nav = useNavigate()
  const finish = async () => {
    setBusy(true)
    try {
      await api("/api/profile/onboarding", { body: p })
      await refresh()
      toast.success("Profile saved. Your recommendations are ready.")
      nav("/dashboard", { replace: true })
    } catch (e) {
      toast.error((e as Error).message)
    } finally {
      setBusy(false)
    }
  }
  const Fields = [BodyFields, DietFields, PreferenceFields, TargetFields][step]
  return (
    <div className="min-h-svh bg-gradient-to-b from-emerald-50/70 to-background">
      <div className="mx-auto max-w-3xl px-4 py-8">
        <div className="mb-8 flex items-center justify-between"><Logo /><span className="text-sm text-muted-foreground">Hi {user?.full_name.split(" ")[0]}</span></div>
        <div className="mb-6 grid grid-cols-4 gap-2">
          {STEPS.map((s, i) => (
            <div key={s.title} className="space-y-2">
              <div className={cn("h-1.5 rounded-full transition", i <= step ? "bg-primary" : "bg-muted")} />
              <p className={cn("hidden text-xs sm:block", i === step ? "font-medium text-foreground" : "text-muted-foreground")}>{i + 1}. {s.title}</p>
            </div>
          ))}
        </div>
        <Card>
          <CardHeader>
            <CardTitle className="text-xl">{STEPS[step].title}</CardTitle>
            <CardDescription>{STEPS[step].desc}</CardDescription>
          </CardHeader>
          <CardContent><Fields value={p} onChange={setP} /></CardContent>
        </Card>
        <div className="mt-6 flex justify-between">
          <Button variant="ghost" disabled={step === 0} onClick={() => setStep(step - 1)}><ArrowLeft /> Back</Button>
          {step < STEPS.length - 1 ? (
            <Button onClick={() => setStep(step + 1)}>Continue <ArrowRight /></Button>
          ) : (
            <Button onClick={finish} disabled={busy}>{busy ? <Loader2 className="animate-spin" /> : <Check />} Finish setup</Button>
          )}
        </div>
      </div>
    </div>
  )
}
