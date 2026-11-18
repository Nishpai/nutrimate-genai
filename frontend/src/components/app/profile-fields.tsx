import { useState } from "react"
import { useQuery } from "@tanstack/react-query"
import { Calculator, Check, Loader2, Plus, X } from "lucide-react"
import { toast } from "sonner"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { api } from "@/lib/api"
import { titleCase } from "@/lib/format"
import type { Profile } from "@/lib/types"
import { cn } from "@/lib/utils"

export type Options = { allergens: string[]; cuisines: string[]; diets: string[]; activity: string[]; goals: string[] }
type Props = { value: Profile; onChange: (p: Profile) => void }

export function useProfileOptions() {
  return useQuery({ queryKey: ["profile-options"], queryFn: () => api<Options>("/api/profile/options"), staleTime: Infinity })
}

export const EMPTY_PROFILE: Profile = {
  sex: null, age: null, height_cm: null, weight_kg: null, activity: null, goal: null, diet: "any", allergies: [],
  restrictions: [], cuisines: [], calorie_target: null, protein_target_g: null, carbs_target_g: null, fat_target_g: null,
  fiber_target_g: 30, meals_per_day: 3, max_minutes: null,
}

function Num({ label, value, onChange, suffix, placeholder }: { label: string; value: number | null; onChange: (v: number | null) => void; suffix?: string; placeholder?: string }) {
  return (
    <div className="space-y-1.5">
      <Label>{label}</Label>
      <div className="relative">
        <Input type="number" inputMode="decimal" value={value ?? ""} placeholder={placeholder}
          onChange={(e) => onChange(e.target.value === "" ? null : Number(e.target.value))} className={cn("h-10", suffix && "pr-12")} />
        {suffix && <span className="pointer-events-none absolute top-1/2 right-3 -translate-y-1/2 text-xs text-muted-foreground">{suffix}</span>}
      </div>
    </div>
  )
}

function Choice({ label, value, options, onChange }: { label: string; value: string | null; options: string[]; onChange: (v: string) => void }) {
  return (
    <div className="space-y-1.5">
      <Label>{label}</Label>
      <Select value={value ?? undefined} onValueChange={onChange}>
        <SelectTrigger className="h-10 w-full"><SelectValue placeholder="Choose" /></SelectTrigger>
        <SelectContent>{options.map((o) => <SelectItem key={o} value={o}>{titleCase(o)}</SelectItem>)}</SelectContent>
      </Select>
    </div>
  )
}

function Chips({ options, selected, onToggle, labels }: { options: string[]; selected: string[]; onToggle: (v: string) => void; labels?: Record<string, string> }) {
  return (
    <div className="flex flex-wrap gap-2">
      {options.map((o) => {
        const on = selected.includes(o)
        return (
          <button type="button" key={o} onClick={() => onToggle(o)}
            className={cn("flex items-center gap-1.5 rounded-full border px-3 py-1.5 text-sm transition",
              on ? "border-primary bg-primary text-primary-foreground shadow-sm" : "bg-card hover:border-primary/40 hover:bg-secondary")}>
            {on && <Check className="size-3.5" />}{labels?.[o] ?? titleCase(o)}
          </button>
        )
      })}
    </div>
  )
}

const toggle = (arr: string[], v: string) => (arr.includes(v) ? arr.filter((x) => x !== v) : [...arr, v])
const DIET_HELP: Record<string, string> = {
  any: "No diet rule", eggetarian: "No meat or fish, egg is fine", vegetarian: "No meat, fish or egg", vegan: "No animal products",
}

export function BodyFields({ value: p, onChange }: Props) {
  const o = useProfileOptions().data
  const set = (patch: Partial<Profile>) => onChange({ ...p, ...patch })
  return (
    <div className="grid gap-4 sm:grid-cols-2">
      <Choice label="Sex (for the calorie equation)" value={p.sex} options={["male", "female"]} onChange={(v) => set({ sex: v as Profile["sex"] })} />
      <Num label="Age" value={p.age} onChange={(v) => set({ age: v })} suffix="years" />
      <Num label="Height" value={p.height_cm} onChange={(v) => set({ height_cm: v })} suffix="cm" />
      <Num label="Weight" value={p.weight_kg} onChange={(v) => set({ weight_kg: v })} suffix="kg" />
      <Choice label="Activity level" value={p.activity} options={o?.activity ?? []} onChange={(v) => set({ activity: v })} />
      <Choice label="Goal" value={p.goal} options={o?.goals ?? []} onChange={(v) => set({ goal: v as Profile["goal"] })} />
    </div>
  )
}

