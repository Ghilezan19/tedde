import { StatusPill } from "@/components/StatusPill";
import type { HealthCheck } from "@/lib/api/superadmin";

interface HealthSectionProps {
  health: HealthCheck | null;
}

export function HealthSection({ health }: HealthSectionProps) {
  const checks = health?.checks ? Object.entries(health.checks) : [];

  return (
    <section className="space-y-4">
      <h2 className="text-xs font-bold uppercase tracking-[0.08em] text-muted-foreground">
        📡 Status sistem
      </h2>

      <div className="rounded-xl border bg-card p-4">
        {checks.length === 0 ? (
          <p className="text-sm text-muted-foreground">Nu s-au putut încărca datele de sănătate.</p>
        ) : (
          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-3">
            {checks.map(([key, check]) => (
              <div key={key} className="flex items-center gap-2">
                <StatusPill
                  variant={check.ok ? "success" : "error"}
                  label={check.label || key}
                />
              </div>
            ))}
          </div>
        )}

        {/* System metrics */}
        {health && (
          <div className="mt-4 pt-4 border-t grid grid-cols-2 sm:grid-cols-3 gap-3 text-sm">
            {health.uptime_seconds !== undefined && (
              <div>
                <p className="text-xs text-muted-foreground">Uptime</p>
                <p className="font-mono font-medium">
                  {Math.floor(health.uptime_seconds / 3600)}h {Math.floor((health.uptime_seconds % 3600) / 60)}m
                </p>
              </div>
            )}
            {health.disk_percent !== undefined && (
              <div>
                <p className="text-xs text-muted-foreground">Disc folosit</p>
                <p className="font-mono font-medium">{health.disk_percent.toFixed(1)}%</p>
              </div>
            )}
            {health.mem_percent !== undefined && (
              <div>
                <p className="text-xs text-muted-foreground">RAM folosit</p>
                <p className="font-mono font-medium">{health.mem_percent.toFixed(1)}%</p>
              </div>
            )}
          </div>
        )}
      </div>
    </section>
  );
}
