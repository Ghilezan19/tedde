"use client";

import { useState, useEffect, useCallback } from "react";
import { Maximize2, X, RefreshCw, VideoOff, Loader2 } from "lucide-react";
import { LivePreview } from "@/components/LivePreview";
import { useWorkflowRecordingBlock } from "@/hooks/useWorkflowRecordingBlock";

interface CameraConfig {
  id: 1 | 2;
  label: string;
  sublabel: string;
}

const CAMERAS: CameraConfig[] = [
  { id: 1, label: "Camera 1", sublabel: "Fixă" },
  { id: 2, label: "Camera 2", sublabel: "PTZ" },
];

/** Full-screen overlay pentru o singură cameră */
function FullscreenModal({
  camera,
  label,
  onClose,
}: {
  camera: 1 | 2;
  label: string;
  onClose: () => void;
}) {
  const [nonce, setNonce] = useState(0);
  const [errored, setErrored] = useState(false);
  const { blocked, elapsedSec, durationSec } = useWorkflowRecordingBlock(camera);
  const recordingBlocks = blocked;

  const STREAM_BASE = process.env.NEXT_PUBLIC_BACKEND_URL ?? "";
  const streamUrl = `${STREAM_BASE}/api/stream?camera=${camera}&fps=8&_=${nonce}`;
  const progressText =
    recordingBlocks && elapsedSec != null && durationSec != null
      ? `${Math.floor(elapsedSec / 60)}m ${elapsedSec % 60}s din ~${Math.ceil(durationSec / 60)}m`
      : null;

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

  // Blochează scroll-ul body cât modalul e deschis
  useEffect(() => {
    document.body.style.overflow = "hidden";
    return () => { document.body.style.overflow = ""; };
  }, []);

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/90 backdrop-blur-sm"
      onClick={onClose}
    >
      <div
        className="relative w-full max-w-[90vw] max-h-[90vh] aspect-video"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Stream sau placeholder înregistrare / fallback */}
        {recordingBlocks ? (
          <div className="w-full h-full flex flex-col items-center justify-center bg-zinc-950 rounded-lg gap-3 text-muted-foreground px-8 text-center">
            <Loader2 className="h-14 w-14 opacity-60 animate-spin" />
            <p className="text-base font-medium text-amber-500">Înregistrare în curs</p>
            <p className="text-sm max-w-md">
              Preview fullscreen este indisponibil pentru a nu întrerupe RTSP-ul. Se reactivează
              automat după terminarea sesiunii.
            </p>
            {progressText && (
              <p className="text-xs font-mono text-muted-foreground">{progressText}</p>
            )}
          </div>
        ) : !errored ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            key={nonce}
            src={streamUrl}
            alt={label}
            className="w-full h-full object-contain rounded-lg"
            onError={() => setErrored(true)}
          />
        ) : (
          <div className="w-full h-full flex flex-col items-center justify-center bg-zinc-900 rounded-lg gap-3 text-muted-foreground">
            <VideoOff className="h-14 w-14 opacity-40" />
            <p className="text-sm">Stream indisponibil</p>
            <button
              onClick={() => { setErrored(false); setNonce((n) => n + 1); }}
              className="inline-flex items-center gap-1.5 text-sm text-primary hover:underline"
            >
              <RefreshCw className="h-3.5 w-3.5" />
              Reîncearcă
            </button>
          </div>
        )}

        {/* Badge LIVE */}
        {!errored && !recordingBlocks && (
          <div className="absolute top-3 left-3 inline-flex items-center gap-1.5 rounded-full bg-black/60 backdrop-blur-sm px-2.5 py-1 text-xs font-semibold text-white">
            <span className="relative flex h-2 w-2">
              <span className="absolute inline-flex h-full w-full rounded-full bg-red-500 opacity-75 animate-ping" />
              <span className="relative inline-flex rounded-full h-2 w-2 bg-red-500" />
            </span>
            LIVE
          </div>
        )}

        {/* Label cameră */}
        <div className="absolute top-3 right-16 rounded-full bg-black/60 backdrop-blur-sm px-2.5 py-1 text-xs font-semibold text-white">
          {label}
        </div>

        {/* Butoane acțiuni top-right */}
        <div className="absolute top-3 right-3 flex gap-2">
          {!errored && !recordingBlocks && (
            <button
              onClick={() => { setErrored(false); setNonce((n) => n + 1); }}
              title="Reîncarcă stream"
              className="h-8 w-8 rounded-full bg-black/60 backdrop-blur-sm hover:bg-black/80 flex items-center justify-center text-white transition-colors"
            >
              <RefreshCw className="h-4 w-4" />
            </button>
          )}
          <button
            onClick={onClose}
            title="Închide"
            className="h-8 w-8 rounded-full bg-black/60 backdrop-blur-sm hover:bg-red-600/80 flex items-center justify-center text-white transition-colors"
          >
            <X className="h-4 w-4" />
          </button>
        </div>
      </div>
    </div>
  );
}

/** Card individual pentru o cameră cu buton fullscreen */
function CameraCard({ camera }: { camera: CameraConfig }) {
  const [fullscreen, setFullscreen] = useState(false);
  const openFullscreen = useCallback(() => setFullscreen(true), []);
  const closeFullscreen = useCallback(() => setFullscreen(false), []);

  return (
    <>
      <div className="space-y-2">
        {/* Header card */}
        <div className="flex items-center justify-between">
          <div>
            <p className="text-sm font-medium text-foreground">{camera.label}</p>
            <p className="text-xs text-muted-foreground">{camera.sublabel}</p>
          </div>
          <button
            onClick={openFullscreen}
            title="Mărește"
            className="h-7 w-7 rounded-md border border-border bg-background hover:bg-muted flex items-center justify-center text-muted-foreground hover:text-foreground transition-colors"
          >
            <Maximize2 className="h-3.5 w-3.5" />
          </button>
        </div>

        {/* Preview */}
        <LivePreview
          camera={camera.id}
          fps={5}
          label={camera.label}
        />
      </div>

      {fullscreen && (
        <FullscreenModal
          camera={camera.id}
          label={`${camera.label} — ${camera.sublabel}`}
          onClose={closeFullscreen}
        />
      )}
    </>
  );
}

/** Secțiunea principală adăugată în pagina Admin */
export function AdminLiveSection() {
  return (
    <section className="rounded-xl border bg-card p-5 space-y-4">
      {/* Header secțiune */}
      <div className="flex items-center gap-2">
        <div className="h-2 w-2 rounded-full bg-red-500 animate-pulse" />
        <h2 className="text-sm font-semibold text-foreground">
          Stand 1 — Supraveghere Live
        </h2>
      </div>

      {/* Grid camere */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
        {CAMERAS.map((cam) => (
          <CameraCard key={cam.id} camera={cam} />
        ))}
      </div>
    </section>
  );
}
