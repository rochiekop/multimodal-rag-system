"use client"

import { SquarePenIcon } from "lucide-react"
import Link from "next/link"
import { usePathname } from "next/navigation"

import { BrandMark } from "@/components/branding"
import { ConversationList } from "@/components/conversation-list"
import { UserMenu } from "@/components/user-menu"
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarRail,
} from "@/components/ui/sidebar"
import { useBranding } from "@/lib/branding"

export function AppSidebar() {
  const pathname = usePathname()
  const { appName } = useBranding()
  const activeId = pathname.startsWith("/app/c/")
    ? pathname.split("/")[3]
    : undefined
  return (
    <Sidebar>
      <SidebarHeader>
        <SidebarMenu>
          <SidebarMenuItem>
            <SidebarMenuButton size="lg" asChild>
              <Link href="/app">
                <BrandMark />
                <span className="truncate font-medium">{appName}</span>
              </Link>
            </SidebarMenuButton>
          </SidebarMenuItem>
          <SidebarMenuItem>
            <SidebarMenuButton asChild>
              <Link href="/app">
                <SquarePenIcon /> New chat
              </Link>
            </SidebarMenuButton>
          </SidebarMenuItem>
        </SidebarMenu>
      </SidebarHeader>
      <SidebarContent>
        <ConversationList activeId={activeId} />
      </SidebarContent>
      <SidebarFooter>
        <UserMenu />
      </SidebarFooter>
      <SidebarRail />
    </Sidebar>
  )
}
