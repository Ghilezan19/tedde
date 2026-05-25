"use client";

import { useState } from "react";
import { Trash2, Play, AlertTriangle } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "@/components/ui/dialog";
import type { CleanupConfig } from "@/lib/api/superadmin";

interface CleanupSectionProps {
  config: CleanupConfig | null;
  log: string;
}

export function CleanupSection({ config, log }: CleanupSectionProps) {
  const [autoEnabled, setAutoEnabled] = useState(config?.auto_cleanup_enabled ?? false);
  const [cleanupDays, setCleanupDays] = useState(config?.cleanup_days ?? 30);
  const [cleanupLog, setCleanupLog] = useState(log);
  const [runLoading, setRunLoading] = useState(false);
  const [runMessage, setRunMessage] = useState("");

  const [showDangerDialog, setShowDangerDialog] = useState(false);
  const [confirmText, setConfirmText] = useState("");
  const [deleteLoading, setDeleteLoading] = useState(false);
  const [deleteMessage, setDeleteMessage] = useState("");

  const saveCleanupConfig = async (days: number, enabled: boolean) => {
    await fetch("/api/superadmin/cleanup-config", {
      method: "PATCH",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ cleanup_days: days, auto_cleanup_enabled: enabled }),
    });
  };

  const runCleanup = async () => {
    setRunLoading(true);
    setRunMessage("");
    try {
      const res = await fetch("/api/superadmin/cleanup-now", {
        method: "POST",
        credentials: "include",
      });
      const data = (await res.json()) as Record<string, unknown>;
      const logStr =
        typeof data.log === "string"
          ? data.log
          : data.log != null && typeof data.log === "object"
            ? JSON.stringify(data.log, null, 2)
            : "";
      const msg =
        typeof data.message === "string" && data.message
          ? data.message
          : logStr || "Cleanup finalizat.";
      setRunMessage(msg);
      setCleanupLog(logStr || cleanupLog);
    } catch {
      setRunMessage("Eroare la rulare cleanup.");
    } finally {
      setRunLoading(false);
    }
  };

  const handleDeleteAll = async () => {
    if (confirmText !== "DELETE_ALL") return;
    setDeleteLoading(true);
    try {
      const res = await fetch("/api/superadmin/clear-all", {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ confirm: "DELETE_ALL" }),
      });
      const data = await res.json();
      setDeleteMessage(res.ok ? "Toate datele au fost șterse." : (data.detail || "Eroare"));
    } catch {
      setDeleteMessage("Eroare de rețea.");
    } finally {
      setDeleteLoading(false);
      setShowDangerDialog(false);
    }
  };

  return (
    <section className="space-y-4">
      <h2 className="text-xs font-bold uppercase tracking-[0.08em] text-muted-foreground">
        🗑 Cleanup automat
      </h2>

      <div className="rounded-xl border bg-card p-4 space-y-4">
        {/* Auto cleanup toggle */}
        <div className="flex items-center justify-between">
          <label className="text-sm font-medium">Cleanup automat activ</label>
          <button
            role="switch"
            aria-checked={autoEnabled}
            onClick={() => {
              const next = !autoEnabled;
              setAutoEnabled(next);
              saveCleanupConfig(cleanupDays, next);
            }}
            className={`relative inline-flex h-5 w-9 items-center rounded-full transition-colors focus:outline-none focus:ring-2 focus:ring-ring ${autoEnabled ? "bg-primary" : "bg-muted"}`}
          >
            <span
              className={`inline-block h-3.5 w-3.5 transform rounded-full bg-white transition-transform ${autoEnabled ? "translate-x-4" : "translate-x-0.5"}`}
            />
          </button>
        </div>

        {/* Days setting */}
        <div className="flex items-center gap-3">
          <label className="text-sm">Șterge fișiere mai vechi de</label>
          <input
            type="number"
            min={1}
            max={365}
            value={cleanupDays}
            onChange={(e) => {
              const val = Number(e.target.value);
              setCleanupDays(val);
              saveCleanupConfig(val, autoEnabled);
            }}
            className="h-8 w-20 rounded-md border border-input bg-background px-2 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-ring"
          />
          <span className="text-sm text-muted-foreground">zile</span>
        </div>

        {/* Run now */}
        <div className="flex items-center gap-3">
          <Button
            variant="outline"
            size="sm"
            onClick={runCleanup}
            disabled={runLoading}
            className="gap-1.5"
          >
            <Play className="h-3.5 w-3.5" />
            {runLoading ? "Se rulează..." : "Rulează acum"}
          </Button>
          {runMessage && (
            <span className="text-xs text-muted-foreground">{runMessage}</span>
          )}
        </div>

        {/* Log */}
        {cleanupLog && (
          <div className="rounded-md bg-muted/50 border p-3">
            <p className="text-xs text-muted-foreground mb-1 font-medium">Ultimul cleanup:</p>
            <p className="text-xs font-mono text-foreground whitespace-pre-wrap">{cleanupLog}</p>
          </div>
        )}

        {/* Delete feedback from previous run */}
        {deleteMessage && (
          <p className="text-sm text-muted-foreground">{deleteMessage}</p>
        )}

        {/* Danger zone */}
        <div className="rounded-lg border border-red-200 bg-red-50 dark:border-red-900/40 dark:bg-red-950/20 p-4 space-y-3">
          <div className="flex items-center gap-2">
            <AlertTriangle className="h-4 w-4 text-red-600 dark:text-red-400" />
            <p className="text-sm font-semibold text-red-700 dark:text-red-400">Zonă periculoasă</p>
          </div>
          <p className="text-xs text-red-600 dark:text-red-400">
            Ștergerea tuturor datelor este ireversibilă. Toate evenimentele, înregistrările, snapshot-urile, link-urile clienților și feedback-ul vor fi șterse permanent.
          </p>
          <Button
            variant="destructive"
            size="sm"
            onClick={() => {
              setConfirmText("");
              setShowDangerDialog(true);
            }}
            className="gap-1.5"
          >
            <Trash2 className="h-3.5 w-3.5" />
            Șterge TOT
          </Button>
        </div>
      </div>

      {/* Danger Dialog */}
      <Dialog open={showDangerDialog} onOpenChange={setShowDangerDialog}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2 text-red-600">
              <AlertTriangle className="h-5 w-5" />
              Confirmare ștergere totală
            </DialogTitle>
          </DialogHeader>
          <div className="space-y-4">
            <p className="text-sm text-muted-foreground">
              Această acțiune va șterge <strong>toate</strong> evenimentele, înregistrările,
              snapshot-urile, link-urile clienților și feedback-ul. Nu poate fi anulată.
            </p>
            <div className="space-y-1.5">
              <label className="text-sm font-medium">
                Scrie <code className="font-mono text-red-600">DELETE_ALL</code> pentru confirmare:
              </label>
              <input
                type="text"
                value={confirmText}
                onChange={(e) => setConfirmText(e.target.value)}
                placeholder="DELETE_ALL"
                className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-destructive"
              />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setShowDangerDialog(false)}>
              Anulează
            </Button>
            <Button
              variant="destructive"
              disabled={confirmText !== "DELETE_ALL" || deleteLoading}
              onClick={handleDeleteAll}
            >
              {deleteLoading ? "Se șterge..." : "Da, șterge TOT"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </section>
  );
}
