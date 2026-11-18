import type { ReactNode } from "react"
import { AlertTriangle, Inbox, RefreshCw } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { cn } from "@/lib/utils"

export function LoadingGrid({ count = 6, className, itemClass = "h-56" }: { count?: number; className?: string; itemClass?: string }) {
  return (
    <div className={cn("grid gap-4 sm:grid-cols-2 xl:grid-cols-3", className)}>
      {Array.from({ length: count }).map((_, i) => (
        <Skeleton key={i} className={cn("rounded-xl", itemClass)} />
      ))}
    </div>
  )
}

export function LoadingBlock({ className }: { className?: string }) {
  return <Skeleton className={cn("h-64 w-full rounded-xl", className)} />
}

export function ErrorState({ error, onRetry, className }: { error: unknown; onRetry?: () => void; className?: string }) {
  const msg = error instanceof Error ? error.message : "Something went wrong"
  return (
    <div className={cn("flex flex-col items-center justify-center gap-3 rounded-xl border border-destructive/20 bg-destructive/5 p-8 text-center", className)}>
      <div className="flex size-10 items-center justify-center rounded-full bg-destructive/10 text-destructive">
        <AlertTriangle className="size-5" />
      </div>
      <div>
        <p className="font-medium">Could not load this</p>
        <p className="text-sm text-muted-foreground">{msg}</p>
      </div>
      {onRetry && (
        <Button variant="outline" size="sm" onClick={onRetry}>
          <RefreshCw /> Try again
        </Button>
      )}
    </div>
  )
}

export function EmptyState({ icon, title, description, action, className }: {
  icon?: ReactNode; title: string; description?: string; action?: ReactNode; className?: string
}) {
  return (
    <div className={cn("flex flex-col items-center justify-center gap-3 rounded-xl border border-dashed bg-card/50 p-10 text-center", className)}>
      <div className="flex size-11 items-center justify-center rounded-full bg-secondary text-primary">
        {icon ?? <Inbox className="size-5" />}
      </div>
      <div className="max-w-sm">
        <p className="font-medium">{title}</p>
        {description && <p className="mt-1 text-sm text-muted-foreground">{description}</p>}
      </div>
      {action}
    </div>
  )
}
