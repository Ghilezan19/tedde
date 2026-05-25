import { getConfig } from "@/lib/api/config";
import { AutomationClient } from "./_client";

export const metadata = { title: "Automatizare — Configure" };

export default async function AutomationPage() {
  const config = await getConfig().catch(() => ({}));
  return <AutomationClient config={config} />;
}
