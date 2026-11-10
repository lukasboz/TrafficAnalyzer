import Link from "next/link";

export default function ConfigurationNotice({ detail }: { detail: string }) {
  return <main className="signin-shell"><section className="signin-card"><div className="signin-brand">flowstate<span>.</span></div><h1>Connect your workspace</h1><p role="alert">{detail}</p><p>Configure ANALYSIS_URL, ANALYSIS_KEY, and DASHBOARD_PASSWORD in your deployment environment, then redeploy.</p><Link className="button primary" href="/">Check configuration again</Link></section></main>;
}
