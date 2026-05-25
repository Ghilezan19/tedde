"use client";

import { useState } from "react";
import { RefreshCw, Trash2, Search, ChevronDown, ChevronUp } from "lucide-react";
import { Button } from "@/components/ui/button";
import { StatusPill } from "@/components/StatusPill";

interface SysInfo {
  disk_total_gb?: number;
  disk_used_gb?: number;
  disk_free_gb?: number;
  ram_total_mb?: number;
  ram_used_mb?: number;
  uptime_s?: number;
  services?: Record<string, boolean>;
}

interface AlprPlate {
  plate: string;
  raw_plate?: string;
  confidence: number;
}

interface AlprData {
  enabled?: boolean;
  selected_plate?: string;
  selected_confidence?: number;
  plates?: AlprPlate[];
}

interface EventRecord {
  event_id: string;
  folder?: string;
  created?: number;
  created_at?: string;
  selected_plate?: string;
  snapshot_url?: string | null;
  alpr?: AlprData;
  videos?: {
    camera1?: string | null;
    camera2?: string | null;
  };
  // legacy fields (fallback)
  id?: string;
  plate?: string;
  cam1_url?: string;
  cam2_url?: string;
}

interface Recording {
  filename: string;
  size_mb?: number;
  sizeMB?: string;
  camera?: string;
  created_at?: string;
  url?: string;
}

interface Props {
  sysInfo: SysInfo | null;
  events: EventRecord[];
  recordings: Recording[];
}

function formatUptime(s: number) {
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  return `${h}h ${m}m`;
}

function formatBytes(mb: number) {
  return mb > 1024 ? `${(mb / 1024).toFixed(1)} GB` : `${mb.toFixed(0)} MB`;
}

function formatDate(iso?: string | null) {
  if (!iso) return "—";
  try {
    return new Intl.DateTimeFormat("ro-RO", {
      day: "2-digit", month: "2-digit", year: "numeric",
      hour: "2-digit", minute: "2-digit", second: "2-digit",
    }).format(new Date(iso));
  } catch {
    return iso;
  }
}

function ConfidenceBadge({ value }: { value: number }) {
  const color =
    value >= 90 ? "bg-emerald-500/15 text-emerald-600 border-emerald-500/30" :
    value >= 70 ? "bg-yellow-500/15 text-yellow-600 border-yellow-500/30" :
                  "bg-red-500/15 text-red-600 border-red-500/30";
  return (
    <span className={`inline-flex items-center rounded-full border px-2 py-0.5 text-xs font-medium ${color}`}>
      {value.toFixed(0)}%
    </span>
  );
}

