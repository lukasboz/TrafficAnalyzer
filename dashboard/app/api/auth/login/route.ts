import { NextResponse } from "next/server";
import { ConfigurationError, workspaceConfiguration } from "@/lib/server/config";
import { createSession, passwordMatches, sameOrigin, SESSION_COOKIE, sessionOptions } from "@/lib/server/session";

export const runtime = "nodejs";
export async function POST(request: Request) {
  try {
    const config = workspaceConfiguration();
    if (!sameOrigin(request)) return NextResponse.json({ detail: "This request must come from your workspace." }, { status: 403 });
    if (!config.signInEnabled) return NextResponse.json({ ok: true });
    if (Number(request.headers.get("content-length")) > 2048) return NextResponse.json({ detail: "Invalid sign-in request." }, { status: 400 });
    const body = await request.json().catch(() => null);
    if (!body || typeof body.password !== "string" || body.password.length > 512 || !passwordMatches(body.password, config.password)) {
      return NextResponse.json({ detail: "That password is incorrect." }, { status: 401, headers: { "Cache-Control": "no-store" } });
    }
    const response = NextResponse.json({ ok: true }, { headers: { "Cache-Control": "no-store" } });
    response.cookies.set(SESSION_COOKIE, createSession(), sessionOptions());
    return response;
  } catch (error) {
    if (error instanceof ConfigurationError) return NextResponse.json({ detail: error.message, code: error.code }, { status: 503 });
    throw error;
  }
}
