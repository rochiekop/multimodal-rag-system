"use client"

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import type { ColumnDef } from "@tanstack/react-table"
import { MoreHorizontalIcon } from "lucide-react"
import { useState } from "react"
import { toast } from "sonner"

import { DataTable } from "@/components/admin/data-table"
import { PageHeader } from "@/components/admin/page-header"
import {
  CreateGroupDialog,
  CreateUserDialog,
  EditUserDialog,
  ResetPasswordDialog,
  ROLE_LABELS,
  userStatuses,
} from "@/components/admin/user-dialogs"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { adminApi } from "@/lib/admin-api"
import { api, ApiError } from "@/lib/api"
import { isSuperAdmin } from "@/lib/roles"
import type { AdminUser, Group, UserUpdate } from "@/lib/types"

export default function UsersPage() {
  const queryClient = useQueryClient()
  const { data: me } = useQuery({ queryKey: ["me"], queryFn: api.me })
  const users = useQuery({
    queryKey: ["admin", "users"],
    queryFn: adminApi.users,
  })
  const groups = useQuery({
    queryKey: ["admin", "groups"],
    queryFn: adminApi.groups,
  })
  const [creating, setCreating] = useState(false)
  const [creatingGroup, setCreatingGroup] = useState(false)
  const [editing, setEditing] = useState<AdminUser | null>(null)
  const [resetting, setResetting] = useState<AdminUser | null>(null)
  const canGrantSuperAdmin = !!me && isSuperAdmin(me)

  const update = useMutation({
    mutationFn: ({ id, body }: { id: string; body: UserUpdate }) =>
      adminApi.updateUser(id, body),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: ["admin", "users"] }),
    onError: (error) =>
      toast.error(
        error instanceof ApiError ? error.message : "Could not update the user"
      ),
  })

  const userColumns: ColumnDef<AdminUser>[] = [
    {
      accessorKey: "username",
      header: "User",
      enableSorting: true,
      cell: ({ row }) => (
        <div>
          <div className="font-medium">{row.original.username}</div>
          <div className="text-xs text-muted-foreground">
            {row.original.full_name}
          </div>
        </div>
      ),
    },
    {
      accessorKey: "role",
      header: "Role",
      cell: ({ row }) => ROLE_LABELS[row.original.role],
    },
    {
      id: "groups",
      header: "Groups",
      cell: ({ row }) =>
        row.original.groups.map((g) => g.name).join(", ") || "—",
    },
    {
      id: "status",
      header: "Status",
      cell: ({ row }) => (
        <div className="flex flex-wrap gap-1">
          {userStatuses(row.original).map((status) => (
            <Badge
              key={status}
              variant={status === "Active" ? "secondary" : "destructive"}
            >
              {status}
            </Badge>
          ))}
        </div>
      ),
    },
    {
      id: "actions",
      header: "",
      cell: ({ row }) => {
        const user = row.original
        const statuses = userStatuses(user)
        const locked =
          statuses.includes("Sign-in locked") ||
          statuses.includes("Chat locked")
        return (
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button
                size="icon"
                variant="ghost"
                aria-label={`Actions for ${user.username}`}
              >
                <MoreHorizontalIcon />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              <DropdownMenuItem onSelect={() => setEditing(user)}>
                Edit
              </DropdownMenuItem>
              <DropdownMenuItem onSelect={() => setResetting(user)}>
                Reset password
              </DropdownMenuItem>
              {locked && (
                <DropdownMenuItem
                  onSelect={() =>
                    update.mutate({ id: user.id, body: { unlock: true } })
                  }
                >
                  Unlock
                </DropdownMenuItem>
              )}
              {user.id !== me?.id && (
                <DropdownMenuItem
                  onSelect={() =>
                    update.mutate({
                      id: user.id,
                      body: { is_active: !user.is_active },
                    })
                  }
                >
                  {user.is_active ? "Suspend" : "Reactivate"}
                </DropdownMenuItem>
              )}
            </DropdownMenuContent>
          </DropdownMenu>
        )
      },
    },
  ]

  const groupColumns: ColumnDef<Group>[] = [
    { accessorKey: "name", header: "Name", enableSorting: true },
    { accessorKey: "description", header: "Description" },
  ]

  return (
    <>
      <PageHeader
        title="Users & groups"
        description="Accounts, roles and the groups that grant access to collections."
      />
      <Tabs defaultValue="users">
        <TabsList>
          <TabsTrigger value="users">Users</TabsTrigger>
          <TabsTrigger value="groups">Groups</TabsTrigger>
        </TabsList>
        <TabsContent value="users" className="grid gap-3">
          <div className="flex justify-end">
            <Button onClick={() => setCreating(true)}>New user</Button>
          </div>
          <DataTable
            columns={userColumns}
            data={users.data ?? []}
            isLoading={users.isLoading}
            getRowId={(u) => u.id}
          />
        </TabsContent>
        <TabsContent value="groups" className="grid gap-3">
          <div className="flex justify-end">
            <Button onClick={() => setCreatingGroup(true)}>New group</Button>
          </div>
          <DataTable
            columns={groupColumns}
            data={groups.data ?? []}
            isLoading={groups.isLoading}
            getRowId={(g) => g.id}
            empty="No groups yet."
          />
        </TabsContent>
      </Tabs>
      <CreateUserDialog
        open={creating}
        onOpenChange={setCreating}
        groups={groups.data ?? []}
        canGrantSuperAdmin={canGrantSuperAdmin}
      />
      <EditUserDialog
        user={editing}
        onOpenChange={(open) => !open && setEditing(null)}
        groups={groups.data ?? []}
        canGrantSuperAdmin={canGrantSuperAdmin}
      />
      <ResetPasswordDialog
        user={resetting}
        onOpenChange={(open) => !open && setResetting(null)}
      />
      <CreateGroupDialog open={creatingGroup} onOpenChange={setCreatingGroup} />
    </>
  )
}
