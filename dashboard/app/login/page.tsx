import { redirect } from "next/navigation";
import SignInForm from "@/components/sign-in-form";
import { signedIn } from "@/lib/server/session";
import { ConfigurationError } from "@/lib/server/config";
import ConfigurationNotice from "@/components/configuration-notice";
import { dashboardReturnTo } from "@/lib/navigation";

export const dynamic = "force-dynamic";
export default async function Login({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const returnTo = dashboardReturnTo((await searchParams).next);
  try { if (await signedIn()) redirect(returnTo); }
  catch (error) {
    if (!(error instanceof ConfigurationError)) throw error;
    return <ConfigurationNotice detail={error.message} />;
  }
  return <main className="signin-shell"><section className="signin-card"><div className="signin-brand">flowstate<span>.</span></div><div className="eyebrow">TRAFFIC OBSERVATORY</div><h1>Welcome to your workspace.</h1><p>Sign in to explore cameras, measure traffic, and manage scheduled observations.</p><SignInForm returnTo={returnTo} /><div className="signin-note">Your workspace password is set by the site owner.</div></section><div className="signin-decoration" aria-hidden="true"><span /><span /><span /><span /></div></main>;
}
