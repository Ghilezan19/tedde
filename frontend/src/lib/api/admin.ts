import { serverFetch } from "./client";

export interface AdminStats {
  today_events: number;
  sms_sent_today: number;
  feedback_today: number;
  avg_rating: number | null;
  tokens_remaining: number;
}

/** A single ALPR snapshot that produced a detected plate. */
export interface AlprSample {
  filename: string;
  url: string;
  plate: string;
  confidence: number;
  captured_at?: string;
}

export interface Vehicle {
  id: number;
  event_id: string;
  license_plate: string;
  owner_name: string;
  phone_number_masked: string;
  mechanic_name?: string;
  sms_status: "sent" | "mocked" | "failed" | "pending";
  has_feedback: boolean;
  rating_overall?: number;
  created_at: string;
  sent_at?: string;
  snapshot_url?: string;
  video_cam1_url?: string;
  video_cam2_url?: string;
  public_url?: string;
  expires_at?: string;
  alpr_confidence?: number;
  /** Aggregation method used to pick the winning plate ("frequency" | "confidence" | "none"). */
  alpr_method?: string;
  /** Snapshots that had a plate detected (populated by multi-shot loop). */
  alpr_samples?: AlprSample[];
  /** Total snapshots taken during the recording (including blanks). */
  alpr_samples_total?: number;
  /** Number of snapshots that had at least one plate detected. */
  alpr_samples_with_plate?: number;
  /** Camera 1 actual recorded duration in seconds (from ffprobe), null if unknown. */
  video_cam1_duration_seconds?: number | null;
  /** Camera 2 actual recorded duration in seconds (from ffprobe), null if unknown. */
  video_cam2_duration_seconds?: number | null;
  /** Configured target duration for the recording (for comparison). */
  expected_duration_seconds?: number;
  /** Romanian-language warnings about missing or truncated recordings. */
  recording_warnings?: string[];
  has_link?: boolean;
}

export interface VehiclesResponse {
  vehicles: Vehicle[];
  total: number;
  page: number;
  page_size: number;
  pages: number;
  filter: string;
  days: number;
  search: string;
}

export async function getAdminStats(): Promise<AdminStats> {
  const res = await serverFetch("/api/admin/stats");
  if (!res.ok) throw new Error("Failed to fetch admin stats");
  return res.json();
}

export async function getVehicles(params: {
  filter?: string;
  days?: number;
  search?: string;
  page?: number;
  page_size?: number;
}): Promise<VehiclesResponse> {
  const query = new URLSearchParams();
  if (params.filter) query.set("filter", params.filter);
  if (params.days) query.set("days", String(params.days));
  if (params.search) query.set("search", params.search);
  if (params.page) query.set("page", String(params.page));
  if (params.page_size) query.set("page_size", String(params.page_size));

  const res = await serverFetch(`/api/admin/events-list?${query}`);
  if (!res.ok) throw new Error("Failed to fetch events");
  return res.json();
}
