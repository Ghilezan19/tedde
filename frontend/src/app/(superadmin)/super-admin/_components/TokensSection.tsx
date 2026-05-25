"use client";

import { useState } from "react";
import { Coins, TrendingUp, History, CheckCircle, XCircle } from "lucide-react";
import { StatBox } from "@/components/StatBox";
import { Button } from "@/components/ui/button";
import type { TokensInfo, TokenHistoryEntry } from "@/lib/api/superadmin";

interface TokensSectionProps {
  tokens: TokensInfo | null;
  history: TokenHistoryEntry[];
}

function kindLabel(kind: string) {
  if (kind === "consume") return "Consumat";
  if (kind === "topup") return "Adăugat";
  return "Ajustat";
}

function kindColor(kind: string) {
  if (kind === "consume") return "text-red-600 dark:text-red-400";
  if (kind === "topup") return "text-emerald-600 dark:text-emerald-400";
  return "text-amber-600 dark:text-amber-400";
}

function formatDate(iso: string) {
  try {
    return new Date(iso).toLocaleString("ro-RO", {
      day: "2-digit",
      month: "2-digit",
      year: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return iso;
  }
}

export function TokensSection({ tokens, history }: TokensSectionProps) {
  const [newTokens, setNewTokens] = useState("");
  const [saving, setSaving] = useState(false);
  const [saveResult, setSaveResult] = useState<"success" | "error" | null>(null);
  const [saveMessage, setSaveMessage] = useState("");

  const handleSetTokens = async () => {
    const val = parseInt(newTokens, 10);
    if (isNaN(val) || val < 0) return;
    setSaving(true);
    setSaveResult(null);

    try {
      const res = await fetch("/api/superadmin/tokens", {
        method: "PATCH",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ tokens_remaining: val }),
      });
      if (res.ok) {
        setSaveResult("success");
        setSaveMessage(`Tokeni setați la ${val}`);
      } else {
        const err = await res.json();
        setSaveResult("error");
        setSaveMessage(err.detail || "Eroare");
      }
    } catch {
      setSaveResult("error");
      setSaveMessage("Eroare de rețea");
    } finally {
      setSaving(false);
    }
  };

  return (
    <section className="space-y-4">
      <h2 className="text-xs font-bold uppercase tracking-[0.08em] text-muted-foreground">
        🪙 Tokeni — Subscripție vehicule
      </h2>

      <div className="grid grid-cols-2 sm:grid-cols-3 gap-4">
        <StatBox label="Tokeni rămași" value={tokens?.tokens_remaining ?? "—"} icon={<Coins className="h-4 w-4" />} />
        <StatBox label="Procesate luna aceasta" value={tokens?.monthly_processed ?? "—"} icon={<TrendingUp className="h-4 w-4" />} />
        <StatBox label="Total procesate" value={tokens?.total_processed ?? "—"} icon={<History className="h-4 w-4" />} />
      </div>

      {/* Set tokens */}
      <div className="rounded-xl border bg-card p-4 space-y-3">
        <p className="text-sm font-medium">Setează număr tokeni</p>
        <div className="flex items-center gap-2">
          <input
            type="number"
            min={0}
            value={newTokens}
            onChange={(e) => setNewTokens(e.target.value)}
            placeholder="ex. 500"
            className="h-9 w-32 rounded-md border border-input bg-background px-3 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-ring"
          />
          <Button
            size="sm"
            onClick={handleSetTokens}
            disabled={saving || !newTokens}
          >
            {saving ? "Se salvează..." : "Setează tokeni"}
          </Button>
          {saveResult === "success" && (
            <span className="flex items-center gap-1 text-xs text-emerald-600">
              <CheckCircle className="h-3.5 w-3.5" />{saveMessage}
            </span>
          )}
          {saveResult === "error" && (
            <span className="flex items-center gap-1 text-xs text-red-600">
              <XCircle className="h-3.5 w-3.5" />{saveMessage}
            </span>
          )}
        </div>
      </div>

      {/* Token history */}
      {history.length > 0 && (
        <div className="rounded-xl border bg-card overflow-hidden">
          <div className="px-4 py-3 border-b">
            <p className="text-sm font-medium">Istoric tokeni</p>
          </div>
          <div className="divide-y max-h-80 overflow-y-auto">
            {history.map((entry) => (
              <div key={entry.id} className="flex items-center gap-3 px-4 py-2.5 text-sm">
                <span className={`font-medium shrink-0 ${kindColor(entry.kind)}`}>
                  {entry.delta > 0 ? "+" : ""}{entry.delta}
                </span>
                <span className="text-xs text-muted-foreground">{kindLabel(entry.kind)}</span>
                <span className="text-xs text-muted-foreground font-mono">→ {entry.balance_after}</span>
                {entry.license_plate && (
                  <span className="font-mono text-xs bg-muted px-1.5 py-0.5 rounded">{entry.license_plate}</span>
                )}
                {entry.note && (
                  <span className="text-xs text-muted-foreground italic truncate">{entry.note}</span>
                )}
                <span className="ml-auto text-xs text-muted-foreground shrink-0">
                  {formatDate(entry.created_at)}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
    </section>
  );
}
