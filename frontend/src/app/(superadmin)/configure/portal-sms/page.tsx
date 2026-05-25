import { getConfig } from "@/lib/api/config";
import { PortalSmsClient } from "./_client";

export const metadata = { title: "Portal & SMS — Configure" };

export default async function PortalSmsPage() {
  const config = await getConfig().catch(() => ({}));
  return <PortalSmsClient config={config} />;
}
