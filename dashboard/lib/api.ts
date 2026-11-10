import { signInPath } from "./navigation";

export async function api<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch("/api" + path, { cache: "no-store", ...options, headers: { "Content-Type": "application/json", ...options?.headers } });
  if (!response.ok) {
    const body = await response.json().catch(() => ({})) as { detail?: string | { msg: string }[]; code?: string };
    if (body.code === "SIGN_IN_REQUIRED") window.location.assign(signInPath(window.location.pathname + window.location.search + window.location.hash));
    const detail = body.detail;
    throw new Error(Array.isArray(detail) ? detail.map((e: { msg: string }) => e.msg).join(" · ") : detail || "The request could not be completed.");
  }
  return response.json();
}
export const write = (method: string, body?: unknown): RequestInit => ({ method, body: body === undefined ? undefined : JSON.stringify(body) });

export async function cameraCatalog(): Promise<import("./types").Camera[]> {
  const cameras = new Map<string, import("./types").Camera>();
  let offset = 0;
  while (true) {
    const page = await api<{ items: import("./types").Camera[]; total: number }>(`/cameras?limit=4000&offset=${offset}`);
    for (const camera of page.items) cameras.set(camera.id, camera);
    offset += page.items.length;
    if (offset >= page.total) break;
    if (!page.items.length) throw new Error("The camera directory changed while loading. Please refresh.");
  }
  return [...cameras.values()];
}

