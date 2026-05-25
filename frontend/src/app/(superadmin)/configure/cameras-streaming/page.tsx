import { getConfig } from "@/lib/api/config";
import { CamerasStreamingClient } from "./_client";

export const metadata = { title: "Camere & Streaming — Configure" };

export default async function CamerasStreamingPage() {
  const config = await getConfig().catch(() => ({}));
  return <CamerasStreamingClient config={config} />;
}
