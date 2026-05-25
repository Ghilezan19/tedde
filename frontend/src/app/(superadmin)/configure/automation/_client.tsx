"use client";

import { Button } from "@/components/ui/button";
import { ArrowDown, ArrowLeft, ArrowRight, ArrowUp, BookmarkCheck, CheckCircle2, Loader2, Play, Scan, Square, XCircle, ZoomIn, ZoomOut } from "lucide-react";
import { useCallback, useState } from "react";
import { LivePreview } from "../_components/LivePreview";
import { SaveBar } from "../_components/SaveBar";

interface Props { config: Record<string, string>; }

// ALPR models available
const DETECTOR_MODELS = [
  "yolo-v9-t-384-license-plate-end2end",
  "yolo-v9-s-608-license-plate-end2end",
  "yolo-v9-c-640-license-plate-end2end",
];
const OCR_MODELS = [
  "cct-xs-v2-global-model",
  "cct-s-v1-global-model",
];

type BenchmarkRow = {
  detector: string;
  ocr: string;
  plate: string;
  confidence: number | null;
  status: "pending" | "running" | "done" | "error";
};

// PTZ joystick directions
const PTZ_DIRS = [
  { dir: "up-left", Icon: null, row: 1, col: 1 },
  { dir: "up", Icon: ArrowUp, row: 1, col: 2 },
  { dir: "up-right", Icon: null, row: 1, col: 3 },
  { dir: "left", Icon: ArrowLeft, row: 2, col: 1 },
  { dir: "stop", Icon: Square, row: 2, col: 2 },
  { dir: "right", Icon: ArrowRight, row: 2, col: 3 },
  { dir: "down-left", Icon: null, row: 3, col: 1 },
  { dir: "down", Icon: ArrowDown, row: 3, col: 2 },
  { dir: "down-right", Icon: null, row: 3, col: 3 },
] as const;

