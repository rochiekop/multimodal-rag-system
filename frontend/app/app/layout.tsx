"use client"

import type { ReactNode } from "react"

import { AppSidebar } from "@/components/app-sidebar"
import { CollectionSelectionProvider } from "@/components/chat/collection-selection"
import { MeGate } from "@/components/me-gate"
import {
  SidebarInset,
  SidebarProvider,
  SidebarTrigger,
} from "@/components/ui/sidebar"

export default function AppLayout({ children }: { children: ReactNode }) {
  return (
    <MeGate>
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
    </MeGate>
  )
}
