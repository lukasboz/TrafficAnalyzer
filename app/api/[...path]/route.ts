import { env } from "cloudflare:workers";

type Runtime = { ANALYSIS_URL?: string; ANALYSIS_KEY?: string };

async function proxy(request: Request, context: { params: Promise<{ path: string[] }> }) {
  const { path } = await context.params;
  const runtime = env as unknown as Runtime;
  const base = runtime.ANALYSIS_URL || process.env.ANALYSIS_URL || "http://127.0.0.1:8000";
  const key = runtime.ANALYSIS_KEY || process.env.ANALYSIS_KEY || "";
  const incoming = new URL(request.url);
  const target = new URL("/api/" + path.map(encodeURIComponent).join("/"), base);
  target.search = incoming.search;
  const headers = new Headers();
  headers.set("x-flowstate-key", key);
  if (request.headers.has("content-type")) headers.set("content-type", request.headers.get("content-type")!);
  try {
    const response = await fetch(target, {
      method: request.method, headers,
      body: ["GET", "HEAD"].includes(request.method) ? undefined : await request.arrayBuffer(),
      signal: AbortSignal.timeout(path[0] === "providers" || path.at(-1) === "clip" ? 90000 : 30000), redirect: "manual",
    });
    if (response.status >= 300 && response.status < 400) throw new Error("The configured service redirected unexpectedly.");
    const outgoing = new Headers({ "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff" });
    for (const name of ["content-type", "content-disposition", "content-length"]) if (response.headers.has(name)) outgoing.set(name, response.headers.get(name)!);
    return new Response(response.body, { status: response.status, headers: outgoing });
  } catch (error) {
    console.error("Analysis service connection failed:", error instanceof Error ? error.message : "Unknown error");
    return Response.json({ detail: "The analysis service is offline. Start the Flowstate service and retry." }, { status: 503 });
  }
}
export const GET = proxy;
export const POST = proxy;
export const PATCH = proxy;
export const DELETE = proxy;
