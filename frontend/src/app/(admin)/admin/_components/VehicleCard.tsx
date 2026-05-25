"use client";

import { PlateBadge } from "@/components/PlateBadge";
import { StatusPill } from "@/components/StatusPill";
import { Button } from "@/components/ui/button";
import type { Vehicle } from "@/lib/api/admin";
import { AlertTriangle, Camera, ChevronDown, ExternalLink, Loader2, Plus, Star, Trash2, Video } from "lucide-react";
import { useState } from "react";

/** Matches backend placeholder for unknown plate (U+2014 em dash). */
const EM_DASH = "\u2014";

/** True when portal must prompt for plate (missing or unknown from ALPR). */
function plateNeedsManualEntry(licensePlate: string): boolean {
  const t = licensePlate.trim();
  if (!t) return true;
  return t === EM_DASH;
}

/** Minimum alphanumeric length enforced client-side (aligned with backend). */
const MIN_PLATE_ALNUM = 4;
import { AlprGalleryModal } from "./AlprGalleryModal";
import { ResendSmsButton } from "./ResendSmsButton";

interface VehicleCardProps {
  vehicle: Vehicle;
  onDeleted?: (eventId: string) => void;
}

function smsVariant(status: string) {
  if (status === "sent") return "success";
  if (status === "mocked") return "warning";
  if (status === "failed") return "error";
  return "idle";
}

