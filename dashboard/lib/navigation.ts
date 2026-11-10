// Workspace sign-in may return only to the dashboard on this origin.
export function dashboardReturnTo(value: unknown): string {
  if (typeof value !== "string" || !value.startsWith("/") || value.startsWith("//")) return "/";
  try {
    const url = new URL(value, "https://flowstate.invalid");
    return url.origin === "https://flowstate.invalid" && url.pathname === "/"
      ? url.pathname + url.search + url.hash : "/";
  } catch { return "/"; }
}

export function signInPath(returnTo: string): string {
  const destination = dashboardReturnTo(returnTo);
  return destination === "/" ? "/login" : `/login?next=${encodeURIComponent(destination)}`;
}
