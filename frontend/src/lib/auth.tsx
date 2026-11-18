import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react"
import { useQueryClient } from "@tanstack/react-query"
import { api, tokenStore } from "./api"
import type { User } from "./types"

type AuthState = {
  user: User | null
  loading: boolean
  login: (email: string, password: string) => Promise<User>
  register: (full_name: string, email: string, password: string) => Promise<User>
  logout: () => void
  refresh: () => Promise<void>
}

const AuthContext = createContext<AuthState | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null)
  const [loading, setLoading] = useState(true)
  const qc = useQueryClient()

  const refresh = useCallback(async () => {
    if (!tokenStore.get()) {
      setUser(null)
      setLoading(false)
      return
    }
    try {
      setUser(await api<User>("/api/auth/me"))
    } catch {
      setUser(null)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    refresh()
    const onLogout = () => setUser(null)
    window.addEventListener("nutrimate:logout", onLogout)
    return () => window.removeEventListener("nutrimate:logout", onLogout)
  }, [refresh])

  const finish = (r: { token: string; user: User }) => {
    tokenStore.set(r.token)
    qc.clear()
    setUser(r.user)
    return r.user
  }

  const value: AuthState = {
    user,
    loading,
    refresh,
    login: async (email, password) => finish(await api("/api/auth/login", { body: { email, password } })),
    register: async (full_name, email, password) =>
      finish(await api("/api/auth/register", { body: { full_name, email, password } })),
    logout: () => {
      tokenStore.clear()
      qc.clear()
      setUser(null)
    },
  }
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

// eslint-disable-next-line react-refresh/only-export-components
export function useAuth() {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error("useAuth outside AuthProvider")
  return ctx
}
