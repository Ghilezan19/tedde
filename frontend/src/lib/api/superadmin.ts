import { serverFetch } from "./client";

export interface TokensInfo {
  tokens_remaining: number;
  monthly_processed: number;
  total_processed: number;
  month: string;
}

export interface TokenHistoryEntry {
  id: number;
  kind: "consume" | "topup" | "adjust";
  delta: number;
  balance_after: number;
  license_plate?: string;
  note?: string;
  created_at: string;
}

export interface HealthCheck {
  checks: Record<string, { ok: boolean; label: string; detail?: string }>;
  uptime_seconds?: number;
  disk_percent?: number;
  mem_percent?: number;
}

export interface EventsByDay {
  days: Array<{
    date: string;
    events: Array<{
      event_id: string;
      license_plate: string;
      recorded_at: string;
      sms_status?: string;
      has_feedback: boolean;
    }>;
  }>;
}

export interface CleanupConfig {
  cleanup_days: number;
  auto_cleanup_enabled: boolean;
}

export async function getSuperAdminTokens(): Promise<TokensInfo> {
  const res = await serverFetch("/api/superadmin/tokens");
  if (!res.ok) throw new Error("Failed to fetch tokens");
  return res.json();
}

export async function getTokenHistory(limit = 100): Promise<TokenHistoryEntry[]> {
  const res = await serverFetch(`/api/superadmin/tokens/history?limit=${limit}`);
  if (!res.ok) throw new Error("Failed to fetch token history");
  const data = await res.json();
  const raw = data.items ?? data.history ?? data;
  return Array.isArray(raw) ? raw : [];
}

const HEALTH_LABELS: Record<string, string> = {
  ffmpeg: "ffmpeg",
  camera1_rtsp: "Camera 1 RTSP",
  camera2_rtsp: "Camera 2 RTSP",
  camera2_http: "Camera 2 HTTP",
  snapshots_dir: "Director snapshots",
  recordings_dir: "Director înregistrări",
  events_dir: "Director evenimente",
  data_dir: "Director date",
};

function normalizeHealthJson(data: Record<string, unknown>): HealthCheck {
  const inner = (data.health as Record<string, unknown> | undefined) ?? data;
  const checks: HealthCheck["checks"] = {};
  for (const [k, v] of Object.entries(inner)) {
    if (k === "overall" || k === "started_at") continue;
    if (v && typeof v === "object" && v !== null && "ok" in v) {
      const p = v as { ok: boolean; detail?: string };
      checks[k] = {
        ok: Boolean(p.ok),
        label: HEALTH_LABELS[k] ?? k.replace(/_/g, " "),
        detail: typeof p.detail === "string" ? p.detail : undefined,
      };
    }
  }
  return { checks };
}

export async function getHealth(): Promise<HealthCheck> {
  const res = await serverFetch("/api/superadmin/health");
  if (!res.ok) throw new Error("Failed to fetch health");
  const data = (await res.json()) as Record<string, unknown>;
  if (data.checks && typeof data.checks === "object") {
    return data as unknown as HealthCheck;
  }
  return normalizeHealthJson(data);
}

export async function getEventsByDay(): Promise<EventsByDay> {
  const res = await serverFetch("/api/superadmin/events-by-day");
  if (!res.ok) throw new Error("Failed to fetch events by day");
  const data = (await res.json()) as Record<string, unknown>;
  const rawDays = data.days;
  if (!Array.isArray(rawDays)) {
    return { days: [] };
  }
  const days = rawDays.map((d: Record<string, unknown>) => {
    const date = String(d.date ?? d.day ?? "");
    const rawEvents = Array.isArray(d.events) ? d.events : [];
    const events = rawEvents.map((ev: Record<string, unknown>) => ({
      event_id: String(ev.event_id ?? ""),
      license_plate: String(ev.license_plate ?? ev.plate ?? "—"),
      recorded_at: String(ev.recorded_at ?? ev.time ?? ""),
      sms_status: typeof ev.sms_status === "string" ? ev.sms_status : undefined,
      has_feedback: Boolean(ev.has_feedback ?? ev.feedback_done),
    }));
    return { date, events };
  });
  return { days };
}

export async function getCleanupConfig(): Promise<CleanupConfig> {
  const res = await serverFetch("/api/superadmin/cleanup-config-get");
  if (!res.ok) throw new Error("Failed to fetch cleanup config");
  return res.json();
}

export async function getCleanupLog(): Promise<string> {
  const res = await serverFetch("/api/superadmin/cleanup-log");
  if (!res.ok) return "";
  const data = (await res.json()) as Record<string, unknown>;
  const log = data.log;
  if (typeof log === "string") return log;
  if (log != null && typeof log === "object") {
    try {
      return JSON.stringify(log, null, 2);
    } catch {
      return "";
    }
  }
  const msg = data.message;
  return typeof msg === "string" ? msg : "";
}
