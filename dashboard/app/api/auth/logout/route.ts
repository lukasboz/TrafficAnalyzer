import { NextResponse } from "next/server";
import { sameOrigin, SESSION_COOKIE, sessionOptions } from "@/lib/server/session";
export async function POST(request: Request) {
  if (!sameOrigin(request)) return NextResponse.json({ detail: "This request must come from your workspace." }, { status: 403 });
  const response = NextResponse.json({ ok: true }, { headers: { "Cache-Control": "no-store" } });
  response.cookies.set(SESSION_COOKIE, "", { ...sessionOptions(), maxAge: 0 });
  return response;
}
