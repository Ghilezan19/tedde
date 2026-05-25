"use client";

import { Loader2, Wifi, WifiOff } from "lucide-react";
import { useCallback, useEffect, useState } from "react";

interface Probe {
  reachable: boolean;
  latency_ms?: number;
  label: string;
  port: number;
}

interface CameraStatusCardProps {
  title: string;
  subtitle: string;
  ip: string;
  probes: Array<{ port: number; label: string }>;
  refreshToken: number;
  onStateChange?: (online: boolean) => void;
}

export function CameraStatusCard({
  title,
  subtitle,
  ip,
  probes,
  refreshToken,
  onStateChange,
}: CameraStatusCardProps) {
  const [results, setResults] = useState<Probe[] | null>(null);
  const [loading, setLoading] = useState(false);

  const probe = useCallback(async () => {
    if (!ip) {
      setResults(null);
      onStateChange?.(false);
      return;
    }
    setLoading(true);
    try {
      const out = await Promise.all(
        probes.map(async ({ port, label }) => {
          try {
            const r = await fetch(
              `/api/net/reach?host=${encodeURIComponent(ip)}&port=${port}&timeout=1.5`,
              { credentials: "include" },
            );
            const d = await r.json();
            return {
              reachable: Boolean(d.reachable),
              latency_ms: d.latency_ms,
              label,
              port,
            };
          } catch {
            return { reachable: false, label, port };
          }
        }),
      );
      setResults(out);
      onStateChange?.(out.some((p) => p.reachable));
    } finally {
      setLoading(false);
    }
  }, [ip, probes, onStateChange]);

  useEffect(() => {
    probe();
    const id = setInterval(probe, 15000);
    return () => clearInterval(id);
  }, [probe, refreshToken]);

  const online = results !== null && results.some((p) => p.reachable);
  const hasResults = results !== null;

  let pill: React.ReactNode;
  if (!ip) {
    pill = (
      <span className="inline-flex items-center gap-1 rounded-full bg-amber-500/10 text-amber-600 px-2 py-0.5 text-xs font-semibold">
        FĂRĂ IP
      </span>
    );
  } else if (loading && !hasResults) {
    pill = (
      <span className="inline-flex items-center gap-1 rounded-full bg-muted text-muted-foreground px-2 py-0.5 text-xs font-semibold">
        <Loader2 className="h-3 w-3 animate-spin" />
        Verifică...
      </span>
    );
  } else if (online) {
    pill = (
      <span className="inline-flex items-center gap-1.5 rounded-full bg-emerald-500/10 text-emerald-500 px-2 py-0.5 text-xs font-semibold">
        <span className="relative flex h-2 w-2">
          <span className="absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75 animate-ping" />
          <span className="relative inline-flex rounded-full h-2 w-2 bg-emerald-500" />
        </span>
        ONLINE
      </span>
    );
  } else {
    pill = (
      <span className="inline-flex items-center gap-1 rounded-full bg-red-500/10 text-red-500 px-2 py-0.5 text-xs font-semibold">
        <WifiOff className="h-3 w-3" />
        OFFLINE
      </span>
    );
  }

  return (
    <div className="rounded-lg border bg-muted/20 p-4 space-y-2">
      <div className="flex items-center justify-between gap-2">
        <div className="min-w-0">
          <div className="text-sm font-semibold truncate">{title}</div>
          <div className="text-xs text-muted-foreground truncate">{subtitle}</div>
        </div>
        {pill}
      </div>
      <div className="font-mono text-xs text-muted-foreground">
        {ip || <span className="italic">fără IP configurat</span>}
      </div>
      {hasResults && (
        <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs">
          {results!.map((p) => (
            <span key={p.port} className="inline-flex items-center gap-1">
              <Wifi
                className={`h-3 w-3 ${p.reachable ? "text-emerald-500" : "text-red-500"}`}
              />
              <span className="text-muted-foreground">{p.label}:</span>
              {p.reachable ? (
                <b className="text-emerald-500">✓ {p.latency_ms}ms</b>
              ) : (
                <b className="text-red-500">✗</b>
              )}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}
