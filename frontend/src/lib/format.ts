export const fmt = (v: number | null | undefined, digits = 0, unit = "") =>
  v === null || v === undefined || Number.isNaN(v) ? "n/a" : `${v.toLocaleString(undefined, { maximumFractionDigits: digits, minimumFractionDigits: 0 })}${unit}`

export const titleCase = (s: string) => s.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase())

export const shortDate = (iso: string) =>
  new Date(iso + (iso.length === 10 ? "T00:00:00" : "")).toLocaleDateString(undefined, { month: "short", day: "numeric" })

export const dayName = (iso: string) =>
  new Date(iso + "T00:00:00").toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric" })

export const dateTime = (iso: string) =>
  new Date(iso).toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" })

export const todayIso = () => {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`
}

export const MACRO_COLORS = {
  calories_kcal: "var(--chart-1)",
  protein_g: "var(--chart-3)",
  carbs_g: "var(--chart-2)",
  fat_g: "var(--chart-4)",
  fiber_g: "var(--chart-5)",
} as const

export const MACRO_LABEL: Record<string, string> = {
  calories_kcal: "Calories",
  protein_g: "Protein",
  carbs_g: "Carbs",
  fat_g: "Fat",
  fiber_g: "Fibre",
}
