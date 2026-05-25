import { serverFetch } from "./client";

export async function getConfig(): Promise<Record<string, string>> {
  const res = await serverFetch("/api/config");
  if (!res.ok) throw new Error("Failed to load config");
  const data = await res.json();
  return data.config || {};
}

export async function saveConfig(values: Record<string, string>): Promise<{ ok: boolean; message?: string }> {
  const res = await fetch("/api/config/save", {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(values),
  });
  const data = await res.json();
  return { ok: res.ok, message: data.message || data.detail };
}