export function DietFields({ value: p, onChange }: Props) {
  const o = useProfileOptions().data
  const set = (patch: Partial<Profile>) => onChange({ ...p, ...patch })
  const [term, setTerm] = useState("")
  const add = () => {
    const t = term.trim().toLowerCase()
    if (t.length >= 2 && !p.restrictions.includes(t)) set({ restrictions: [...p.restrictions, t] })
    setTerm("")
  }
  return (
    <div className="space-y-6">
      <div className="space-y-2">
        <Label>Diet</Label>
        <div className="grid gap-2 sm:grid-cols-4">
          {(o?.diets ?? ["any", "eggetarian", "vegetarian", "vegan"]).map((d) => (
            <button type="button" key={d} onClick={() => set({ diet: d as Profile["diet"] })}
              className={cn("rounded-xl border p-3 text-left transition", p.diet === d ? "border-primary bg-secondary ring-2 ring-primary/20" : "hover:border-primary/40")}>
              <p className="text-sm font-medium">{titleCase(d)}</p>
              <p className="text-xs text-muted-foreground">{DIET_HELP[d]}</p>
            </button>
          ))}
        </div>
      </div>
      <div className="space-y-2">
        <Label>Allergies</Label>
        <p className="text-xs text-muted-foreground">Recipes that mention these are removed before ranking. This is text matching on the recipe, not a safety guarantee.</p>
        <Chips options={o?.allergens ?? []} selected={p.allergies} onToggle={(v) => set({ allergies: toggle(p.allergies, v) })} labels={{ tree_nut: "Tree nuts" }} />
      </div>
      <div className="space-y-2">
        <Label>Other foods to avoid</Label>
        <div className="flex gap-2">
          <Input value={term} onChange={(e) => setTerm(e.target.value)} placeholder="e.g. mushroom, coriander"
            onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); add() } }} className="h-10" />
          <Button type="button" variant="outline" className="h-10" onClick={add}><Plus /> Add</Button>
        </div>
        <div className="flex flex-wrap gap-1.5">
          {p.restrictions.map((r) => (
            <Badge key={r} variant="secondary" className="gap-1 py-1 pl-2.5">{r}
              <button type="button" aria-label={`Remove ${r}`} onClick={() => set({ restrictions: p.restrictions.filter((x) => x !== r) })}><X className="size-3" /></button>
            </Badge>
          ))}
        </div>
      </div>
    </div>
  )
}

export function PreferenceFields({ value: p, onChange }: Props) {
  const o = useProfileOptions().data
  const set = (patch: Partial<Profile>) => onChange({ ...p, ...patch })
  return (
    <div className="space-y-6">
      <div className="space-y-2">
        <Label>Favourite cuisines</Label>
        <p className="text-xs text-muted-foreground">Used to personalise recommendations before you have liked anything.</p>
        <Chips options={o?.cuisines ?? []} selected={p.cuisines} onToggle={(v) => set({ cuisines: toggle(p.cuisines, v) })} />
      </div>
      <div className="grid gap-4 sm:grid-cols-2">
        <Choice label="Meals per day" value={String(p.meals_per_day)} options={["3", "4"]} onChange={(v) => set({ meals_per_day: Number(v) })} />
        <Num label="Longest cooking time" value={p.max_minutes} onChange={(v) => set({ max_minutes: v })} suffix="min" placeholder="No limit" />
      </div>
    </div>
  )
}

export function TargetFields({ value: p, onChange }: Props) {
  const set = (patch: Partial<Profile>) => onChange({ ...p, ...patch })
  const [busy, setBusy] = useState(false)
  const [method, setMethod] = useState<string | null>(null)
  const estimate = async () => {
    if (!p.sex || !p.age || !p.height_cm || !p.weight_kg || !p.activity || !p.goal) {
      toast.error("Fill in sex, age, height, weight, activity and goal first")
      return
    }
    setBusy(true)
    try {
      const r = await api<{ daily_kcal: number; daily_protein_g: number; daily_carbs_g: number; daily_fat_g: number; bmr: number; tdee: number }>(
        "/api/profile/estimate", { body: { sex: p.sex, age: p.age, height_cm: p.height_cm, weight_kg: p.weight_kg, activity: p.activity, goal: p.goal } })
      set({ calorie_target: r.daily_kcal, protein_target_g: r.daily_protein_g, carbs_target_g: r.daily_carbs_g, fat_target_g: r.daily_fat_g })
      setMethod(`Mifflin-St Jeor: BMR ${r.bmr} kcal, maintenance ${r.tdee} kcal`)
    } catch (e) {
      toast.error((e as Error).message)
    } finally {
      setBusy(false)
    }
  }
  return (
    <div className="space-y-4">
      <div className="flex flex-col gap-2 rounded-xl border bg-secondary/50 p-4 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <p className="text-sm font-medium">Estimate from your details</p>
          <p className="text-xs text-muted-foreground">{method ?? "A starting point you can edit. Not medical advice."}</p>
        </div>
        <Button type="button" variant="outline" onClick={estimate} disabled={busy}>{busy ? <Loader2 className="animate-spin" /> : <Calculator />} Estimate targets</Button>
      </div>
      <div className="grid gap-4 sm:grid-cols-3">
        <Num label="Calories" value={p.calorie_target} onChange={(v) => set({ calorie_target: v })} suffix="kcal" />
        <Num label="Protein" value={p.protein_target_g} onChange={(v) => set({ protein_target_g: v })} suffix="g" />
        <Num label="Carbs" value={p.carbs_target_g} onChange={(v) => set({ carbs_target_g: v })} suffix="g" />
        <Num label="Fat" value={p.fat_target_g} onChange={(v) => set({ fat_target_g: v })} suffix="g" />
        <Num label="Fibre" value={p.fiber_target_g} onChange={(v) => set({ fiber_target_g: v })} suffix="g" />
      </div>
    </div>
  )
}

export function cleanProfile(p: Profile): Profile {
  return { ...p }
}
