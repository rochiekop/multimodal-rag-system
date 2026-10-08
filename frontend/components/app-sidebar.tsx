"use client"

import { MessagesSquareIcon, SquarePenIcon } from "lucide-react"
import Link from "next/link"
import { usePathname } from "next/navigation"

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
import { APP_NAME } from "@/lib/config"

export function AppSidebar() {
  const pathname = usePathname()
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
                <div className="flex size-8 items-center justify-center rounded-lg bg-primary text-primary-foreground">
                  <MessagesSquareIcon className="size-4" />
                </div>
                <span className="truncate font-medium">{APP_NAME}</span>
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
