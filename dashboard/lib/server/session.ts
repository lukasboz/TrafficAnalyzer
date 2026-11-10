import { createHash, createHmac, randomBytes, timingSafeEqual } from "node:crypto";
import { cookies } from "next/headers";
import { workspaceConfiguration } from "./config";

export const SESSION_COOKIE = "flowstate_session";
export const SESSION_SECONDS = 7 * 24 * 60 * 60;

function signingKey() {
  const configuration = workspaceConfiguration();
  return createHmac("sha256", configuration.key).update("flowstate-session-v1:" + configuration.password).digest();
}
export function passwordMatches(input: string, expected: string) {
  return timingSafeEqual(createHash("sha256").update(input).digest(), createHash("sha256").update(expected).digest());
}
export function createSession(now = Date.now()) {
  const payload = Math.floor(now / 1000 + SESSION_SECONDS) + "." + randomBytes(24).toString("base64url");
  return payload + "." + createHmac("sha256", signingKey()).update(payload).digest("base64url");
}
export function validSession(token: string | undefined, now = Date.now()) {
  if (!token || token.length > 256) return false;
  const parts = token.split(".");
  if (parts.length !== 3 || !/^\d{10}$/.test(parts[0]) || !/^[A-Za-z0-9_-]{32}$/.test(parts[1]) || !/^[A-Za-z0-9_-]{43}$/.test(parts[2])) return false;
  const expires = Number(parts[0]);
  const seconds = Math.floor(now / 1000);
  if (expires <= seconds || expires > seconds + SESSION_SECONDS + 60) return false;
  const expected = createHmac("sha256", signingKey()).update(parts[0] + "." + parts[1]).digest("base64url");
  // Compare canonical encoding too: permissive base64 decoders ignore unused
  // trailing bits, which otherwise accept some modified signature strings.
  return timingSafeEqual(Buffer.from(parts[2], "ascii"), Buffer.from(expected, "ascii"));
}
export async function signedIn() {
  const config = workspaceConfiguration();
  return !config.signInEnabled || validSession((await cookies()).get(SESSION_COOKIE)?.value);
}
export function sameOrigin(request: Request) {
  // Next.js can construct an internal localhost URL even when the browser uses
  // 127.0.0.1 or a deployment domain. Match the browser Origin to the actual Host.
  const origin = request.headers.get("origin");
  const host = request.headers.get("host") || new URL(request.url).host;
  const protocol = sessionOptions().secure ? "https:" : new URL(request.url).protocol;
  return origin === protocol + "//" + host;
}
export function sessionOptions() {
  const local = process.env.VERCEL !== "1" && process.env.FLOWSTATE_LOCAL === "1" && workspaceConfiguration().loopback;
  return { httpOnly: true, sameSite: "lax" as const, secure: process.env.NODE_ENV === "production" && !local, path: "/", maxAge: SESSION_SECONDS };
}
