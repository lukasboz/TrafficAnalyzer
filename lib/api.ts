export async function api<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch("/api" + path, { cache: "no-store", ...options, headers: { "Content-Type": "application/json", ...options?.headers } });
  if (!response.ok) {
    const body = await response.json().catch(() => ({})) as { detail?: string | { msg: string }[] };
    const detail = body.detail;
    throw new Error(Array.isArray(detail) ? detail.map((e: { msg: string }) => e.msg).join(" · ") : detail || "The request could not be completed.");
  }
  return response.json();
}
export const write = (method: string, body?: unknown): RequestInit => ({ method, body: body === undefined ? undefined : JSON.stringify(body) });
