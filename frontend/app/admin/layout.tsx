"use client"

import type { ReactNode } from "react"

import { AdminSidebar } from "@/components/admin/admin-sidebar"
import { MeGate } from "@/components/me-gate"
import {
  SidebarInset,
  SidebarProvider,
  SidebarTrigger,
} from "@/components/ui/sidebar"
import { isAdmin } from "@/lib/roles"

export default function AdminLayout({ children }: { children: ReactNode }) {
  return (
    <MeGate allow={isAdmin}>
      <SidebarProvider>
        <AdminSidebar />
        <SidebarInset className="flex min-h-svh flex-col">
          <header className="flex h-12 shrink-0 items-center gap-2 border-b px-3">
            <SidebarTrigger />
            <span className="text-sm text-muted-foreground">Admin console</span>
          </header>
          <div className="flex-1 p-4 md:p-6">{children}</div>
        </SidebarInset>
      </SidebarProvider>
    </MeGate>
  )
}
