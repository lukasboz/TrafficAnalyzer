export class ConfigurationError extends Error {
  constructor(public code: string, message: string) { super(message); }
}

export function backendConfiguration(environment: Record<string, string | undefined> = process.env) {
  const value = environment.ANALYSIS_URL?.trim();
  const key = environment.ANALYSIS_KEY?.trim();
  if (!value) throw new ConfigurationError("BACKEND_NOT_CONFIGURED", "Set ANALYSIS_URL to the permanent HTTPS address of your analysis service.");
  let url: URL;
  try { url = new URL(value); } catch { throw new ConfigurationError("BACKEND_NOT_CONFIGURED", "ANALYSIS_URL must be a valid HTTP or HTTPS origin."); }
  if (!["http:", "https:"].includes(url.protocol) || url.username || url.password || url.search || url.hash || url.pathname !== "/") {
    throw new ConfigurationError("BACKEND_NOT_CONFIGURED", "ANALYSIS_URL must be an HTTP or HTTPS origin without credentials, a path, or query parameters.");
  }
  if (!key || key.length < 32) throw new ConfigurationError("BACKEND_KEY_NOT_CONFIGURED", "Set ANALYSIS_KEY to the analysis service's FLOWSTATE_API_KEY (at least 32 characters).");
  const loopback = ["localhost", "127.0.0.1", "[::1]"].includes(url.hostname);
  const temporaryTunnel = url.hostname.endsWith(".trycloudflare.com") || url.hostname.endsWith(".loca.lt");
  if (environment.VERCEL === "1" && (url.protocol !== "https:" || loopback || temporaryTunnel)) {
    throw new ConfigurationError("BACKEND_NOT_PUBLIC", "Vercel requires a permanent public HTTPS analysis service. Localhost and temporary tunnels cannot be used.");
  }
  return { url, key, loopback };
}

export function workspaceConfiguration(environment: Record<string, string | undefined> = process.env) {
  const backend = backendConfiguration(environment);
  const password = environment.DASHBOARD_PASSWORD || "";
  const local = environment.VERCEL !== "1" && environment.FLOWSTATE_LOCAL === "1" && backend.loopback;
  const required = environment.VERCEL === "1" || (environment.NODE_ENV === "production" && !local);
  if ((required || password) && password.length < 12) {
    throw new ConfigurationError("WORKSPACE_NOT_CONFIGURED", "Set DASHBOARD_PASSWORD to a workspace password with at least 12 characters.");
  }
  return { ...backend, password, signInEnabled: Boolean(password) };
}
