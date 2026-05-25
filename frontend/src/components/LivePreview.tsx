"use client";

import { useState } from "react";
import { Loader2, RefreshCw, VideoOff } from "lucide-react";
import { useWorkflowRecordingBlock } from "@/hooks/useWorkflowRecordingBlock";

interface LivePreviewProps {
  camera: 1 | 2;
  fps?: number;
  online?: boolean;
  label?: string;
  /** When false, always attempt live MJPEG even if a workflow uses this camera (not recommended). */
  showWorkflowBlock?: boolean;
}

// In dev (or anywhere Next.js sits in front), MJPEG `multipart/x-mixed-replace`
// dies inside the rewrite proxy because it buffers the body. When
// `NEXT_PUBLIC_BACKEND_URL` is set, point the <img> straight at FastAPI so
// the long-lived stream is never proxied. In production behind nginx, leave
// the env var unset and use a relative URL (nginx streams correctly).
const STREAM_BASE = process.env.NEXT_PUBLIC_BACKEND_URL ?? "";

export function LivePreview({
  camera,
  fps = 8,
  online,
  label,
  showWorkflowBlock = true,
}: LivePreviewProps) {
  const [nonce, setNonce] = useState(0);
  const [errored, setErrored] = useState(false);
  const { blocked, elapsedSec, durationSec } = useWorkflowRecordingBlock(camera);

  const reload = () => {
    setErrored(false);
    setNonce((n) => n + 1);
  };

  const recordingBlocks = showWorkflowBlock && blocked;
  const progressText =
    recordingBlocks && elapsedSec != null && durationSec != null
      ? `${Math.floor(elapsedSec / 60)}m ${elapsedSec % 60}s din ~${Math.ceil(durationSec / 60)}m`
      : null;

  const showStream = online !== false && !errored && !recordingBlocks;
  const streamUrl = `${STREAM_BASE}/api/stream?camera=${camera}&fps=${fps}&_=${nonce}`;

  return (
    <div className="relative rounded-lg overflow-hidden bg-black aspect-video border">
      {recordingBlocks ? (
        <div className="w-full h-full flex flex-col items-center justify-center text-muted-foreground gap-2 px-4 text-center">
          <Loader2 className="h-10 w-10 opacity-60 animate-spin" />
          <p className="text-sm font-medium text-amber-600/95">Înregistrare în curs</p>
          <p className="text-xs max-w-[18rem]">
            Preview live este oprit pentru a nu întrerupe fluxul RTSP către cameră. Revine automat
            când sesiunea se termină.
          </p>
          {progressText && (
            <p className="text-[11px] font-mono text-muted-foreground">{progressText}</p>
          )}
        </div>
      ) : showStream ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img
          key={nonce}
          src={streamUrl}
          alt={label || `Live preview Camera ${camera}`}
          className="w-full h-full object-contain"
          onError={() => setErrored(true)}
        />
      ) : (
        <div className="w-full h-full flex flex-col items-center justify-center text-muted-foreground gap-2">
          <VideoOff className="h-10 w-10 opacity-40" />
          <p className="text-xs">
            {online === false ? "Camera offline" : "Stream indisponibil"}
          </p>
          <button
            onClick={reload}
            className="mt-1 inline-flex items-center gap-1 text-xs text-primary hover:underline"
          >
            <RefreshCw className="h-3 w-3" />
            Reîncearcă
          </button>
        </div>
      )}

      {/* LIVE badge */}
      {showStream && (
        <div className="absolute top-2 left-2 inline-flex items-center gap-1.5 rounded-full bg-black/60 backdrop-blur-sm px-2 py-0.5 text-[10px] font-semibold text-white">
          <span className="relative flex h-1.5 w-1.5">
            <span className="absolute inline-flex h-full w-full rounded-full bg-red-500 opacity-75 animate-ping" />
            <span className="relative inline-flex rounded-full h-1.5 w-1.5 bg-red-500" />
          </span>
          LIVE
        </div>
      )}

      {/* Label */}
      {label && (
        <div className="absolute top-2 right-2 rounded-full bg-black/60 backdrop-blur-sm px-2 py-0.5 text-[10px] font-semibold text-white">
          {label}
        </div>
      )}

      {/* Reload button over video */}
      {showStream && (
        <button
          onClick={reload}
          title="Reîncarcă stream"
          className="absolute bottom-2 right-2 h-7 w-7 rounded-full bg-black/60 backdrop-blur-sm hover:bg-black/80 flex items-center justify-center text-white transition-colors"
        >
          <RefreshCw className="h-3.5 w-3.5" />
        </button>
      )}
    </div>
  );
}
