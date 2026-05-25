"use client";

import { Button } from "@/components/ui/button";
import type { AlprSample } from "@/lib/api/admin";
import { X, ZoomIn } from "lucide-react";
import { useState } from "react";

interface AlprGalleryModalProps {
  plate: string;
  method?: string;
  samplesWithPlate: number;
  samplesTotal: number;
  samples: AlprSample[];
  onClose: () => void;
}

function formatCapturedAt(iso?: string) {
  if (!iso) return "";
  try {
    return new Date(iso).toLocaleTimeString("ro-RO", {
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    });
  } catch {
    return iso;
  }
}

function methodLabel(method?: string) {
  if (method === "frequency") return "frecvență";
  if (method === "confidence") return "confidence";
  return method ?? "—";
}

export function AlprGalleryModal({
  plate,
  method,
  samplesWithPlate,
  samplesTotal,
  samples,
  onClose,
}: AlprGalleryModalProps) {
  const [preview, setPreview] = useState<AlprSample | null>(null);

  // Find the sample with the highest confidence to mark as "winner".
  const winnerFilename = samples.reduce<string | null>((best, s) => {
    if (best === null) return s.filename;
    const bestSample = samples.find((x) => x.filename === best);
    return (bestSample?.confidence ?? 0) >= s.confidence ? best : s.filename;
  }, null);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4" onClick={onClose}>
      {/* Main modal */}
      <div
        className="relative w-full max-w-3xl max-h-[90vh] flex flex-col bg-background rounded-xl border shadow-2xl overflow-hidden"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-start justify-between px-5 py-4 border-b shrink-0">
          <div>
            <h2 className="text-lg font-semibold">ALPR — Galerie snapshot-uri</h2>
            <p className="text-sm text-muted-foreground mt-0.5">
              Cea mai probabilă plăcuță:{" "}
              <span className="font-mono font-bold text-foreground">{plate}</span>
            </p>
            <p className="text-xs text-muted-foreground mt-0.5">
              Metodă:{" "}
              <span className="font-medium">{methodLabel(method)}</span>
              {" · "}
              {samplesWithPlate} din {samplesTotal} snapshot-uri cu plăcuță detectată
            </p>
          </div>
          <Button variant="ghost" size="icon" onClick={onClose} className="shrink-0 -mr-1 -mt-1">
            <X className="h-4 w-4" />
          </Button>
        </div>

        {/* Grid */}
        <div className="overflow-y-auto p-4">
          {samples.length === 0 ? (
            <p className="text-center text-sm text-muted-foreground py-8">
              Niciun snapshot cu plăcuță detectată.
            </p>
          ) : (
            <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 gap-3">
              {samples.map((s) => {
                const isWinner = s.filename === winnerFilename;
                return (
                  <button
                    key={s.filename}
                    onClick={() => setPreview(s)}
                    className={`relative group rounded-lg border overflow-hidden text-left transition-shadow hover:shadow-md focus:outline-none focus-visible:ring-2 focus-visible:ring-ring ${
                      isWinner
                        ? "border-yellow-400 ring-2 ring-yellow-400/50"
                        : "border-border"
                    }`}
                    title="Click pentru previzualizare"
                  >
                    {/* Thumbnail */}
                    <div className="relative aspect-video bg-muted">
                      <img
                        src={s.url}
                        alt={s.plate}
                        className="absolute inset-0 w-full h-full object-cover"
                        loading="lazy"
                      />
                      {/* Hover overlay */}
                      <div className="absolute inset-0 flex items-center justify-center bg-black/40 opacity-0 group-hover:opacity-100 transition-opacity">
                        <ZoomIn className="h-5 w-5 text-white" />
                      </div>
                      {isWinner && (
                        <span className="absolute top-1 right-1 bg-yellow-400 text-yellow-900 text-[9px] font-bold px-1.5 py-0.5 rounded-full leading-none">
                          ★ ALES
                        </span>
                      )}
                    </div>

                    {/* Info */}
                    <div className="px-2 py-1.5 bg-card space-y-0.5">
                      <p className="font-mono text-xs font-semibold truncate text-foreground">
                        {s.plate}
                      </p>
                      <p className="text-[10px] text-muted-foreground">
                        {s.confidence.toFixed(1)}% · {formatCapturedAt(s.captured_at)}
                      </p>
                    </div>
                  </button>
                );
              })}
            </div>
          )}
        </div>
      </div>

      {/* Full-size preview overlay */}
      {preview && (
        <div
          className="fixed inset-0 z-[60] flex items-center justify-center bg-black/90 p-4"
          onClick={() => setPreview(null)}
        >
          <div className="relative max-w-4xl w-full" onClick={(e) => e.stopPropagation()}>
            <Button
              variant="ghost"
              size="icon"
              className="absolute -top-2 -right-2 z-10 bg-background/80 hover:bg-background"
              onClick={() => setPreview(null)}
            >
              <X className="h-4 w-4" />
            </Button>
            <img
              src={preview.url}
              alt={preview.plate}
              className="w-full rounded-lg max-h-[80vh] object-contain"
            />
            <p className="text-center text-sm text-white/80 mt-2">
              <span className="font-mono font-bold">{preview.plate}</span>{" "}
              — {preview.confidence.toFixed(1)}%
              {preview.captured_at && ` · ${formatCapturedAt(preview.captured_at)}`}
            </p>
          </div>
        </div>
      )}
    </div>
  );
}
