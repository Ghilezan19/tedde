"use client";

import { useMemo, useState } from "react";
import { CheckCircle2, Loader2, PlayCircle, RefreshCw, Zap } from "lucide-react";
import { Button } from "@/components/ui/button";
import { SaveBar } from "../_components/SaveBar";
import { PTZJoystick } from "../_components/PTZJoystick";
import { CameraStatusCard } from "../_components/CameraStatusCard";
import { LivePreview } from "../_components/LivePreview";

interface CamerasStreamingClientProps {
  config: Record<string, string>;
}

function FormField({
  label,
  name,
  value,
  type = "text",
  onChange,
  mono,
  hint,
}: {
  label: string;
  name: string;
  value: string;
  type?: string;
  onChange: (v: string) => void;
  mono?: boolean;
  hint?: string;
}) {
  return (
    <div className="space-y-1.5">
      <label className="text-sm font-medium">{label}</label>
      <input
        name={name}
        type={type}
        defaultValue={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={type === "password" ? "(lasă gol pentru a nu schimba)" : undefined}
        className={`w-full h-9 rounded-md border border-input bg-background px-3 text-sm shadow-sm focus:outline-none focus:ring-2 focus:ring-ring ${mono ? "font-mono" : ""}`}
      />
      {hint && <p className="text-xs text-muted-foreground">{hint}</p>}
    </div>
  );
}

type TriggerState = "idle" | "loading" | "ok" | "error";

function TriggerWorkflowButton() {
  const [state, setState] = useState<TriggerState>("idle");
  const [msg, setMsg] = useState("");

  async function handleTrigger() {
    setState("loading");
    setMsg("");
    try {
      const res = await fetch("/api/workflow/trigger", { method: "POST" });
      const data = await res.json().catch(() => ({}));
      if (res.ok && data.success) {
        setState("ok");
        setMsg("Workflow pornit!");
      } else {
        setState("error");
        setMsg(data.error ?? `Eroare ${res.status}`);
      }
    } catch (e) {
      setState("error");
      setMsg("Eroare de rețea");
    }
    // Reset back to idle after 4s
    setTimeout(() => { setState("idle"); setMsg(""); }, 4000);
  }

  return (
    <section className="rounded-xl border-2 border-red-500/40 bg-red-500/5 p-5">
      <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4">
        <div>
          <h2 className="text-sm font-semibold text-red-600 dark:text-red-400">🔴 Simulare apăsare buton ESP</h2>
          <p className="text-xs text-muted-foreground mt-0.5">
            Pornește un workflow de înregistrare exact ca și cum ar fi apăsat butonul fizic de pe ESP.
          </p>
        </div>
        <button
          onClick={handleTrigger}
          disabled={state === "loading" || state === "ok"}
          className="flex items-center gap-2.5 rounded-xl px-8 py-4 text-base font-bold text-white bg-red-600 hover:bg-red-700 active:scale-95 disabled:opacity-60 disabled:cursor-not-allowed transition-all shadow-lg shadow-red-600/30 shrink-0"
        >
          {state === "loading" && <Loader2 className="h-5 w-5 animate-spin" />}
          {state === "ok" && <CheckCircle2 className="h-5 w-5" />}
          {(state === "idle" || state === "error") && <PlayCircle className="h-5 w-5" />}
          {state === "loading" ? "Se pornește..." : state === "ok" ? "Pornit!" : "Pornește Workflow"}
        </button>
      </div>
      {msg && (
        <p className={`mt-3 text-xs font-medium ${state === "error" ? "text-red-600" : "text-green-600"}`}>
          {msg}
        </p>
      )}
    </section>
  );
}

export function CamerasStreamingClient({ config }: CamerasStreamingClientProps) {
  const [values, setValues] = useState({ ...config });
  const [refreshToken, setRefreshToken] = useState(0);
  const [cam1Online, setCam1Online] = useState<boolean | null>(null);
  const [cam2Online, setCam2Online] = useState<boolean | null>(null);

  const set = (key: string) => (v: string) =>
    setValues((prev) => ({ ...prev, [key]: v }));

  // Use saved .env values (not edited-but-unsaved) for probes & preview
  const cam1Ip = (config.CAMERA_IP || "").trim();
  const cam1Rtsp = parseInt(config.CAMERA_RTSP_PORT || "554", 10);
  const cam2Ip = (config.CAMERA2_IP || "").trim();
  const cam2Rtsp = parseInt(config.CAMERA2_RTSP_PORT || "554", 10);
  const cam2Http = parseInt(config.CAMERA2_HTTP_PORT || "80", 10);

  const cam1Probes = useMemo(
    () => [{ port: cam1Rtsp, label: `RTSP ${cam1Rtsp}` }],
    [cam1Rtsp],
  );
  const cam2Probes = useMemo(
    () => [
      { port: cam2Rtsp, label: `RTSP ${cam2Rtsp}` },
      { port: cam2Http, label: `HTTP ${cam2Http}` },
    ],
    [cam2Rtsp, cam2Http],
  );

  return (
    <div className="space-y-8 pb-20">
      <div>
        <h1 className="text-xl font-bold text-foreground">Camere & Streaming</h1>
        <p className="text-sm text-muted-foreground mt-1">
          Configurare conexiuni camere, previzualizare live și control PTZ
        </p>
      </div>

      {/* ── Live status + previews ─────────────────────────── */}
      <section className="rounded-xl border bg-card p-5 space-y-4">
        <div className="flex items-center justify-between gap-3 flex-wrap">
          <div>
            <h2 className="text-sm font-semibold">Stare conexiune camere</h2>
            <p className="text-xs text-muted-foreground mt-0.5">
              Verificare automată la fiecare 15 secunde
            </p>
          </div>
          <div className="flex items-center gap-2">
            <Button
              variant="outline"
              size="sm"
              onClick={() => setRefreshToken((n) => n + 1)}
              className="gap-1.5"
            >
              <RefreshCw className="h-3.5 w-3.5" />
              Verifică acum
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={() => (window.location.href = "/configure/network-esp")}
              className="gap-1.5"
            >
              <Zap className="h-3.5 w-3.5" />
              Scanează rețeaua
            </Button>
          </div>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <CameraStatusCard
            title="Camera 1 — Fixă"
            subtitle="Stream principal + secundar"
            ip={cam1Ip}
            probes={cam1Probes}
            refreshToken={refreshToken}
            onStateChange={setCam1Online}
          />
          <CameraStatusCard
            title="Camera 2 — PTZ"
            subtitle="Control pan/tilt/zoom"
            ip={cam2Ip}
            probes={cam2Probes}
            refreshToken={refreshToken}
            onStateChange={setCam2Online}
          />
        </div>

        {/* Live previews side-by-side */}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4 pt-2">
          <LivePreview camera={1} fps={6} online={cam1Online ?? undefined} label="CAM 1" />
          <LivePreview camera={2} fps={6} online={cam2Online ?? undefined} label="CAM 2" />
        </div>
      </section>

      {/* ── Trigger manual workflow ─────────────────────────── */}
      <TriggerWorkflowButton />

      {/* ── Camera 1 config ────────────────────────────────── */}
      <section className="rounded-xl border bg-card p-5 space-y-4">
        <h2 className="text-sm font-semibold">📷 Camera 1 — Fixă</h2>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <FormField label="IP Cameră 1" name="CAMERA_IP" value={values.CAMERA_IP || ""} onChange={set("CAMERA_IP")} mono />
          <FormField label="Port RTSP" name="CAMERA_RTSP_PORT" value={values.CAMERA_RTSP_PORT || "554"} onChange={set("CAMERA_RTSP_PORT")} mono />
          <FormField label="Username" name="CAMERA_USERNAME" value={values.CAMERA_USERNAME || ""} onChange={set("CAMERA_USERNAME")} />
          <FormField label="Parolă" name="CAMERA_PASSWORD" value="" type="password" onChange={set("CAMERA_PASSWORD")} />
          <FormField label="Path stream principal" name="RTSP_MAIN_PATH" value={values.RTSP_MAIN_PATH || ""} onChange={set("RTSP_MAIN_PATH")} mono hint="ex. /Streaming/channels/101" />
          <FormField label="Path stream secundar" name="RTSP_SUB_PATH" value={values.RTSP_SUB_PATH || ""} onChange={set("RTSP_SUB_PATH")} mono hint="ex. /Streaming/channels/102" />
        </div>
      </section>

      {/* ── Camera 2 config ────────────────────────────────── */}
      <section className="rounded-xl border bg-card p-5 space-y-4">
        <h2 className="text-sm font-semibold">📷 Camera 2 — PTZ</h2>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <FormField label="IP Cameră 2" name="CAMERA2_IP" value={values.CAMERA2_IP || ""} onChange={set("CAMERA2_IP")} mono />
          <FormField label="Port RTSP" name="CAMERA2_RTSP_PORT" value={values.CAMERA2_RTSP_PORT || "554"} onChange={set("CAMERA2_RTSP_PORT")} mono />
          <FormField label="Port HTTP (ISAPI)" name="CAMERA2_HTTP_PORT" value={values.CAMERA2_HTTP_PORT || "80"} onChange={set("CAMERA2_HTTP_PORT")} mono />
          <FormField label="Port SDK" name="CAMERA2_SDK_PORT" value={values.CAMERA2_SDK_PORT || "8000"} onChange={set("CAMERA2_SDK_PORT")} mono />
          <FormField label="Username" name="CAMERA2_USERNAME" value={values.CAMERA2_USERNAME || ""} onChange={set("CAMERA2_USERNAME")} />
          <FormField label="Parolă" name="CAMERA2_PASSWORD" value="" type="password" onChange={set("CAMERA2_PASSWORD")} />
          <FormField label="Profil ONVIF" name="CAMERA2_ONVIF_PROFILE" value={values.CAMERA2_ONVIF_PROFILE || ""} onChange={set("CAMERA2_ONVIF_PROFILE")} />
        </div>
      </section>

      {/* ── PTZ Preview + Joystick ─────────────────────────── */}
      <section className="rounded-xl border bg-card p-5 space-y-4">
        <h2 className="text-sm font-semibold">🎯 Previzualizare & Control PTZ</h2>
        <div className="flex flex-col lg:flex-row gap-6">
          <div className="flex-1 min-w-0">
            <LivePreview camera={2} fps={8} online={cam2Online ?? undefined} label="CAM 2 — PTZ" />
          </div>
          <PTZJoystick />
        </div>
      </section>

      <SaveBar
        getValues={() => {
          const filtered: Record<string, string> = {};
          Object.entries(values).forEach(([k, v]) => {
            // Skip empty password fields (so they don't overwrite saved passwords)
            if (k.includes("PASSWORD") && !v) return;
            filtered[k] = v;
          });
          return filtered;
        }}
      />
    </div>
  );
}
