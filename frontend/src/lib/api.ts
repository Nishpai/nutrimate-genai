const TOKEN_KEY = "nutrimate.token"

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

export const tokenStore = {
  get: () => localStorage.getItem(TOKEN_KEY),
  set: (t: string) => localStorage.setItem(TOKEN_KEY, t),
  clear: () => localStorage.removeItem(TOKEN_KEY),
}

function message(body: unknown, status: number): string {
  if (body && typeof body === "object" && "detail" in body) {
    const d = (body as { detail: unknown }).detail
    if (typeof d === "string") return d
    if (Array.isArray(d) && d.length) {
      const first = d[0] as { msg?: string; loc?: string[] }
      const field = first.loc?.slice(-1)[0]
      return field ? `${field}: ${first.msg}` : first.msg ?? "Invalid input"
    }
  }
  return status >= 500 ? "Server error, please try again" : `Request failed (${status})`
}

export async function api<T = unknown>(path: string, opts: { method?: string; body?: unknown; form?: FormData } = {}): Promise<T> {
  const headers: Record<string, string> = {}
  const token = tokenStore.get()
  if (token) headers.Authorization = `Bearer ${token}`
  let body: BodyInit | undefined
  if (opts.form) body = opts.form
  else if (opts.body !== undefined) {
    headers["Content-Type"] = "application/json"
    body = JSON.stringify(opts.body)
  }
  let res: Response
  try {
    res = await fetch(path, { method: opts.method ?? (body ? "POST" : "GET"), headers, body })
  } catch {
    throw new ApiError(0, "Cannot reach the NutriMate server. Is the backend running?")
  }
  const text = await res.text()
  const data = text ? JSON.parse(text) : null
  if (!res.ok) {
    if (res.status === 401 && token) {
      tokenStore.clear()
      window.dispatchEvent(new Event("nutrimate:logout"))
    }
    throw new ApiError(res.status, message(data, res.status))
  }
  return data as T
}
