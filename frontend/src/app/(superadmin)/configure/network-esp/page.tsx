import { getConfig } from "@/lib/api/config";
import { NetworkEspClient } from "./_client";

export const metadata = { title: "Rețea & ESP — Configure" };

export default async function NetworkEspPage() {
  const config = await getConfig().catch(() => ({}));
  return <NetworkEspClient config={config} />;
}
