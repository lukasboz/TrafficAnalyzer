import { ConfigurationError, workspaceConfiguration } from "@/lib/server/config";
import { sameOrigin, signedIn } from "@/lib/server/session";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";
export const maxDuration = 120;

const endpoints = new Set(["health", "cameras", "live", "runs", "schedules", "providers", "reports", "export.csv"]);
const failure = (detail: string, code: string, status: number) => Response.json({ detail, code }, { status, headers: { "Cache-Control": "no-store" } });

async function proxy(request: Request, context: { params: Promise<{ path: string[] }> }) {
  const { path } = await context.params;
  if (!endpoints.has(path[0]) || path.some(part => !part || part === "." || part === ".." || part.includes("/") || part.includes("\\"))) return failure("This endpoint does not exist.", "NOT_FOUND", 404);
  try {
    const config = workspaceConfiguration();
    if (!(await signedIn())) return failure("Sign in to your workspace to continue.", "SIGN_IN_REQUIRED", 401);
    if (!["GET", "HEAD"].includes(request.method) && !sameOrigin(request)) return failure("This request must come from your workspace.", "INVALID_ORIGIN", 403);
    const target = new URL("/api/" + path.map(encodeURIComponent).join("/"), config.url);
    target.search = new URL(request.url).search;
    const headers = new Headers({ "x-flowstate-key": config.key });
    for (const name of ["content-type", "range", "if-range"]) if (request.headers.has(name)) headers.set(name, request.headers.get(name)!);
    const timeout = path[0] === "providers" || ["clip", "mjpeg"].includes(path.at(-1) || "") ? 90000 : 30000;
    const response = await fetch(target, {
      method: request.method, headers, cache: "no-store", redirect: "manual",
      body: ["GET", "HEAD"].includes(request.method) ? undefined : await request.arrayBuffer(),
      signal: AbortSignal.any([request.signal, AbortSignal.timeout(timeout)]),
    });
    if (response.status === 401 || response.status === 403) {
      await response.body?.cancel();
      return failure("The analysis service rejected its key. Match ANALYSIS_KEY with the backend's FLOWSTATE_API_KEY, then redeploy.", "BACKEND_KEY_REJECTED", 502);
    }
    if (response.status >= 300 && response.status < 400) {
      await response.body?.cancel();
      return failure("The analysis service redirected unexpectedly. Check ANALYSIS_URL points directly to its HTTPS origin.", "BACKEND_REDIRECTED", 502);
    }
    const outgoing = new Headers({ "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff" });
    for (const name of ["content-type", "content-disposition", "accept-ranges", "content-range", "x-source-timestamp"]) if (response.headers.has(name)) outgoing.set(name, response.headers.get(name)!);
    // Keep large camera responses streaming instead of buffering a Vercel function payload.
    return new Response(response.body, { status: response.status, headers: outgoing });
  } catch (error) {
    if (error instanceof ConfigurationError) return failure(error.message, error.code, 503);
    if (error instanceof Error && ["TimeoutError", "AbortError"].includes(error.name)) {
      return failure("The analysis service took too long to respond. Check its health and retry.", "BACKEND_TIMEOUT", 504);
    }
    console.error("Analysis service connection failed:", error instanceof Error ? error.name : "Unknown error");
    return failure("The analysis service is unreachable. Check that the backend is running and ANALYSIS_URL is its permanent HTTPS address.", "BACKEND_UNREACHABLE", 503);
  }
}
export const GET = proxy;
export const HEAD = proxy;
export const POST = proxy;
export const PATCH = proxy;
export const DELETE = proxy;
