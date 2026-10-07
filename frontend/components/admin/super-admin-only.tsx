"use client"

import { useQuery } from "@tanstack/react-query"
import type { ReactNode } from "react"

import { api } from "@/lib/api"
import { isSuperAdmin } from "@/lib/roles"

/** Renders children (and so runs their queries) only for super admins. */
export function SuperAdminOnly({ children }: { children: ReactNode }) {
  const { data: me } = useQuery({ queryKey: ["me"], queryFn: api.me })
  if (!me) return null
  if (!isSuperAdmin(me))
    return (
      <p className="text-sm text-muted-foreground">
        Only super admins can open this page.
      </p>
    )
  return <>{children}</>
}
