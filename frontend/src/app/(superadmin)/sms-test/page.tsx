"use client";

import { useState, useEffect, useRef } from "react";
import { Send, RefreshCw, CheckCircle2, XCircle, Zap, Phone } from "lucide-react";
import { Button } from "@/components/ui/button";

interface GatewayHealth {
  ok: boolean;
  latency_ms?: number;
  error?: string;
}

interface SendResult {
  ok: boolean;
  raw?: Record<string, unknown> | null;
  error?: string;
}

const PRESETS = [
  { label: "Test simplu", to: "", message: "Test SMS de la Tedde Auto. Mesajul a fost livrat cu succes." },
  { label: "Link portal", to: "", message: "Vă rugăm să accesați linkul pentru a vizualiza înregistrarea vehiculului dvs: {PORTAL_URL}" },
  { label: "Notificare", to: "", message: "Vehiculul dvs. a fost procesat. Mulțumim că ați ales Tedde Auto!" },
];

function countSmsSegments(text: string): { chars: number; segments: number; encoding: string } {
  const gsm7 = /^[\x00-\x7FÀ-ÆÈ-ÏÐ-ÖØ-öø-ÿΑ-ΡΣ-Ωα-ω€£¥àäåæçèéìñòöøùü]*$/;
  const isGsm = gsm7.test(text);
  const limit = isGsm ? 160 : 70;
  const multiLimit = isGsm ? 153 : 67;
  const chars = text.length;
  const segments = chars <= limit ? 1 : Math.ceil(chars / multiLimit);
  return { chars, segments, encoding: isGsm ? "GSM-7" : "Unicode" };
}

