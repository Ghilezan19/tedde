"use client";

import { Button } from "@/components/ui/button";
import { saveConfig } from "@/lib/api/config";
import { AlertTriangle, CheckCircle, RefreshCw, Save, XCircle } from "lucide-react";
import { useState } from "react";

interface SaveBarProps {
  getValues: () => Record<string, string>;
}

type RestartPhase = "idle" | "confirming" | "restarting" | "waiting" | "done" | "failed";

async function waitForBackend(timeoutMs = 30000): Promise<boolean> {
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    await new Promise((r) => setTimeout(r, 1000));
    try {
      const r = await fetch("/api/config", {
        credentials: "include",
        cache: "no-store",
      });
      if (r.ok) return true;
    } catch {
      // connection refused while restarting — keep polling
    }
  }
  return false;
}

export function SaveBar({ getValues }: SaveBarProps) {
  const [saving, setSaving] = useState(false);
  const [result, setResult] = useState<"success" | "error" | null>(null);
  const [message, setMessage] = useState("");
  const [restartPhase, setRestartPhase] = useState<RestartPhase>("idle");

  const handleSave = async () => {
    setSaving(true);
    setResult(null);
    try {
      const values = getValues();
      const res = await saveConfig(values);
      if (res.ok) {
        setResult("success");
        setMessage(res.message || "Configurație salvată.");
      } else {
        setResult("error");
        setMessage(res.message || "Eroare la salvare.");
      }
    } catch {
      setResult("error");
      setMessage("Eroare de rețea.");
    } finally {
      setSaving(false);
    }
  };

  const handleRestart = async () => {
    if (restartPhase === "idle") {
      setRestartPhase("confirming");
      return;
    }
    if (restartPhase !== "confirming") return;

    setRestartPhase("restarting");
    try {
      const r = await fetch("/api/admin/restart", {
        method: "POST",
        credentials: "include",
      });
      if (!r.ok) {
        setRestartPhase("failed");
        return;
      }
    } catch {
      // expected — process is exiting
    }

    setRestartPhase("waiting");
    const alive = await waitForBackend(30000);
    setRestartPhase(alive ? "done" : "failed");

    if (alive) {
      // Auto-dismiss after a moment
      setTimeout(() => setRestartPhase("idle"), 4000);
    }
  };

  const restarting =
    restartPhase === "restarting" || restartPhase === "waiting";

  return (
    <div className="sticky bottom-0 border-t bg-card/95 backdrop-blur-sm px-4 py-3 flex flex-wrap items-center gap-3">
      <Button onClick={handleSave} disabled={saving || restarting} className="gap-1.5">
        <Save className="h-4 w-4" />
        {saving ? "Se salvează..." : "Salvează configurația"}
      </Button>

      {result === "success" && restartPhase === "idle" && (
        <span className="flex items-center gap-1.5 text-sm text-emerald-600">
          <CheckCircle className="h-4 w-4" />
          {message}
        </span>
      )}
      {result === "error" && (
        <span className="flex items-center gap-1.5 text-sm text-red-600">
          <XCircle className="h-4 w-4" />
          {message}
        </span>
      )}

      {/* Restart button: shown always, prominent after a successful save */}
      {restartPhase === "idle" && (
        <Button
          onClick={handleRestart}
          variant={result === "success" ? "default" : "outline"}
          size="sm"
          disabled={saving}
          className="gap-1.5"
          title="Repornește backend-ul pentru a aplica modificări (IP camere, porturi etc.)"
        >
          <RefreshCw className="h-3.5 w-3.5" />
          Repornește serverul
        </Button>
      )}

      {restartPhase === "confirming" && (
        <div className="flex items-center gap-2">
          <span className="inline-flex items-center gap-1.5 text-sm text-amber-500">
            <AlertTriangle className="h-4 w-4" />
            Sigur? Backend va fi oprit ~5 sec.
          </span>
          <Button onClick={handleRestart} size="sm" variant="destructive" className="gap-1.5">
            Da, repornește
          </Button>
          <Button onClick={() => setRestartPhase("idle")} size="sm" variant="ghost">
            Anulează
          </Button>
        </div>
      )}

      {restarting && (
        <span className="inline-flex items-center gap-1.5 text-sm text-amber-500">
          <RefreshCw className="h-4 w-4 animate-spin" />
          {restartPhase === "restarting" ? "Trimit comanda..." : "Aștept serverul..."}
        </span>
      )}

      {restartPhase === "done" && (
        <span className="inline-flex items-center gap-1.5 text-sm text-emerald-600">
          <CheckCircle className="h-4 w-4" />
          Server repornit. Modificările sunt active.
        </span>
      )}

      {restartPhase === "failed" && (
        <span className="inline-flex items-center gap-1.5 text-sm text-red-600">
          <XCircle className="h-4 w-4" />
          Serverul nu a revenit. Verifică systemd.
        </span>
      )}

      <p className="ml-auto text-xs text-muted-foreground hidden sm:block">
        Unele setări necesită repornirea serverului.
      </p>
    </div>
  );
}
