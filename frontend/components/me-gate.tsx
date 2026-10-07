"use client"

import { useQuery } from "@tanstack/react-query"
import { useRouter } from "next/navigation"
import { useEffect, type ReactNode } from "react"

import { Button } from "@/components/ui/button"
import { api } from "@/lib/api"
import type { User } from "@/lib/types"

const anyone = () => true

/**
 * Renders children only for a signed-in user who passes `allow` (pass a module-level
 * function so its identity is stable). Forced password changes go to /change-password,
 * users who fail `allow` go to `redirectTo`. A 401 is handled globally (sign-out).
 */
export function MeGate({
  allow = anyone,
  redirectTo = "/app",
  children,
}: {
  allow?: (me: User) => boolean
  redirectTo?: string
  children: ReactNode
}) {
  const router = useRouter()
  const {
    data: me,
    isError,
    isFetching,
    refetch,
  } = useQuery({
    queryKey: ["me"],
    queryFn: api.me,
  })
  useEffect(() => {
    if (!me) return
    if (me.must_change_password) router.replace("/change-password")
    else if (!allow(me)) router.replace(redirectTo)
  }, [me, allow, redirectTo, router])

  if (me && !me.must_change_password && allow(me)) return <>{children}</>
  if (me) return null
  return (
    <div className="flex h-svh flex-col items-center justify-center gap-3 text-sm text-muted-foreground">
      {isError ? (
        <>
          <p>Can&apos;t reach the server.</p>
          <Button
            variant="outline"
            size="sm"
            disabled={isFetching}
            onClick={() => void refetch()}
          >
            Retry
          </Button>
        </>
      ) : (
        "Loading…"
      )}
    </div>
  )
}
