import type { ReactNode } from "react"
import { Card, CardContent } from "@/components/ui/card"
import { cn } from "@/lib/utils"

export function Ring({ value, size = 64, stroke = 7, color = "var(--primary)", children }: {
  value: number | null; size?: number; stroke?: number; color?: string; children?: ReactNode
}) {
  const r = (size - stroke) / 2
  const c = 2 * Math.PI * r
  const pct = Math.max(0, Math.min(100, value ?? 0))
  return (
    <div className="relative shrink-0" style={{ width: size, height: size }}>
      <svg width={size} height={size} className="-rotate-90">
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="var(--muted)" strokeWidth={stroke} />
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke={color} strokeWidth={stroke} strokeLinecap="round"
          strokeDasharray={c} strokeDashoffset={c - (pct / 100) * c} style={{ transition: "stroke-dashoffset .6s ease" }} />
      </svg>
      <div className="absolute inset-0 flex items-center justify-center text-xs font-semibold">{children}</div>
    </div>
  )
}

export function StatCard({ icon, label, value, sub, ring, color, className }: {
  icon?: ReactNode; label: string; value: ReactNode; sub?: ReactNode; ring?: number | null; color?: string; className?: string
}) {
  return (
    <Card className={cn("gap-0 py-0", className)}>
      <CardContent className="flex items-center gap-4 p-4">
        {ring !== undefined ? (
          <Ring value={ring} color={color}>{ring === null ? "n/a" : `${Math.round(ring)}%`}</Ring>
        ) : (
          icon && <div className="flex size-11 items-center justify-center rounded-xl bg-secondary text-primary">{icon}</div>
        )}
        <div className="min-w-0">
          <p className="text-xs font-medium text-muted-foreground">{label}</p>
          <p className="text-xl font-semibold tracking-tight">{value}</p>
          {sub && <p className="truncate text-xs text-muted-foreground">{sub}</p>}
        </div>
      </CardContent>
    </Card>
  )
}

export function MacroBar({ label, value, target, unit, color }: {
  label: string; value: number | null; target: number | null; unit: string; color: string
}) {
  const pct = target && value !== null ? Math.min(100, (100 * value) / target) : 0
  const over = !!(target && value !== null && value > target * 1.1)
  return (
    <div>
      <div className="mb-1 flex items-baseline justify-between text-sm">
        <span className="font-medium">{label}</span>
        <span className="text-muted-foreground tabular-nums">
          <span className={cn("font-medium text-foreground", over && "text-amber-600")}>{value === null ? "n/a" : Math.round(value)}</span>
          {target ? ` / ${Math.round(target)} ${unit}` : ` ${unit}`}
        </span>
      </div>
      <div className="h-2 overflow-hidden rounded-full bg-muted">
        <div className="h-full rounded-full transition-all" style={{ width: `${pct}%`, background: color }} />
      </div>
    </div>
  )
}
