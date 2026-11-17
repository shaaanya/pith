/**
 * The only module that talks to the network. Same-origin; auth is the HttpOnly cookie the server
 * sets when the page is opened with ?token=… (no token handling in JS).
 */
import type { z } from "zod";

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

export async function request<S extends z.ZodType>(
  schema: S,
  method: "GET" | "POST" | "PATCH" | "DELETE",
  path: string,
  body?: unknown,
  signal?: AbortSignal,
): Promise<z.infer<S>> {
  const init: RequestInit = { method, signal, credentials: "same-origin" };
  if (body instanceof FormData) init.body = body;
  else if (body !== undefined) {
    init.headers = { "Content-Type": "application/json" };
    init.body = JSON.stringify(body);
  }
  let res: Response;
  try {
    res = await fetch(path, init);
  } catch (e) {
    if ((e as Error).name === "AbortError") throw e;
    throw new ApiError(0, "Pith is not responding. Is it still running?");
  }
  const text = await res.text();
  let data: unknown = null;
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    /* non-JSON body */
  }
  if (!res.ok) {
    const msg = (data as { error?: string } | null)?.error;
    if (res.status === 401) throw new ApiError(401, "Not signed in. Open the address printed by `pith run` again.");
    throw new ApiError(res.status, msg ?? `Request failed (${res.status})`);
  }
  const parsed = schema.safeParse(data);
  if (!parsed.success) {
    console.error("API contract mismatch", path, parsed.error.issues);
    throw new ApiError(500, "Pith sent a response this page does not understand.");
  }
  return parsed.data;
}

export const qs = (params: Record<string, string | number | null | undefined>) => {
  const u = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v !== null && v !== undefined && v !== "") u.set(k, String(v));
  const s = u.toString();
  return s ? `?${s}` : "";
};

export const blobUrl = (sha: string) => `/api/blob/${encodeURIComponent(sha)}`;
