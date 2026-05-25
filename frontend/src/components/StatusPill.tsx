import { cn } from "@/lib/utils";

type Variant = "success" | "warning" | "error" | "info" | "idle" | "ok";

interface StatusPillProps {
  variant: Variant;
  label: string;
  className?: string;
}

const variantStyles: Record<Variant, string> = {
  success:
    "bg-emerald-500/10 text-emerald-700 border-emerald-500/20 dark:text-emerald-400",
  ok: "bg-emerald-500/10 text-emerald-700 border-emerald-500/20 dark:text-emerald-400",
  warning:
    "bg-amber-500/10 text-amber-700 border-amber-500/20 dark:text-amber-400",
  error:
    "bg-red-500/10 text-red-700 border-red-500/20 dark:text-red-400",
  info:
    "bg-blue-500/10 text-blue-700 border-blue-500/20 dark:text-blue-400",
  idle:
    "bg-muted text-muted-foreground border-border",
};

const dotStyles: Record<Variant, string> = {
  success: "bg-emerald-500",
  ok: "bg-emerald-500",
  warning: "bg-amber-500",
  error: "bg-red-500",
  info: "bg-blue-500",
  idle: "bg-muted-foreground",
};

export function StatusPill({ variant, label, className }: StatusPillProps) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-medium border",
        variantStyles[variant],
        className
      )}
    >
      <span className={cn("h-1.5 w-1.5 rounded-full shrink-0", dotStyles[variant])} />
      {label}
    </span>
  );
}
