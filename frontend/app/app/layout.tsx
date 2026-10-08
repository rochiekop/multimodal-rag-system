"use client"

import { useQuery } from "@tanstack/react-query"
import { useRouter } from "next/navigation"
import { useEffect, type ReactNode } from "react"

import { AppSidebar } from "@/components/app-sidebar"
import { CollectionSelectionProvider } from "@/components/chat/collection-selection"
import { Button } from "@/components/ui/button"
import {
  SidebarInset,
  SidebarProvider,
  SidebarTrigger,
} from "@/components/ui/sidebar"
import { api } from "@/lib/api"

export default function AppLayout({ children }: { children: ReactNode }) {
  const router = useRouter()
  const {
    data: me,
    isError,
    isFetching,
    refetch,
  } = useQuery({ queryKey: ["me"], queryFn: api.me })
  useEffect(() => {
    if (me?.must_change_password) router.replace("/change-password")
  }, [me, router])

  if (!me || me.must_change_password) {
    if (me) return null
    // A 401 is handled globally (sign-out); anything else gets a way to try again.
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

  return (
    <CollectionSelectionProvider>
      <SidebarProvider>
        <AppSidebar />
        <SidebarInset className="flex h-svh flex-col">
          <header className="flex h-12 shrink-0 items-center gap-2 border-b px-3">
            <SidebarTrigger />
          </header>
          <div className="min-h-0 flex-1">{children}</div>
        </SidebarInset>
      </SidebarProvider>
    </CollectionSelectionProvider>
  )
}
