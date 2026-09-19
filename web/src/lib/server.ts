// SPDX-License-Identifier: LicenseRef-SymonSaysLLC-Proprietary-1.0
// Copyright 2026 SymonSaysLLC
// SyMoNsAyLeaRn — SyMoNeuRaL, a subdivision of SymonSaysLLC. Terms: see LICENSE.
/* Server-side access to the gateway. Never imported by a client component.
 *
 * The credential is read here and nowhere else. It was previously re-implemented in
 * every page that needed it, which is how a rule like "the value never reaches the
 * browser" quietly stops being true: one copy forgets. One reader, one place.
 *
 * The `server-only` package would make that a build error. It is not in the dependency
 * set and the package manager cannot reach a registry from this host, so the guard is
 * enforced at runtime instead: the module throws if it is ever evaluated in a browser.
 * That is weaker than a build failure — it fires on first use rather than at compile
 * time — and it is recorded here rather than left silent. Adding `server-only` is the
 * proper fix the next time dependencies are resolved.
 */
if (typeof window !== "undefined") {
  throw new Error("lib/server is server-side only: it reads the gateway credential");
}

export const GATEWAY = process.env.SYM_GW_URL ?? "http://127.0.0.1:9001";

export interface Credential {
  value: string;
  /** First 16 hex characters of the sha256. Safe to render; the value never is. */
  fingerprint: string;
}

export async function credential(): Promise<Credential | null> {
  const { readFile } = await import("node:fs/promises");
  const { createHash } = await import("node:crypto");
  const { homedir } = await import("node:os");
  const path = process.env.SYM_GW_KEY_FILE ?? `${homedir()}/.config/symoneural/gateway-9001.key`;
  try {
    const value = (await readFile(path, "utf8")).trim();
    if (!value) return null;
    return { value, fingerprint: createHash("sha256").update(value).digest("hex").slice(0, 16) };
  } catch {
    return null;
  }
}

/** The dialect's own error envelope, so a failure says which failure it was. */
export function dialectError(status: number, type: string, message: string): Response {
  return new Response(JSON.stringify({ type: "error", error: { type, message } }), {
    status,
    headers: { "content-type": "application/json" },
  });
}

/** Forward to the gateway with the credential attached. Returns the raw Response so
 *  a streaming caller can hand the body straight back. */
export async function toGateway(path: string, init: RequestInit = {}): Promise<Response> {
  const key = await credential();
  if (!key) {
    return dialectError(
      503,
      "not_configured",
      "no credential at the configured key file; the deployment is unconfigured, not broken",
    );
  }
  const headers = new Headers(init.headers);
  headers.set("authorization", `Bearer ${key.value}`);
  headers.set("anthropic-version", "2023-06-01");
  if (init.body && !headers.has("content-type")) headers.set("content-type", "application/json");
  try {
    return await fetch(`${GATEWAY}${path}`, { ...init, headers, cache: "no-store" });
  } catch (cause) {
    return dialectError(502, "unreachable", `the gateway did not answer: ${String(cause)}`);
  }
}

/* ------------------------------------------------------------------ estate services
 *
 * The board, the weight store and the agents runtime each answer on their own port with
 * their own token. Same discipline as the gateway credential: the token is read here, from
 * the environment, and never travels to a browser or into a page's props.
 *
 * An unconfigured service answers 503 naming the variable it wants. That is passed through
 * rather than smoothed over — "unconfigured" and "broken" are different states, and a
 * surface that renders them identically teaches an operator to ignore both.
 */
export const SERVICES: Record<string, { url: string; tokenEnv: string | null }> = {
  board: { url: process.env.SYM_BOARD_URL ?? "http://127.0.0.1:8811", tokenEnv: "SYM_BOARD_TOKEN" },
  store: { url: process.env.SYM_STORE_URL ?? "http://127.0.0.1:8812", tokenEnv: "SYM_STORE_TOKEN" },
  agents: { url: process.env.SYM_AGENTS_URL ?? "http://127.0.0.1:8813", tokenEnv: "SYM_AGENTS_TOKEN" },
};

export interface ServiceResult {
  component: string;
  ok: boolean;
  status: number;
  /** Parsed body when the service answered with one, else null. */
  data: unknown;
  /** Why it did not answer, in words an operator can act on. */
  why: string | null;
}

export async function fromService(
  component: string,
  path: string,
  init: RequestInit = {},
): Promise<ServiceResult> {
  const svc = SERVICES[component];
  if (!svc) {
    return { component, ok: false, status: 0, data: null, why: `no such component: ${component}` };
  }
  const headers: Record<string, string> = { accept: "application/json" };
  if (svc.tokenEnv) {
    const token = (process.env[svc.tokenEnv] ?? "").trim();
    if (!token) {
      return {
        component,
        ok: false,
        status: 503,
        data: null,
        why: `${component} is unconfigured: ${svc.tokenEnv} is not set in this server's environment`,
      };
    }
    headers.authorization = `Bearer ${token}`;
  }
  try {
    const r = await fetch(`${svc.url}${path}`, {
      ...init,
      headers: { ...headers, ...(init.headers as Record<string, string> | undefined) },
      cache: "no-store",
      signal: AbortSignal.timeout(6000),
    });
    const body = await r.text();
    let data: unknown = null;
    try {
      data = body ? JSON.parse(body) : null;
    } catch {
      data = null;
    }
    const detail =
      data && typeof data === "object" && "detail" in (data as Record<string, unknown>)
        ? String((data as Record<string, unknown>).detail)
        : null;
    return { component, ok: r.ok, status: r.status, data, why: r.ok ? null : detail ?? `HTTP ${r.status}` };
  } catch (e) {
    return {
      component,
      ok: false,
      status: 0,
      data: null,
      why: `${svc.url} is not answering: ${e instanceof Error ? e.message : String(e)}`,
    };
  }
}
