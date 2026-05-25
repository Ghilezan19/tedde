import { serverFetch } from "@/lib/api/client";
import { SystemGalleryClient } from "./_client";

export const metadata = { title: "Sistem & Galerie — Configure" };

async function getData() {
  const [sysInfo, events, recordings] = await Promise.allSettled([
    serverFetch("/api/sys/info").then((r) => r.json()),
    serverFetch("/api/events").then((r) => r.json()),
    serverFetch("/api/recordings").then((r) => r.json()),
  ]);
  const eventsData = events.status === "fulfilled" ? events.value : null;
  const recordingsData = recordings.status === "fulfilled" ? recordings.value : null;
  return {
    sysInfo: sysInfo.status === "fulfilled" ? sysInfo.value : null,
    events: Array.isArray(eventsData) ? eventsData : (eventsData?.events ?? []),
    recordings: Array.isArray(recordingsData) ? recordingsData : (recordingsData?.files ?? recordingsData?.recordings ?? []),
  };
}

export default async function SystemGalleryPage() {
  const data = await getData();
  return <SystemGalleryClient {...data} />;
}