export function AutomationClient({ config }: Props) {
  const [values, setValues] = useState({ ...config });
  const [alprResult, setAlprResult] = useState<{ plate: string; confidence: string; snapshot?: string } | null>(null);
  const [alprLoading, setAlprLoading] = useState(false);
  const [workflowStatus, setWorkflowStatus] = useState<string | null>(null);

  // ALPR benchmark state
  const [benchRows, setBenchRows] = useState<BenchmarkRow[]>([]);
  const [benchRunning, setBenchRunning] = useState(false);
  const [benchBest, setBenchBest] = useState<BenchmarkRow | null>(null);

  // PTZ preset config state
  const [ptzSpeed, setPtzSpeed] = useState(4);
  const [savingPreset, setSavingPreset] = useState<"piese" | "masina" | null>(null);
  const [presetSaved, setPresetSaved] = useState<{ piese?: boolean; masina?: boolean }>({});

  const set = (key: string) => (v: string) => setValues((prev) => ({ ...prev, [key]: v }));

  const testAlpr = async () => {
    setAlprLoading(true);
    setAlprResult(null);
    try {
      const res = await fetch("/api/alpr/test", { method: "POST", credentials: "include" });
      const data = await res.json();
      setAlprResult({
        plate: data.selected_plate || "Nedetectat",
        confidence: data.selected_confidence != null ? `${(data.selected_confidence * 100).toFixed(1)}%` : "—",
        snapshot: data.snapshot_url,
      });
    } catch {
      setAlprResult({ plate: "Eroare", confidence: "—" });
    } finally {
      setAlprLoading(false);
    }
  };

  const triggerWorkflow = async () => {
    const res = await fetch("/api/workflow/trigger", { method: "POST", credentials: "include" });
    const data = await res.json();
    setWorkflowStatus(data.message || data.status || JSON.stringify(data));
  };

  const sliderValue = (key: string, def: number) => Number(values[key] || def);

  // ── ALPR Benchmark ──────────────────────────────────────────────
  const runBenchmark = useCallback(async () => {
    setBenchRunning(true);
    setBenchBest(null);
    const rows: BenchmarkRow[] = DETECTOR_MODELS.flatMap((detector) =>
      OCR_MODELS.map((ocr) => ({ detector, ocr, plate: "", confidence: null, status: "pending" as const }))
    );
    setBenchRows([...rows]);

    let best: BenchmarkRow | null = null;
    for (let i = 0; i < rows.length; i++) {
      rows[i] = { ...rows[i], status: "running" };
      setBenchRows([...rows]);
      try {
        const res = await fetch("/api/alpr/test", {
          method: "POST",
          credentials: "include",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ detector_model: rows[i].detector, ocr_model: rows[i].ocr }),
        });
        const data = await res.json();
        const conf = data.selected_confidence ?? null;
        rows[i] = { ...rows[i], status: "done", plate: data.selected_plate || "—", confidence: conf };
        if (conf != null && (best === null || conf > (best.confidence ?? 0))) best = rows[i];
      } catch {
        rows[i] = { ...rows[i], status: "error", plate: "Eroare" };
      }
      setBenchRows([...rows]);
    }
    setBenchBest(best);
    setBenchRunning(false);
  }, []);

  const applyBenchBest = () => {
    if (!benchBest) return;
    setValues((prev) => ({
      ...prev,
      ALPR_DETECTOR_MODEL: benchBest.detector,
      ALPR_OCR_MODEL: benchBest.ocr,
    }));
  };

  // ── PTZ preset save ──────────────────────────────────────────────
  const ptzMove = useCallback(async (direction: string) => {
    if (direction === "stop") {
      await fetch("/api/ptz/stop", { method: "POST", credentials: "include" });
    } else {
      await fetch("/api/ptz/move", {
        method: "POST", credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ direction, speed: ptzSpeed }),
      });
    }
  }, [ptzSpeed]);

  const ptzStop = useCallback(async () => {
    await fetch("/api/ptz/stop", { method: "POST", credentials: "include" });
  }, []);

  const ptzZoom = async (dir: "in" | "out") => {
    await fetch("/api/ptz/zoom", {
      method: "POST", credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ direction: dir }),
    });
  };

  const saveWorkflowPreset = async (slot: "piese" | "masina") => {
    const envKey = slot === "piese" ? "PTZ_PRESET_HOME" : "PTZ_PRESET_SECONDARY";
    const existingToken = values[envKey];
    setSavingPreset(slot);
    setPresetSaved((prev) => ({ ...prev, [slot]: false }));
    try {
      // Delete old preset first (camera doesn't support update via SetPreset)
      if (existingToken) {
        await fetch(`/api/ptz/presets/${encodeURIComponent(existingToken)}`, {
          method: "DELETE", credentials: "include",
        });
      }
      // Create new preset (no token — camera assigns one)
      const res = await fetch("/api/ptz/presets", {
        method: "POST", credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: slot === "piese" ? "Piese" : "Masina" }),
      });
      const data = await res.json();
      if (res.ok && data.token) {
        setValues((prev) => ({ ...prev, [envKey]: data.token }));
        setPresetSaved((prev) => ({ ...prev, [slot]: true }));
        setTimeout(() => setPresetSaved((prev) => ({ ...prev, [slot]: false })), 4000);
      } else {
        setPresetSaved((prev) => ({ ...prev, [slot]: false }));
        alert(`Eroare la salvare preset: ${data.error || res.status}`);
      }
    } finally {
      setSavingPreset(null);
    }
  };

  return (
    <div className="space-y-8 pb-20">
      <div>
        <h1 className="text-xl font-bold">Automatizare</h1>
        <p className="text-sm text-muted-foreground mt-1">ALPR, înregistrare și workflow trigger</p>
      </div>

      {/* ALPR */}
      <section className="rounded-xl border bg-card p-5 space-y-5">
        <h2 className="text-sm font-semibold">🔍 ALPR — Recunoaștere plăcuțe</h2>

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          {[
            { key: "ALPR_DETECTOR_MODEL", label: "Model detector" },
            { key: "ALPR_OCR_MODEL", label: "Model OCR" },
          ].map(({ key, label }) => (
            <div key={key} className="space-y-1.5">
              <label className="text-sm font-medium">{label}</label>
              <input
                type="text"
                value={values[key] || ""}
                onChange={(e) => set(key)(e.target.value)}
                className="w-full h-9 rounded-md border border-input bg-background px-3 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-ring"
              />
            </div>
          ))}

          <div className="space-y-1.5">
            <label className="text-sm font-medium">ALPR Activat</label>
            <select
              value={values.ALPR_ENABLED || "1"}
              onChange={(e) => set("ALPR_ENABLED")(e.target.value)}
              className="w-full h-9 rounded-md border border-input bg-background px-3 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
            >
              <option value="1">Da</option>
              <option value="0">Nu</option>
            </select>
          </div>

          <div className="space-y-1.5">
            <p className="text-xs text-muted-foreground">Camera</p>
            <p className="text-sm">Întotdeauna Camera 2</p>
          </div>
        </div>

        {/* Confidence threshold */}
        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <label className="text-sm font-medium">Prag de confidență</label>
            <span className="text-sm font-mono font-medium">
              {(sliderValue("ALPR_DETECTOR_CONF_THRESH", 0.3) * 100).toFixed(0)}%
            </span>
          </div>
          <input
            type="range"
            min={5}
            max={95}
            value={(sliderValue("ALPR_DETECTOR_CONF_THRESH", 0.3) * 100).toFixed(0)}
            onChange={(e) => set("ALPR_DETECTOR_CONF_THRESH")((Number(e.target.value) / 100).toFixed(2))}
            className="w-full"
          />
          <div className="flex justify-between text-xs text-muted-foreground">
            <span>5% (permisiv)</span><span>95% (strict)</span>
          </div>
        </div>

        {/* Upscale retry */}
        <div className="flex items-center gap-3">
          <input
            type="checkbox"
            id="alpr-upscale"
            checked={values.ALPR_RETRY_WITH_UPSCALE === "1"}
            onChange={(e) => set("ALPR_RETRY_WITH_UPSCALE")(e.target.checked ? "1" : "0")}
            className="h-4 w-4 rounded border border-input"
          />
          <label htmlFor="alpr-upscale" className="text-sm">Retry cu upscale dacă nu se detectează</label>
        </div>

        {/* Test button */}
        <div className="space-y-3">
          <Button onClick={testAlpr} disabled={alprLoading} className="gap-1.5">
            {alprLoading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Scan className="h-4 w-4" />}
            Capturează și detectează
          </Button>
          {alprResult && (
            <div className="rounded-lg border bg-muted/30 p-4 space-y-3">
              <p className="text-3xl font-mono font-bold text-primary">{alprResult.plate}</p>
              <p className="text-sm text-muted-foreground">Confidență: <span className="font-medium">{alprResult.confidence}</span></p>
              {alprResult.snapshot && (
                // eslint-disable-next-line @next/next/no-img-element
                <img src={alprResult.snapshot} alt="Snapshot ALPR" className="max-w-xs rounded-lg border" />
              )}
            </div>
          )}
        </div>
      </section>

      {/* Recording */}
      <section className="rounded-xl border bg-card p-5 space-y-5">
        <h2 className="text-sm font-semibold">⏺ Înregistrare</h2>

        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <label className="text-sm font-medium">Durată înregistrare</label>
            <span className="text-sm font-mono font-medium">{values.RECORDING_DURATION_SECONDS || "10"}s</span>
          </div>
          <input
            type="range"
            min={5}
            max={600}
            step={5}
            value={values.RECORDING_DURATION_SECONDS || 10}
            onChange={(e) => set("RECORDING_DURATION_SECONDS")(e.target.value)}
            className="w-full"
          />
          <div className="flex justify-between text-xs text-muted-foreground">
            <span>5s</span><span>600s</span>
          </div>
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <div className="space-y-1.5">
            <label className="text-sm font-medium">Calitate stream</label>
            <select
              value={values.RECORDING_QUALITY || "main"}
              onChange={(e) => set("RECORDING_QUALITY")(e.target.value)}
              className="w-full h-9 rounded-md border border-input bg-background px-3 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
            >
              <option value="main">Main HD</option>
              <option value="sub">Sub SD</option>
            </select>
          </div>
          <div className="space-y-1.5">
            <label className="text-sm font-medium">Countdown ESP (secunde)</label>
            <input
              type="number"
              value={values.ESP_COUNTDOWN_SECONDS || ""}
              onChange={(e) => set("ESP_COUNTDOWN_SECONDS")(e.target.value)}
              placeholder="(implicit = durată înregistrare)"
              className="w-full h-9 rounded-md border border-input bg-background px-3 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-ring"
            />
          </div>
        </div>
      </section>

      {/* ALPR Auto-Benchmark */}
      <section className="rounded-xl border bg-card p-5 space-y-4">
        <div className="flex items-start justify-between">
          <div>
            <h2 className="text-sm font-semibold">🧪 Auto-benchmark modele ALPR</h2>
            <p className="text-xs text-muted-foreground mt-0.5">Testează toate combinațiile detector+OCR pe imaginea curentă și selectează cel mai bun.</p>
          </div>
          <Button onClick={runBenchmark} disabled={benchRunning} size="sm" className="gap-1.5 shrink-0">
            {benchRunning ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Scan className="h-3.5 w-3.5" />}
            {benchRunning ? "Rulează..." : "Pornește benchmark"}
          </Button>
        </div>

        {benchRows.length > 0 && (
          <div className="rounded-lg border overflow-hidden">
            <table className="w-full text-xs">
              <thead className="bg-muted/50 border-b">
                <tr>
                  <th className="px-3 py-2 text-left font-semibold text-muted-foreground">Detector</th>
                  <th className="px-3 py-2 text-left font-semibold text-muted-foreground">OCR</th>
                  <th className="px-3 py-2 text-left font-semibold text-muted-foreground">Plăcuță</th>
                  <th className="px-3 py-2 text-right font-semibold text-muted-foreground">Conf.</th>
                  <th className="px-3 py-2 text-center font-semibold text-muted-foreground">Status</th>
                </tr>
              </thead>
              <tbody className="divide-y">
                {benchRows.map((row, i) => (
                  <tr key={i} className={benchBest && benchBest.detector === row.detector && benchBest.ocr === row.ocr ? "bg-primary/10" : "hover:bg-muted/30"}>
                    <td className="px-3 py-2 font-mono truncate max-w-[120px]">{row.detector.replace("yolo-v9-", "").replace("-license-plate-end2end", "")}</td>
                    <td className="px-3 py-2 font-mono truncate max-w-[100px]">{row.ocr.replace("-global-model", "")}</td>
                    <td className="px-3 py-2 font-mono font-bold">{row.plate || "—"}</td>
                    <td className="px-3 py-2 text-right font-mono">{row.confidence != null ? `${(row.confidence * 100).toFixed(1)}%` : "—"}</td>
                    <td className="px-3 py-2 text-center">
                      {row.status === "pending" && <span className="text-muted-foreground">·</span>}
                      {row.status === "running" && <Loader2 className="h-3 w-3 animate-spin inline text-primary" />}
                      {row.status === "done" && <CheckCircle2 className="h-3.5 w-3.5 inline text-green-500" />}
                      {row.status === "error" && <XCircle className="h-3.5 w-3.5 inline text-destructive" />}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {benchBest && !benchRunning && (
          <div className="flex items-center gap-3 rounded-lg border border-primary/30 bg-primary/5 p-3">
            <CheckCircle2 className="h-4 w-4 text-primary shrink-0" />
            <div className="flex-1 min-w-0">
              <p className="text-xs font-medium">Cel mai bun: <span className="font-mono">{benchBest.detector.replace("yolo-v9-", "").replace("-license-plate-end2end", "")}</span> + <span className="font-mono">{benchBest.ocr.replace("-global-model", "")}</span></p>
              <p className="text-xs text-muted-foreground">Plăcuță: <strong>{benchBest.plate}</strong> · Conf: {benchBest.confidence != null ? `${(benchBest.confidence * 100).toFixed(1)}%` : "—"}</p>
            </div>
            <Button size="sm" variant="outline" onClick={applyBenchBest} className="shrink-0 text-xs h-7">
              Aplică
            </Button>
          </div>
        )}
      </section>

      {/* PTZ Workflow Presets */}
      <section className="rounded-xl border bg-card p-5 space-y-5">
        <h2 className="text-sm font-semibold">🎯 Preseturi PTZ Workflow</h2>
        <p className="text-xs text-muted-foreground">Configurează poziția &ldquo;Piese&rdquo; (înainte de înregistrare) și &ldquo;Mașină&rdquo; (în timpul înregistrării). Mută camera cu joystick-ul, apoi apasă &ldquo;Salvează poziția&rdquo;.</p>

        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          {/* Live preview */}
          <div className="space-y-2">
            <p className="text-xs font-medium text-muted-foreground uppercase tracking-wider">Preview live — Camera PTZ</p>
            <LivePreview camera={2} fps={5} label="PTZ" />
          </div>

          {/* Goto preset buttons */}
          <div className="space-y-2">
            <p className="text-xs font-medium text-muted-foreground uppercase tracking-wider">Mergi la preset</p>
            <div className="flex gap-2 flex-wrap">
              {(["piese", "masina"] as const).map((slot) => {
                const envKey = slot === "piese" ? "PTZ_PRESET_HOME" : "PTZ_PRESET_SECONDARY";
                const token = values[envKey];
                const label = slot === "piese" ? "🔧 Piese" : "🚗 Mașină";
                return (
                  <Button
                    key={slot}
                    size="sm"
                    variant="outline"
                    disabled={!token}
                    className="gap-1.5"
                    onClick={async () => {
                      if (!token) return;
                      await fetch("/api/ptz/goto", {
                        method: "POST", credentials: "include",
                        headers: { "Content-Type": "application/json" },
                        body: JSON.stringify({ token }),
                      });
                    }}
                  >
                    {label}
                    {token && <span className="font-mono text-muted-foreground text-[10px]">#{token}</span>}
                  </Button>
                );
              })}
            </div>
          </div>

          {/* Joystick */}
          <div className="space-y-4">
            <p className="text-xs font-medium text-muted-foreground uppercase tracking-wider">Joystick</p>
            <div className="grid grid-cols-3 gap-1 w-36">
              {PTZ_DIRS.map(({ dir, Icon }) => (
                <button
                  key={dir}
                  className={`h-11 w-11 rounded-md border flex items-center justify-center transition-colors ${
                    dir === "stop" ? "bg-muted hover:bg-muted/70" : Icon ? "bg-card hover:bg-muted cursor-pointer" : "invisible"
                  }`}
                  onPointerDown={() => Icon && ptzMove(dir)}
                  onPointerUp={ptzStop}
                  onPointerLeave={ptzStop}
                  disabled={!Icon}
                >
                  {Icon && <Icon className="h-4 w-4" />}
                </button>
              ))}
            </div>
            <div className="flex items-center gap-2 w-36">
              <button className="h-9 w-9 rounded-md border flex items-center justify-center hover:bg-muted" onPointerDown={() => ptzZoom("out")} onPointerUp={ptzStop} onPointerLeave={ptzStop}>
                <ZoomOut className="h-4 w-4" />
              </button>
              <span className="text-xs text-muted-foreground flex-1 text-center">Zoom</span>
              <button className="h-9 w-9 rounded-md border flex items-center justify-center hover:bg-muted" onPointerDown={() => ptzZoom("in")} onPointerUp={ptzStop} onPointerLeave={ptzStop}>
                <ZoomIn className="h-4 w-4" />
              </button>
            </div>
            <div className="flex items-center gap-3 w-36">
              <label className="text-xs text-muted-foreground shrink-0">Vit: {ptzSpeed}</label>
              <input type="range" min={1} max={7} value={ptzSpeed} onChange={(e) => setPtzSpeed(Number(e.target.value))} className="w-full" />
            </div>
          </div>
        </div>

        {/* Preset slots */}
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          {(["piese", "masina"] as const).map((slot) => {
            const envKey = slot === "piese" ? "PTZ_PRESET_HOME" : "PTZ_PRESET_SECONDARY";
            const durKey = slot === "piese" ? "PTZ_HOME_RECORDING_SECONDS" : "PTZ_SECONDARY_RECORDING_SECONDS";
            const label = slot === "piese" ? "🔧 Piese" : "🚗 Mașină";
            const hint = slot === "piese" ? "Camera se mută ÎNAINTE de înregistrare (fără înregistrare)" : "Poziția principală — înregistrare activă";
            return (
              <div key={slot} className={`rounded-lg border p-4 space-y-3 transition-colors duration-300 ${presetSaved[slot] ? "border-green-500 bg-green-500/10" : "bg-muted/20"}`}>
                <div className="flex items-center justify-between">
                  <p className="text-sm font-semibold">{label}</p>
                  {presetSaved[slot] && (
                    <span className="text-xs font-semibold text-green-600 flex items-center gap-1 animate-pulse">
                      <CheckCircle2 className="h-3.5 w-3.5" />Poziție salvată!
                    </span>
                  )}
                </div>
                <p className="text-xs text-muted-foreground">{hint}</p>
                <div className="space-y-1.5">
                  <label className="text-xs font-medium">Token preset ONVIF</label>
                  <input
                    type="text"
                    value={values[envKey] || (slot === "piese" ? "1" : "2")}
                    onChange={(e) => set(envKey)(e.target.value)}
                    className="w-full h-8 rounded-md border border-input bg-background px-2 text-xs font-mono focus:outline-none focus:ring-2 focus:ring-ring"
                    placeholder={slot === "piese" ? "1" : "2"}
                  />
                </div>
                <div className="space-y-1.5">
                  <div className="flex items-center justify-between">
                    <label className="text-xs font-medium">Durată înregistrare</label>
                    {Number(values[durKey] ?? (slot === "piese" ? 5 : 120)) === 0
                      ? <span className="text-xs font-semibold text-orange-500">Dezactivat</span>
                      : <span className="text-xs font-mono">{values[durKey] || (slot === "piese" ? "5" : "120")}s</span>
                    }
                  </div>
                  <input
                    type="range"
                    min={0}
                    max={300}
                    step={5}
                    value={Number(values[durKey] ?? (slot === "piese" ? 5 : 120))}
                    onChange={(e) => set(durKey)(e.target.value)}
                    className="w-full"
                  />
                  <div className="flex justify-between text-xs text-muted-foreground"><span>0 (skip)</span><span>300s</span></div>
                </div>
                <Button
                  size="sm"
                  variant="outline"
                  className="w-full gap-1.5"
                  disabled={savingPreset === slot}
                  onClick={() => saveWorkflowPreset(slot)}
                >
                  {savingPreset === slot ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <BookmarkCheck className="h-3.5 w-3.5" />}
                  Salvează poziția curentă ca &ldquo;{slot === "piese" ? "Piese" : "Mașină"}&rdquo;
                </Button>
              </div>
            );
          })}
        </div>

        {/* PTZ settle time */}
        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <label className="text-sm font-medium">Timp așteptare după mișcare PTZ</label>
            <span className="text-sm font-mono">{values.PTZ_SETTLE_SECONDS || "3"}s</span>
          </div>
          <input
            type="range"
            min={1}
            max={15}
            value={Number(values.PTZ_SETTLE_SECONDS || 3)}
            onChange={(e) => set("PTZ_SETTLE_SECONDS")(e.target.value)}
            className="w-full"
          />
          <p className="text-xs text-muted-foreground">Secunde de pauză după ce camera PTZ s-a mutat la preset, înainte de start înregistrare.</p>
        </div>
      </section>

      {/* Workflow trigger */}
      <section className="rounded-xl border bg-card p-5 space-y-3">
        <h2 className="text-sm font-semibold">▶ Trigger Workflow manual</h2>
        <p className="text-xs text-muted-foreground">Pornește un eveniment de înregistrare fără ESP.</p>
        <div className="flex items-center gap-3">
          <Button variant="outline" onClick={triggerWorkflow} className="gap-1.5">
            <Play className="h-4 w-4" />
            Trigger Workflow
          </Button>
          {workflowStatus && (
            <span className="text-xs text-muted-foreground">{workflowStatus}</span>
          )}
        </div>
      </section>

      <SaveBar getValues={() => values} />
    </div>
  );
}