function DiskBar({ used, total }: { used: number; total: number }) {
  const pct = total > 0 ? Math.round((used / total) * 100) : 0;
  const color = pct > 90 ? "bg-destructive" : pct > 70 ? "bg-yellow-500" : "bg-primary";
  return (
    <div className="space-y-1">
      <div className="flex justify-between text-xs text-muted-foreground">
        <span>{used.toFixed(1)} GB folosit</span>
        <span>{pct}%</span>
      </div>
      <div className="h-2 rounded-full bg-muted overflow-hidden">
        <div className={`h-full rounded-full ${color} transition-all`} style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}

function EventCard({
  event,
  onDelete,
  deleting,
}: {
  event: EventRecord;
  onDelete: (id: string) => void;
  deleting: boolean;
}) {
  const [showAlpr, setShowAlpr] = useState(false);
  const id = event.event_id || event.id || "";
  const plate = event.selected_plate || event.plate || event.alpr?.selected_plate || "NECUNOSCUT";
  const confidence = event.alpr?.selected_confidence;
  const plates = event.alpr?.plates ?? [];
  const cam1 = event.videos?.camera1 || event.cam1_url;
  const cam2 = event.videos?.camera2 || event.cam2_url;
  const snapshot = event.snapshot_url;
  const hasVideo = !!(cam1 || cam2);
  const isUnknown = plate === "UNKNOWN" || plate === "NECUNOSCUT" || !plate;

  return (
    <div className="rounded-xl border bg-card overflow-hidden">
      {/* Header */}
      <div className="flex items-start justify-between gap-3 px-4 pt-4 pb-3 border-b bg-muted/20">
        <div className="flex items-center gap-3 min-w-0">
          {/* Plate */}
          <div className={`inline-flex items-center rounded-lg border-2 px-3 py-1.5 font-mono text-base font-bold tracking-widest tabular-nums shrink-0 ${
            isUnknown
              ? "border-muted bg-muted/40 text-muted-foreground"
              : "border-foreground/20 bg-background"
          }`}>
            {isUnknown ? "—" : plate}
          </div>
          {confidence != null && <ConfidenceBadge value={confidence} />}
          {plates.length > 1 && (
            <button
              onClick={() => setShowAlpr((v) => !v)}
              className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground transition-colors"
            >
              {plates.length} variante
              {showAlpr ? <ChevronUp className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />}
            </button>
          )}
        </div>
        <div className="flex items-center gap-2 shrink-0">
          <span className="text-xs text-muted-foreground font-mono hidden sm:block">
            {formatDate(event.created_at)}
          </span>
          <Button
            variant="ghost"
            size="sm"
            onClick={() => onDelete(id)}
            disabled={deleting}
            className="h-7 w-7 p-0 text-destructive hover:bg-destructive/10"
          >
            {deleting ? <RefreshCw className="h-3.5 w-3.5 animate-spin" /> : <Trash2 className="h-3.5 w-3.5" />}
          </Button>
        </div>
      </div>

      {/* ALPR candidates dropdown */}
      {showAlpr && plates.length > 0 && (
        <div className="px-4 py-2 border-b bg-muted/10 flex flex-wrap gap-2">
          {plates.map((p, i) => (
            <div key={i} className="flex items-center gap-1.5 rounded-md border bg-background px-2 py-1">
              <span className="font-mono text-xs font-semibold">{p.plate}</span>
              <ConfidenceBadge value={p.confidence} />
            </div>
          ))}
        </div>
      )}

      {/* Timestamp on mobile */}
      <div className="sm:hidden px-4 py-1.5 text-xs text-muted-foreground font-mono border-b">
        {formatDate(event.created_at)}
      </div>

      {/* Content: snapshot + videos */}
      <div className="p-4">
        {!hasVideo && !snapshot && (
          <p className="text-xs text-muted-foreground italic">Niciun fișier video disponibil.</p>
        )}
        <div className={`grid gap-3 ${
          snapshot && hasVideo ? "grid-cols-1 sm:grid-cols-3" :
          hasVideo && cam1 && cam2 ? "grid-cols-1 sm:grid-cols-2" :
          "grid-cols-1"
        }`}>
          {/* Snapshot */}
          {snapshot && (
            <div className="space-y-1.5">
              <p className="text-xs font-medium text-muted-foreground uppercase tracking-wider">Snapshot ALPR</p>
              <a href={snapshot} target="_blank" rel="noopener noreferrer">
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img
                  src={snapshot}
                  alt="ALPR snapshot"
                  className="w-full rounded-lg border object-cover aspect-video bg-muted hover:opacity-90 transition-opacity cursor-zoom-in"
                />
              </a>
            </div>
          )}

          {/* Camera 1 */}
          {cam1 && (
            <div className="space-y-1.5">
              <p className="text-xs font-medium text-muted-foreground uppercase tracking-wider">Camera 1</p>
              {/* eslint-disable-next-line jsx-a11y/media-has-caption */}
              <video
                src={cam1}
                controls
                preload="metadata"
                className="w-full rounded-lg border aspect-video bg-black"
              />
            </div>
          )}

          {/* Camera 2 */}
          {cam2 && (
            <div className="space-y-1.5">
              <p className="text-xs font-medium text-muted-foreground uppercase tracking-wider">Camera 2</p>
              {/* eslint-disable-next-line jsx-a11y/media-has-caption */}
              <video
                src={cam2}
                controls
                preload="metadata"
                className="w-full rounded-lg border aspect-video bg-black"
              />
            </div>
          )}
        </div>

        {/* Event ID */}
        <p className="mt-3 text-[10px] text-muted-foreground/50 font-mono truncate">{id}</p>
      </div>
    </div>
  );
}

export function SystemGalleryClient({ sysInfo, events, recordings }: Props) {
  const [eventSearch, setEventSearch] = useState("");
  const [recSearch, setRecSearch] = useState("");
  const [deletingEvent, setDeletingEvent] = useState<string | null>(null);
  const [deletingRec, setDeletingRec] = useState<string | null>(null);
  const [localEvents, setLocalEvents] = useState<EventRecord[]>(Array.isArray(events) ? events : []);
  const [localRecs, setLocalRecs] = useState<Recording[]>(Array.isArray(recordings) ? recordings : []);

  const deleteEvent = async (id: string) => {
    if (!confirm("Ștergi evenimentul și toate fișierele asociate?")) return;
    setDeletingEvent(id);
    try {
      await fetch(`/api/events/${id}`, { method: "DELETE", credentials: "include" });
      setLocalEvents((prev) => prev.filter((e) => (e.event_id || e.id) !== id));
    } finally {
      setDeletingEvent(null);
    }
  };

  const deleteRecording = async (filename: string) => {
    if (!confirm("Ștergi înregistrarea?")) return;
    setDeletingRec(filename);
    try {
      await fetch(`/api/recordings/${encodeURIComponent(filename)}`, { method: "DELETE", credentials: "include" });
      setLocalRecs((prev) => prev.filter((r) => r.filename !== filename));
    } finally {
      setDeletingRec(null);
    }
  };

  const filteredEvents = localEvents.filter((e) => {
    if (!eventSearch) return true;
    const q = eventSearch.toLowerCase();
    const plate = (e.selected_plate || e.plate || e.alpr?.selected_plate || "").toLowerCase();
    const id = (e.event_id || e.id || "").toLowerCase();
    return plate.includes(q) || id.includes(q);
  });

  const filteredRecs = localRecs.filter((r) =>
    !recSearch || r.filename.toLowerCase().includes(recSearch.toLowerCase())
  );

  return (
    <div className="space-y-8 pb-20">
      <div>
        <h1 className="text-xl font-bold">Sistem & Galerie</h1>
        <p className="text-sm text-muted-foreground mt-1">Informații sistem, servicii și galerie video</p>
      </div>

      {/* System Info */}
      <section className="rounded-xl border bg-card p-5 space-y-4">
        <h2 className="text-sm font-semibold">💻 Informații sistem</h2>
        {sysInfo ? (
          <div className="space-y-4">
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
              {sysInfo.disk_total_gb != null && (
                <div>
                  <p className="text-xs text-muted-foreground">Disc total</p>
                  <p className="font-mono font-medium text-sm">{sysInfo.disk_total_gb.toFixed(1)} GB</p>
                </div>
              )}
              {sysInfo.disk_free_gb != null && (
                <div>
                  <p className="text-xs text-muted-foreground">Disc liber</p>
                  <p className="font-mono font-medium text-sm">{sysInfo.disk_free_gb.toFixed(1)} GB</p>
                </div>
              )}
              {sysInfo.ram_total_mb != null && sysInfo.ram_used_mb != null && (
                <div>
                  <p className="text-xs text-muted-foreground">RAM folosit</p>
                  <p className="font-mono font-medium text-sm">{formatBytes(sysInfo.ram_used_mb)} / {formatBytes(sysInfo.ram_total_mb)}</p>
                </div>
              )}
              {sysInfo.uptime_s != null && (
                <div>
                  <p className="text-xs text-muted-foreground">Uptime</p>
                  <p className="font-mono font-medium text-sm">{formatUptime(sysInfo.uptime_s)}</p>
                </div>
              )}
            </div>
            {sysInfo.disk_used_gb != null && sysInfo.disk_total_gb != null && (
              <DiskBar used={sysInfo.disk_used_gb} total={sysInfo.disk_total_gb} />
            )}
            {sysInfo.services && Object.keys(sysInfo.services).length > 0 && (
              <div className="space-y-2">
                <p className="text-xs font-medium text-muted-foreground uppercase tracking-wider">Servicii</p>
                <div className="flex flex-wrap gap-2">
                  {Object.entries(sysInfo.services).map(([name, ok]) => (
                    <StatusPill key={name} variant={ok ? "success" : "error"} label={name} />
                  ))}
                </div>
              </div>
            )}
          </div>
        ) : (
          <p className="text-sm text-muted-foreground">Informațiile de sistem nu sunt disponibile.</p>
        )}
      </section>

      {/* Events Gallery */}
      <section className="space-y-4">
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-base font-semibold">🎬 Galerie evenimente</h2>
            <p className="text-xs text-muted-foreground mt-0.5">{localEvents.length} evenimente totale</p>
          </div>
          <div className="relative">
            <Search className="absolute left-2.5 top-2 h-3.5 w-3.5 text-muted-foreground" />
            <input
              type="text"
              value={eventSearch}
              onChange={(e) => setEventSearch(e.target.value)}
              placeholder="Caută plăcuță / ID..."
              className="h-8 pl-8 pr-3 w-48 rounded-md border border-input bg-background text-xs focus:outline-none focus:ring-2 focus:ring-ring"
            />
          </div>
        </div>

        {filteredEvents.length === 0 ? (
          <div className="rounded-xl border bg-card p-8 text-center">
            <p className="text-sm text-muted-foreground">
              {eventSearch ? "Niciun eveniment găsit pentru căutarea dată." : "Nu există evenimente înregistrate."}
            </p>
          </div>
        ) : (
          <div className="space-y-4">
            {filteredEvents.map((event) => {
              const id = event.event_id || event.id || "";
              return (
                <EventCard
                  key={id}
                  event={event}
                  onDelete={deleteEvent}
                  deleting={deletingEvent === id}
                />
              );
            })}
          </div>
        )}
      </section>

      {/* Manual Recordings */}
      <section className="rounded-xl border bg-card p-5 space-y-4">
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-sm font-semibold">⏺ Înregistrări manuale</h2>
            <p className="text-xs text-muted-foreground mt-0.5">{localRecs.length} fișiere</p>
          </div>
          <div className="relative">
            <Search className="absolute left-2.5 top-2 h-3.5 w-3.5 text-muted-foreground" />
            <input
              type="text"
              value={recSearch}
              onChange={(e) => setRecSearch(e.target.value)}
              placeholder="Caută fișier..."
              className="h-8 pl-8 pr-3 w-40 rounded-md border border-input bg-background text-xs focus:outline-none focus:ring-2 focus:ring-ring"
            />
          </div>
        </div>

        {filteredRecs.length === 0 ? (
          <p className="text-sm text-muted-foreground">Nicio înregistrare găsită.</p>
        ) : (
          <div className="rounded-lg border overflow-hidden">
            <table className="w-full text-sm">
              <thead className="bg-muted/50 border-b">
                <tr>
                  <th className="px-4 py-2 text-left text-xs font-semibold text-muted-foreground">Fișier</th>
                  <th className="px-4 py-2 text-left text-xs font-semibold text-muted-foreground">Cameră</th>
                  <th className="px-4 py-2 text-left text-xs font-semibold text-muted-foreground">Mărime</th>
                  <th className="px-4 py-2 text-left text-xs font-semibold text-muted-foreground">Dată</th>
                  <th className="px-4 py-2 text-right text-xs font-semibold text-muted-foreground">Acțiuni</th>
                </tr>
              </thead>
              <tbody className="divide-y">
                {filteredRecs.map((rec) => (
                  <tr key={rec.filename} className="hover:bg-muted/30 transition-colors">
                    <td className="px-4 py-2.5 font-mono text-xs max-w-[200px] truncate">{rec.filename}</td>
                    <td className="px-4 py-2.5 text-xs text-muted-foreground">{rec.camera || "—"}</td>
                    <td className="px-4 py-2.5 text-xs text-muted-foreground">
                      {rec.size_mb != null ? formatBytes(rec.size_mb) : rec.sizeMB ? `${rec.sizeMB} MB` : "—"}
                    </td>
                    <td className="px-4 py-2.5 text-xs text-muted-foreground">{formatDate(rec.created_at)}</td>
                    <td className="px-4 py-2.5 text-right">
                      <div className="flex items-center justify-end gap-2">
                        {rec.url && (
                          <a href={rec.url} target="_blank" rel="noopener noreferrer" className="text-xs text-primary hover:underline">
                            Descarcă
                          </a>
                        )}
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => deleteRecording(rec.filename)}
                          disabled={deletingRec === rec.filename}
                          className="h-6 w-6 p-0 text-destructive hover:bg-destructive/10"
                        >
                          {deletingRec === rec.filename ? (
                            <RefreshCw className="h-3 w-3 animate-spin" />
                          ) : (
                            <Trash2 className="h-3 w-3" />
                          )}
                        </Button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {/* Remote Access */}
      <section className="rounded-xl border bg-card p-5 space-y-4">
        <h2 className="text-sm font-semibold">🌐 Acces la distanță</h2>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 text-sm">
          <div className="rounded-lg border bg-muted/30 p-3 space-y-1">
            <p className="text-xs text-muted-foreground uppercase tracking-wider font-medium">Stream MJPEG</p>
            <p className="font-mono text-xs">/api/stream?camera=1</p>
            <p className="font-mono text-xs">/api/stream?camera=2</p>
          </div>
          <div className="rounded-lg border bg-muted/30 p-3 space-y-1">
            <p className="text-xs text-muted-foreground uppercase tracking-wider font-medium">WebSocket Audio</p>
            <p className="font-mono text-xs">/ws/audio</p>
          </div>
          <div className="rounded-lg border bg-muted/30 p-3 space-y-1">
            <p className="text-xs text-muted-foreground uppercase tracking-wider font-medium">Înregistrări</p>
            <p className="font-mono text-xs">/recordings/&lt;filename&gt;</p>
          </div>
          <div className="rounded-lg border bg-muted/30 p-3 space-y-1">
            <p className="text-xs text-muted-foreground uppercase tracking-wider font-medium">Snapshots</p>
            <p className="font-mono text-xs">/snapshots/&lt;filename&gt;</p>
          </div>
        </div>
      </section>
    </div>
  );
}
