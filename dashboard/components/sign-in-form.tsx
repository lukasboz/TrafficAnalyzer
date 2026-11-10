"use client";
import { useState } from "react";
import { ArrowUpRight, Loader2, LockKeyhole } from "lucide-react";

export default function SignInForm({ returnTo = "/" }: { returnTo?: string }) {
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  return <form className="signin-form" onSubmit={async event => {
    event.preventDefault(); setLoading(true); setError("");
    try {
      const response = await fetch("/api/auth/login", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ password }) });
      const result = await response.json();
      if (!response.ok) throw new Error(result.detail || "Sign-in failed. Try again.");
      window.location.assign(returnTo);
    } catch (error) { setError((error as Error).message); setLoading(false); }
  }}>
    <label htmlFor="workspace-password">Workspace password</label>
    <div className="signin-input"><LockKeyhole size={18} /><input id="workspace-password" type="password" autoComplete="current-password" required minLength={12} maxLength={512} value={password} onChange={e => setPassword(e.target.value)} autoFocus /></div>
    {error && <p className="form-error" role="alert">{error}</p>}
    <button className="button primary" type="submit" disabled={loading}>{loading ? <Loader2 size={17} className="spin" /> : <ArrowUpRight size={17} />}{loading ? "Signing in…" : "Open workspace"}</button>
  </form>;
}
