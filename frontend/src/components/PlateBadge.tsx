import { cn } from "@/lib/utils";

interface PlateBadgeProps {
  plate: string;
  className?: string;
  size?: "sm" | "md" | "lg";
}

export function PlateBadge({ plate, className, size = "md" }: PlateBadgeProps) {
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-md bg-muted px-2.5 py-1 font-mono font-semibold tracking-wider tabular-nums border border-border",
        size === "sm" && "text-xs px-2 py-0.5",
        size === "md" && "text-sm",
        size === "lg" && "text-lg px-3 py-1.5",
        className
      )}
    >
      {plate}
    </span>
  );
}
