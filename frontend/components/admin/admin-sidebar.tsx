"use client"

import { useQuery } from "@tanstack/react-query"
import {
  BellIcon,
  CpuIcon,
  FileTextIcon,
  FlaskConicalIcon,
  FolderLockIcon,
  InboxIcon,
  LayoutDashboardIcon,
  ScrollTextIcon,
  SettingsIcon,
  ShieldIcon,
  UsersIcon,
  type LucideIcon,
} from "lucide-react"
import Link from "next/link"
import { usePathname } from "next/navigation"

import { BrandMark } from "@/components/branding"
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuBadge,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarRail,
} from "@/components/ui/sidebar"
import { UserMenu } from "@/components/user-menu"
import { adminApi } from "@/lib/admin-api"
import { api } from "@/lib/api"
import { useBranding } from "@/lib/branding"
import { isSuperAdmin } from "@/lib/roles"

interface NavItem {
  title: string
  href: string
  icon: LucideIcon
  superAdmin?: boolean
}

export const ADMIN_NAV: NavItem[] = [
  { title: "Dashboard", href: "/admin", icon: LayoutDashboardIcon },
  { title: "Documents", href: "/admin/documents", icon: FileTextIcon },
  {
    title: "Collections & access",
    href: "/admin/collections",
    icon: FolderLockIcon,
  },
  { title: "Users & groups", href: "/admin/users", icon: UsersIcon },
  { title: "Evaluation", href: "/admin/evaluation", icon: FlaskConicalIcon },
  { title: "Review queue", href: "/admin/review", icon: InboxIcon },
  { title: "Audit log", href: "/admin/audit", icon: ScrollTextIcon },
  { title: "Notifications", href: "/admin/notifications", icon: BellIcon },
  {
    title: "Models & RAG config",
    href: "/admin/models",
    icon: CpuIcon,
    superAdmin: true,
  },
  {
    title: "Guardrails",
    href: "/admin/guardrails",
    icon: ShieldIcon,
    superAdmin: true,
  },
  {
    title: "Settings",
    href: "/admin/settings",
    icon: SettingsIcon,
    superAdmin: true,
  },
]

const isActive = (pathname: string, href: string) =>
  href === "/admin"
    ? pathname === href
    : pathname === href || pathname.startsWith(`${href}/`)

export function AdminSidebar() {
  const pathname = usePathname() ?? ""
  const { appName } = useBranding()
  const { data: me } = useQuery({ queryKey: ["me"], queryFn: api.me })
  const { data: unread } = useQuery({
    queryKey: ["admin", "notifications", "unread"],
    queryFn: () => adminApi.notifications(true),
    refetchInterval: 60_000,
  })
  const items = ADMIN_NAV.filter(
    (item) => !item.superAdmin || (me && isSuperAdmin(me))
  )
  return (
    <Sidebar>
      <SidebarHeader>
        <SidebarMenu>
          <SidebarMenuItem>
            <SidebarMenuButton size="lg" asChild>
              <Link href="/admin">
                <BrandMark />
                <span className="truncate font-medium">{appName}</span>
              </Link>
            </SidebarMenuButton>
          </SidebarMenuItem>
        </SidebarMenu>
      </SidebarHeader>
      <SidebarContent>
        <SidebarGroup>
          <SidebarGroupLabel>Admin console</SidebarGroupLabel>
          <SidebarGroupContent>
            <SidebarMenu>
              {items.map((item) => (
                <SidebarMenuItem key={item.href}>
                  <SidebarMenuButton
                    asChild
                    isActive={isActive(pathname, item.href)}
                  >
                    <Link href={item.href}>
                      <item.icon /> {item.title}
                    </Link>
                  </SidebarMenuButton>
                  {item.href === "/admin/notifications" &&
                    unread &&
                    unread.length > 0 && (
                      <SidebarMenuBadge aria-label={`${unread.length} unread`}>
                        {unread.length}
                      </SidebarMenuBadge>
                    )}
                </SidebarMenuItem>
              ))}
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>
      </SidebarContent>
      <SidebarFooter>
        <UserMenu />
      </SidebarFooter>
      <SidebarRail />
    </Sidebar>
  )
}
