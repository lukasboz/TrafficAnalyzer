import { redirect } from "next/navigation";
import ConfigurationNotice from "@/components/configuration-notice";
import TrafficDashboard from "@/components/traffic-dashboard";
import { ConfigurationError, workspaceConfiguration } from "@/lib/server/config";
import { signedIn } from "@/lib/server/session";
import { signInPath } from "@/lib/navigation";

export const dynamic = "force-dynamic";

export default async function Home({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  let config;
  try { config = workspaceConfiguration(); }
  catch (error) {
    if (!(error instanceof ConfigurationError)) throw error;
    return <ConfigurationNotice detail={error.message} />;
  }
  if (!(await signedIn())) {
    const query = new URLSearchParams();
    for (const [key, value] of Object.entries(await searchParams)) {
      for (const item of Array.isArray(value) ? value : value === undefined ? [] : [value]) query.append(key, item);
    }
    redirect(signInPath(query.size ? `/?${query}` : "/"));
  }
  return <TrafficDashboard signInEnabled={config.signInEnabled} />;
}