export default function SmsTestPage() {
  const [health, setHealth] = useState<GatewayHealth | null>(null);
  const [healthLoading, setHealthLoading] = useState(false);
  const [to, setTo] = useState("");
  const [message, setMessage] = useState(PRESETS[0].message);
  const [sending, setSending] = useState(false);
  const [result, setResult] = useState<SendResult | null>(null);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const checkHealth = async () => {
    setHealthLoading(true);
    try {
      const t0 = Date.now();
      const res = await fetch("/api/sms-gateway/health", { credentials: "include" });
      const latency_ms = Date.now() - t0;
      const data = await res.json();
      setHealth({ ok: data.ok ?? res.ok, latency_ms, error: data.error });
    } catch (e) {
      setHealth({ ok: false, error: String(e) });
    } finally {
      setHealthLoading(false);
    }
  };

  useEffect(() => {
    checkHealth();
    intervalRef.current = setInterval(checkHealth, 10000);
    return () => { if (intervalRef.current) clearInterval(intervalRef.current); };
  }, []);

  const sendSms = async () => {
    if (!to || !message) return;
    setSending(true);
    setResult(null);
    try {
      const res = await fetch("/api/sms-gateway/send", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({ to, message }),
      });
      const data = await res.json();
      setResult({ ok: res.ok && (data.ok !== false), raw: data });
    } catch (e) {
      setResult({ ok: false, error: String(e) });
    } finally {
      setSending(false);
    }
  };

  const applyPreset = (preset: typeof PRESETS[0]) => {
    setMessage(preset.message);
    setResult(null);
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if ((e.metaKey || e.ctrlKey) && e.key === "Enter") {
      e.preventDefault();
      sendSms();
    }
  };

  const smsInfo = countSmsSegments(message);

  return (
    <div className="min-h-screen bg-background">
      <div className="max-w-2xl mx-auto px-4 py-10 space-y-8">
        {/* Header */}
        <div>
          <h1 className="text-2xl font-bold flex items-center gap-2">
            <Phone className="h-6 w-6 text-primary" />
            Test SMS Gateway
          </h1>
          <p className="text-sm text-muted-foreground mt-1">Testează trimiterea de SMS-uri prin gateway-ul configurat</p>
        </div>

        {/* Gateway Health */}
        <div className="rounded-xl border bg-card p-5 space-y-3">
          <div className="flex items-center justify-between">
            <h2 className="text-sm font-semibold">Status Gateway</h2>
            <Button variant="ghost" size="sm" onClick={checkHealth} disabled={healthLoading} className="h-7 gap-1 text-xs">
              <RefreshCw className={`h-3 w-3 ${healthLoading ? "animate-spin" : ""}`} />
              Reîmprospătează
            </Button>
          </div>
          <div className="flex items-center gap-3">
            {health === null ? (
              <div className="h-2.5 w-2.5 rounded-full bg-muted animate-pulse" />
            ) : health.ok ? (
              <CheckCircle2 className="h-5 w-5 text-emerald-500 shrink-0" />
            ) : (
              <XCircle className="h-5 w-5 text-destructive shrink-0" />
            )}
            <div>
              <p className="text-sm font-medium">
                {health === null ? "Se verifică..." : health.ok ? "Gateway funcțional" : "Gateway inaccesibil"}
              </p>
              {health?.latency_ms != null && (
                <p className="text-xs text-muted-foreground">{health.latency_ms}ms latență</p>
              )}
              {health?.error && (
                <p className="text-xs text-destructive">{health.error}</p>
              )}
            </div>
            {health?.latency_ms != null && (
              <span className={`ml-auto text-xs font-mono px-2 py-0.5 rounded-full ${health.latency_ms < 200 ? "bg-emerald-500/10 text-emerald-600" : health.latency_ms < 500 ? "bg-yellow-500/10 text-yellow-600" : "bg-destructive/10 text-destructive"}`}>
                {health.latency_ms}ms
              </span>
            )}
          </div>
          <p className="text-xs text-muted-foreground">Auto-refresh la 10 secunde. API key-ul nu trece prin browser.</p>
        </div>

        {/* Presets */}
        <div className="space-y-2">
          <p className="text-xs font-medium text-muted-foreground uppercase tracking-wider">Preseturi mesaj</p>
          <div className="flex flex-wrap gap-2">
            {PRESETS.map((p) => (
              <button
                key={p.label}
                onClick={() => applyPreset(p)}
                className="px-3 py-1.5 rounded-lg border text-xs hover:bg-muted transition-colors"
              >
                {p.label}
              </button>
            ))}
          </div>
        </div>

        {/* Send Form */}
        <div className="rounded-xl border bg-card p-5 space-y-4">
          <h2 className="text-sm font-semibold">Trimite SMS</h2>
          <div className="space-y-1.5">
            <label className="text-sm font-medium">Număr destinatar</label>
            <input
              type="tel"
              value={to}
              onChange={(e) => setTo(e.target.value)}
              placeholder="+40712345678"
              className="w-full h-9 rounded-md border border-input bg-background px-3 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-ring"
            />
          </div>
          <div className="space-y-1.5">
            <div className="flex items-center justify-between">
              <label className="text-sm font-medium">Mesaj</label>
              <span className={`text-xs font-mono ${smsInfo.segments > 1 ? "text-yellow-600" : "text-muted-foreground"}`}>
                {smsInfo.chars} car. · {smsInfo.encoding} · {smsInfo.segments} segment{smsInfo.segments !== 1 ? "e" : ""}
              </span>
            </div>
            <textarea
              value={message}
              onChange={(e) => setMessage(e.target.value)}
              onKeyDown={handleKeyDown}
              rows={4}
              placeholder="Mesajul SMS..."
              className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-ring resize-none"
            />
            <p className="text-xs text-muted-foreground">Shortcut: <kbd className="px-1 py-0.5 rounded border text-xs font-mono">⌘ Enter</kbd> pentru trimitere rapidă</p>
          </div>
          <Button onClick={sendSms} disabled={sending || !to || !message} className="gap-1.5 w-full sm:w-auto">
            {sending ? <RefreshCw className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
            {sending ? "Se trimite..." : "Trimite SMS"}
          </Button>
        </div>

        {/* Result */}
        {result && (
          <div className={`rounded-xl border p-5 space-y-3 ${result.ok ? "border-emerald-500/30 bg-emerald-500/5" : "border-destructive/30 bg-destructive/5"}`}>
            <div className="flex items-center gap-2">
              {result.ok ? (
                <CheckCircle2 className="h-5 w-5 text-emerald-500" />
              ) : (
                <XCircle className="h-5 w-5 text-destructive" />
              )}
              <p className="text-sm font-semibold">{result.ok ? "SMS trimis cu succes" : "Eroare la trimitere"}</p>
            </div>
            {result.error && <p className="text-sm text-destructive">{result.error}</p>}
            {result.raw && (
              <pre className="text-xs font-mono bg-background/60 rounded-lg border p-3 overflow-auto max-h-48">
                {JSON.stringify(result.raw, null, 2)}
              </pre>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
