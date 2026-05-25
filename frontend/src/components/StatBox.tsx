import { cn } from "@/lib/utils";

interface StatBoxProps {
  label: string;
  value: string | number;
  subtitle?: string;
  className?: string;
  icon?: React.ReactNode;
}

export function StatBox({ label, value, subtitle, className, icon }: StatBoxProps) {
  return (
    <div
      className={cn(
        "rounded-xl border bg-card p-5 flex flex-col gap-2 shadow-sm",
        className
      )}
    >
      <div className="flex items-center justify-between">
        <p className="text-xs font-semibold uppercase tracking-[0.08em] text-muted-foreground">
          {label}
        </p>
        {icon && <span className="text-muted-foreground">{icon}</span>}
      </div>
      <p className="text-3xl font-bold tabular-nums text-foreground leading-none">
        {value}
      </p>
      {subtitle && (
        <p className="text-xs text-muted-foreground">{subtitle}</p>
      )}
    </div>
  );
}