function smsLabel(status: string) {
  if (status === "sent") return "SMS trimis";
  if (status === "mocked") return "SMS simulat";
  if (status === "failed") return "SMS eșuat";
  return "SMS neprelucrat";
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

function StarRating({ rating }: { rating: number }) {
  return (
    <div className="flex items-center gap-0.5">
      {[1, 2, 3, 4, 5].map((i) => (
        <Star
          key={i}
          className={`h-3.5 w-3.5 ${i <= rating ? "fill-amber-400 text-amber-400" : "text-muted-foreground/30"}`}
        />
      ))}
      <span className="ml-1 text-xs text-muted-foreground">{rating}/5</span>
    </div>
  );
}

/** Format seconds as "Xm YYs" or "YYs" when below 1 minute. */
function formatDuration(seconds: number): string {
  const total = Math.round(seconds);
  if (total < 60) return `${total}s`;
  const m = Math.floor(total / 60);
  const s = total % 60;
  return `${m}m ${s.toString().padStart(2, "0")}s`;
}

function VideoThumb({
  url,
  label,
  durationSeconds,
  expectedSeconds,
}: {
  url: string;
  label: string;
  durationSeconds?: number | null;
  expectedSeconds?: number;
}) {
  const [err, setErr] = useState(false);
  if (err) return null;
  const isShort =
    durationSeconds != null &&
    expectedSeconds != null &&
    durationSeconds < expectedSeconds * 0.9;
  return (
    <div className="space-y-1">
      <div className="flex items-center justify-between">
        <p className="text-xs text-muted-foreground font-medium uppercase tracking-wide">{label}</p>
        {durationSeconds != null && (
          <span
            className={`text-[10px] font-mono ${
              isShort ? "text-destructive font-semibold" : "text-muted-foreground"
            }`}
            title={
              expectedSeconds
                ? `Asteptat ~${formatDuration(expectedSeconds)}`
                : undefined
            }
          >
            {formatDuration(durationSeconds)}
            {isShort && expectedSeconds ? ` / ${formatDuration(expectedSeconds)}` : ""}
          </span>
        )}
      </div>
      <video
        src={url}
        className="w-full rounded-lg border bg-black aspect-video object-cover"
        controls
        preload="metadata"
        onError={() => setErr(true)}
      />
    </div>
  );
}

function FeedbackModal({ linkId }: { linkId: number }) {
  const [show, setShow] = useState(false);
  const [loading, setLoading] = useState(false);
  const [feedback, setFeedback] = useState<any>(null);
  const [error, setError] = useState("");

  async function loadFeedback() {
    setLoading(true);
    setError("");
    try {
      const res = await fetch(`/api/customer-links/${linkId}`);
      if (!res.ok) throw new Error("Nu s-a putut încărca feedback-ul");
      const data = await res.json();
      setFeedback(data.feedback || null);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Eroare necunoscută");
    } finally {
      setLoading(false);
    }
  }

  async function handleOpen() {
    setShow(true);
    if (!feedback) await loadFeedback();
  }

  return (
    <>
      <Button size="sm" variant="outline" className="h-7 gap-1.5 text-xs" onClick={handleOpen}>
        <Star className="h-3 w-3" />
        Vezi feedback
      </Button>

      {show && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4" onClick={() => setShow(false)}>
          <div className="w-full max-w-md rounded-xl border bg-card shadow-xl p-5 space-y-4" onClick={(e) => e.stopPropagation()}>
            <h3 className="font-semibold text-sm">Feedback client</h3>

            {loading ? (
              <div className="flex items-center justify-center py-8">
                <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
              </div>
            ) : error ? (
              <p className="text-xs text-destructive">{error}</p>
            ) : feedback ? (
              <div className="space-y-4">
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <p className="text-xs text-muted-foreground mb-1">Rating general</p>
                    <StarRating rating={feedback.rating_overall || 0} />
                  </div>
                  {feedback.rating_explanation != null && (
                    <div>
                      <p className="text-xs text-muted-foreground mb-1">Claritate expunere</p>
                      <StarRating rating={feedback.rating_explanation} />
                    </div>
                  )}
                </div>
                {feedback.free_text && (
                  <div>
                    <p className="text-xs text-muted-foreground mb-1">Observații</p>
                    <p className="text-sm bg-muted p-3 rounded-md">{feedback.free_text}</p>
                  </div>
                )}
                {feedback.submitted_at && (
                  <p className="text-xs text-muted-foreground text-right">
                    Trimis la {new Date(feedback.submitted_at).toLocaleString("ro-RO")}
                  </p>
                )}
              </div>
            ) : (
              <p className="text-sm text-muted-foreground">Nu există feedback înregistrat.</p>
            )}

            <div className="flex justify-end pt-1">
              <Button size="sm" variant="outline" onClick={() => setShow(false)}>Închide</Button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}

function CreatePortalModal({
  vehicle,
  onCreated,
}: {
  vehicle: Vehicle;
  onCreated: () => void;
}) {
  const [show, setShow] = useState(false);
  const needsManualPlate = plateNeedsManualEntry(vehicle.license_plate);
  const [manualPlate, setManualPlate] = useState("");
  const [ownerName, setOwnerName] = useState("");
  const [phone, setPhone] = useState("");
  const [mechanic, setMechanic] = useState("");
  const [sendSms, setSendSms] = useState(true);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const plateAlnumLen = manualPlate.replace(/[^A-Za-z0-9]/g, "").length;
  const plateOk = plateAlnumLen >= MIN_PLATE_ALNUM;

  function openModal() {
    setManualPlate(needsManualPlate ? "" : vehicle.license_plate);
    setError("");
    setShow(true);
  }

  async function submit() {
    setError("");
    setLoading(true);
    try {
      const res = await fetch("/api/customer-links", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({
          event_id: vehicle.event_id,
          license_plate: manualPlate.trim(),
          owner_name: ownerName,
          mechanic_name: mechanic,
          phone_number: phone,
          send_sms: sendSms,
        }),
      });
      const data = await res.json();
      if (!res.ok) {
        const msg =
          typeof data.detail === "string"
            ? data.detail
            : Array.isArray(data.detail)
              ? data.detail.map((x: { msg?: string }) => x.msg).filter(Boolean).join(" ")
              : "Eroare server";
        throw new Error(msg || "Eroare server");
      }
      setShow(false);
      onCreated();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Eroare necunoscută");
    } finally {
      setLoading(false);
    }
  }

  return (
    <>
      <Button size="sm" variant="outline" className="h-7 gap-1.5 text-xs" onClick={openModal}>
        <Plus className="h-3 w-3" />
        Creează portal
      </Button>

      {show && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4" onClick={() => setShow(false)}>
          <div className="w-full max-w-sm rounded-xl border bg-card shadow-xl p-5 space-y-4" onClick={(e) => e.stopPropagation()}>
            <h3 className="font-semibold text-sm">Creează portal</h3>
            <p className="text-xs text-muted-foreground">
              Eveniment: <span className="font-mono text-foreground">{vehicle.event_id}</span>
            </p>

            <div className="space-y-3">
              <div>
                <label className="text-xs text-muted-foreground block mb-1">Număr înmatriculare *</label>
                <input
                  value={manualPlate}
                  onChange={(e) => setManualPlate(e.target.value.toUpperCase())}
                  className="w-full h-8 rounded-md border border-input bg-background px-2.5 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-ring"
                  placeholder="ex. TM12ABC"
                  autoComplete="off"
                />
                {needsManualPlate && (
                  <p className="text-[10px] text-muted-foreground mt-1">
                    Nu s-a detectat plăcuță automat — completează manual înainte de a genera portalul.
                  </p>
                )}
              </div>
              <div>
                <label className="text-xs text-muted-foreground block mb-1">Proprietar *</label>
                <input
                  value={ownerName}
                  onChange={(e) => setOwnerName(e.target.value)}
                  className="w-full h-8 rounded-md border border-input bg-background px-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
                  placeholder="Nume complet"
                />
              </div>
              <div>
                <label className="text-xs text-muted-foreground block mb-1">Telefon *</label>
                <input
                  value={phone}
                  onChange={(e) => setPhone(e.target.value)}
                  className="w-full h-8 rounded-md border border-input bg-background px-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
                  placeholder="07XXXXXXXX"
                />
              </div>
              <div>
                <label className="text-xs text-muted-foreground block mb-1">Mecanic *</label>
                <input
                  value={mechanic}
                  onChange={(e) => setMechanic(e.target.value)}
                  className="w-full h-8 rounded-md border border-input bg-background px-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
                  placeholder="Nume mecanic"
                />
              </div>
              <label className="flex items-center gap-2 text-sm cursor-pointer select-none">
                <input
                  type="checkbox"
                  checked={sendSms}
                  onChange={(e) => setSendSms(e.target.checked)}
                  className="rounded"
                />
                Trimite SMS clientului
              </label>
            </div>

            {error && <p className="text-xs text-destructive">{error}</p>}

            <div className="flex gap-2 justify-end pt-1">
              <Button size="sm" variant="outline" onClick={() => setShow(false)} disabled={loading}>Anulează</Button>
              <Button
                size="sm"
                onClick={submit}
                disabled={
                  loading ||
                  !ownerName.trim() ||
                  !phone.trim() ||
                  !mechanic.trim() ||
                  !plateOk
                }
              >
                {loading ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : sendSms ? "Generează & trimite SMS" : "Generează portal"}
              </Button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}

export function VehicleCard({ vehicle, onDeleted }: VehicleCardProps) {
  const [open, setOpen] = useState(false);
  const [showAlprGallery, setShowAlprGallery] = useState(false);
  const [portalCreated, setPortalCreated] = useState(false);
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState("");
  const hasLink = vehicle.has_link || portalCreated;

  async function handleDelete() {
    setDeleting(true);
    setDeleteError("");
    try {
      const res = await fetch(`/api/admin/events/${encodeURIComponent(vehicle.event_id)}`, {
        method: "DELETE",
        credentials: "include",
      });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data.detail || "Eroare la ștergere");
      }
      setShowDeleteConfirm(false);
      onDeleted?.(vehicle.event_id);
    } catch (e: unknown) {
      setDeleteError(e instanceof Error ? e.message : "Eroare necunoscută");
    } finally {
      setDeleting(false);
    }
  }
  const hasVideos = vehicle.video_cam1_url || vehicle.video_cam2_url;
  const alprSamples = vehicle.alpr_samples ?? [];
  const hasAlprGallery = alprSamples.length > 0;

  return (
    <div className="rounded-xl border bg-card shadow-sm overflow-hidden transition-shadow hover:shadow-md">
      {/* Header row — always visible */}
      <button
        onClick={() => setOpen(!open)}
        className="w-full flex items-center gap-3 px-4 py-3 text-left hover:bg-muted/30 transition-colors"
      >
        {/* Snapshot thumbnail */}
        {vehicle.snapshot_url && (
          <img
            src={vehicle.snapshot_url}
            alt="snapshot"
            className="h-10 w-16 rounded object-cover shrink-0 border"
          />
        )}

        {/* Plate */}
        <PlateBadge plate={vehicle.license_plate} size="sm" />

        {/* ALPR confidence */}
        {vehicle.alpr_confidence != null && (
          <span className="hidden md:inline-flex items-center rounded px-1.5 py-0.5 text-[10px] font-mono bg-green-500/10 text-green-600 border border-green-500/20 shrink-0">
            {vehicle.alpr_confidence.toFixed(0)}%
          </span>
        )}

        {/* ALPR gallery button */}
        {hasAlprGallery && (
          <button
            onClick={(e) => {
              e.stopPropagation();
              setShowAlprGallery(true);
            }}
            className="hidden md:inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[10px] bg-blue-500/10 text-blue-600 border border-blue-500/20 hover:bg-blue-500/20 transition-colors shrink-0"
            title="Deschide galeria ALPR"
          >
            <Camera className="h-3 w-3" />
            {alprSamples.length} snapshot-uri
          </button>
        )}

        {/* Owner */}
        <span className="flex-1 min-w-0 text-sm font-medium text-foreground truncate">
          {vehicle.owner_name || <span className="text-muted-foreground italic">fără portal</span>}
        </span>

        {/* Video icon if videos exist */}
        {hasVideos && <Video className="h-3.5 w-3.5 text-muted-foreground shrink-0" />}

        {/* Badges */}
        <div className="hidden sm:flex items-center gap-2 shrink-0">
          {(vehicle.recording_warnings?.length ?? 0) > 0 && (
            <span
              className="inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[10px] font-medium bg-destructive/10 text-destructive border border-destructive/30"
              title={vehicle.recording_warnings?.join(" • ")}
            >
              <AlertTriangle className="h-3 w-3" />
              Inregistrare incompleta
            </span>
          )}
          <StatusPill variant={smsVariant(vehicle.sms_status)} label={smsLabel(vehicle.sms_status)} />
          {vehicle.has_feedback && (
            <StatusPill variant="success" label="Feedback ✓" />
          )}
        </div>

        {/* Date */}
        <span className="hidden lg:block text-xs text-muted-foreground shrink-0">
          {formatDate(vehicle.created_at)}
        </span>

        {/* Chevron */}
        <ChevronDown
          className={`h-4 w-4 text-muted-foreground shrink-0 transition-transform ${open ? "rotate-180" : ""}`}
        />
      </button>

      {/* Expanded body */}
      {open && (
        <div className="border-t px-4 py-4 space-y-4 bg-muted/20">
          {(vehicle.recording_warnings?.length ?? 0) > 0 && (
            <div className="rounded-lg border border-destructive/30 bg-destructive/5 p-3">
              <div className="flex items-center gap-2 text-destructive font-semibold text-xs mb-1">
                <AlertTriangle className="h-3.5 w-3.5" />
                Inregistrare incompleta
              </div>
              <ul className="text-xs text-destructive/90 space-y-0.5 list-disc list-inside">
                {vehicle.recording_warnings!.map((w, i) => (
                  <li key={i}>{w}</li>
                ))}
              </ul>
            </div>
          )}
          {/* Videos */}
          {hasVideos && (
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              {vehicle.snapshot_url && (
                <div className="space-y-1">
                  <p className="text-xs text-muted-foreground font-medium uppercase tracking-wide">Snapshot ALPR</p>
                  <img src={vehicle.snapshot_url} alt="ALPR snapshot" className="w-full rounded-lg border object-cover" />
                </div>
              )}
              {vehicle.video_cam1_url && (
                <VideoThumb
                  url={vehicle.video_cam1_url}
                  label="Camera 1"
                  durationSeconds={vehicle.video_cam1_duration_seconds}
                  expectedSeconds={vehicle.expected_duration_seconds}
                />
              )}
              {vehicle.video_cam2_url && (
                <VideoThumb
                  url={vehicle.video_cam2_url}
                  label="Camera 2 (PTZ)"
                  durationSeconds={vehicle.video_cam2_duration_seconds}
                  expectedSeconds={vehicle.expected_duration_seconds}
                />
              )}
            </div>
          )}

          {/* Portal info */}
          {vehicle.has_link && (
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4 text-sm">
              {vehicle.owner_name && (
                <div>
                  <p className="text-xs text-muted-foreground mb-0.5">Proprietar</p>
                  <p className="font-medium">{vehicle.owner_name}</p>
                </div>
              )}
              {vehicle.phone_number_masked && (
                <div>
                  <p className="text-xs text-muted-foreground mb-0.5">Telefon</p>
                  <p className="font-mono text-sm">{vehicle.phone_number_masked}</p>
                </div>
              )}
              {vehicle.mechanic_name && (
                <div>
                  <p className="text-xs text-muted-foreground mb-0.5">Mecanic</p>
                  <p className="font-medium">{vehicle.mechanic_name}</p>
                </div>
              )}
              <div>
                <p className="text-xs text-muted-foreground mb-0.5">Data</p>
                <p>{formatDate(vehicle.created_at)}</p>
              </div>
              <div>
                <p className="text-xs text-muted-foreground mb-0.5">Status SMS</p>
                <StatusPill variant={smsVariant(vehicle.sms_status)} label={smsLabel(vehicle.sms_status)} />
              </div>
              {vehicle.has_feedback && vehicle.rating_overall && (
                <div>
                  <p className="text-xs text-muted-foreground mb-0.5">Rating client</p>
                  <StarRating rating={vehicle.rating_overall} />
                </div>
              )}
            </div>
          )}

          {/* Actions */}
          <div className="flex flex-wrap items-center gap-3 pt-2 border-t">
            {!hasLink && (
              <CreatePortalModal vehicle={vehicle} onCreated={() => setPortalCreated(true)} />
            )}

            {hasLink && vehicle.id > 0 && (
              <ResendSmsButton linkId={vehicle.id} smsStatus={vehicle.sms_status} />
            )}

            {vehicle.public_url && (
              <a
                href={vehicle.public_url}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium border border-border bg-background hover:bg-muted transition-colors"
              >
                <ExternalLink className="h-3.5 w-3.5" />
                Deschide portal client
              </a>
            )}

            {vehicle.has_feedback && vehicle.id > 0 && (
              <FeedbackModal linkId={vehicle.id} />
            )}

            {portalCreated && !vehicle.public_url && (
              <span className="text-xs text-green-600 font-medium">Portal creat! Reîncarcă pagina pentru link.</span>
            )}

            {/* Delete */}
            <Button
              size="sm"
              variant="outline"
              className="h-7 gap-1.5 text-xs text-destructive border-destructive/40 hover:bg-destructive/10 ml-auto"
              onClick={() => { setDeleteError(""); setShowDeleteConfirm(true); }}
            >
              <Trash2 className="h-3 w-3" />
              Șterge
            </Button>
          </div>
        </div>
      )}

      {/* ALPR gallery modal */}
      {showAlprGallery && (
        <AlprGalleryModal
          plate={vehicle.license_plate}
          method={vehicle.alpr_method}
          samplesWithPlate={vehicle.alpr_samples_with_plate ?? alprSamples.length}
          samplesTotal={vehicle.alpr_samples_total ?? alprSamples.length}
          samples={alprSamples}
          onClose={() => setShowAlprGallery(false)}
        />
      )}

      {/* Delete confirmation modal */}
      {showDeleteConfirm && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4"
          onClick={() => !deleting && setShowDeleteConfirm(false)}
        >
          <div
            className="w-full max-w-sm rounded-xl border bg-card shadow-xl p-5 space-y-4"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center gap-3">
              <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-destructive/10">
                <Trash2 className="h-4 w-4 text-destructive" />
              </div>
              <div>
                <h3 className="font-semibold text-sm">Confirmare ștergere</h3>
                <p className="text-xs text-muted-foreground mt-0.5">
                  Eveniment: <span className="font-mono text-foreground">{vehicle.event_id}</span>
                </p>
              </div>
            </div>

            <p className="text-sm text-muted-foreground">
              Toate fișierele (înregistrări, snapshot-uri) și portalul asociat vor fi șterse definitiv. Această acțiune nu poate fi anulată.
            </p>

            {deleteError && <p className="text-xs text-destructive">{deleteError}</p>}

            <div className="flex gap-2 justify-end pt-1">
              <Button
                size="sm"
                variant="outline"
                onClick={() => setShowDeleteConfirm(false)}
                disabled={deleting}
              >
                Anulează
              </Button>
              <Button
                size="sm"
                variant="destructive"
                onClick={handleDelete}
                disabled={deleting}
              >
                {deleting ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : "Șterge definitiv"}
              </Button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
