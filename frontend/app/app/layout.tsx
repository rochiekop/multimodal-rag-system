"use client"

import { useQuery } from "@tanstack/react-query"
import { useRouter } from "next/navigation"
import { useEffect, type ReactNode } from "react"

import { AppSidebar } from "@/components/app-sidebar"
import {
  SidebarInset,
  SidebarProvider,
  SidebarTrigger,
} from "@/components/ui/sidebar"
import { api } from "@/lib/api"

export default function AppLayout({ children }: { children: ReactNode }) {
  const router = useRouter()
  const { data: me } = useQuery({ queryKey: ["me"], queryFn: api.me })
  useEffect(() => {
    if (me?.must_change_password) router.replace("/change-password")
  }, [me, router])

  return (
    <SidebarProvider>
      <AppSidebar />
      <SidebarInset className="flex h-svh flex-col">
        <header className="flex h-12 shrink-0 items-center gap-2 border-b px-3">
          <SidebarTrigger />
        </header>
        <div className="min-h-0 flex-1">{children}</div>
      </SidebarInset>
    </SidebarProvider>
  )
}
