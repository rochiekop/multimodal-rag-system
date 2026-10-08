"use client"

import { useQuery } from "@tanstack/react-query"
import type { ColumnDef } from "@tanstack/react-table"
import { useState } from "react"

import { CollectionDialog } from "@/components/admin/collection-dialog"
import { DataTable } from "@/components/admin/data-table"
import { PageHeader } from "@/components/admin/page-header"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { adminApi } from "@/lib/admin-api"
import { formatDateTime } from "@/lib/format"
import type { AdminCollection } from "@/lib/types"

export default function CollectionsPage() {
  const collections = useQuery({
    queryKey: ["admin", "collections"],
    queryFn: adminApi.collections,
  })
  const groups = useQuery({
    queryKey: ["admin", "groups"],
    queryFn: adminApi.groups,
  })
  const [editing, setEditing] = useState<AdminCollection | undefined>()
  const [open, setOpen] = useState(false)

  const columns: ColumnDef<AdminCollection>[] = [
    {
      accessorKey: "name",
      header: "Name",
      enableSorting: true,
      cell: ({ row }) => (
        <div>
          <div className="font-medium">{row.original.name}</div>
          <div className="text-xs text-muted-foreground">
            {row.original.description}
          </div>
        </div>
      ),
    },
    {
      id: "groups",
      header: "Groups",
      cell: ({ row }) =>
        row.original.groups.length ? (
          <div className="flex flex-wrap gap-1">
            {row.original.groups.map((g) => (
              <Badge key={g.id} variant="secondary">
                {g.name}
              </Badge>
            ))}
          </div>
        ) : (
          <span className="text-muted-foreground">No access yet</span>
        ),
    },
    {
      id: "sensitive",
      header: "Sensitive",
      cell: ({ row }) =>
        row.original.sensitive ? <Badge>Sensitive</Badge> : null,
    },
    {
      accessorKey: "created_at",
      header: "Created",
      cell: ({ row }) => formatDateTime(row.original.created_at),
    },
    {
      id: "actions",
      header: "",
      cell: ({ row }) => (
        <Button
          size="sm"
          variant="outline"
          aria-label={`Edit ${row.original.name}`}
          onClick={() => {
            setEditing(row.original)
            setOpen(true)
          }}
        >
          Edit
        </Button>
      ),
    },
  ]

  return (
    <>
      <PageHeader
        title="Collections & access"
        description="Collections group documents; groups decide who can ask about them."
        actions={
          <Button
            onClick={() => {
              setEditing(undefined)
              setOpen(true)
            }}
          >
            New collection
          </Button>
        }
      />
      <DataTable
        columns={columns}
        data={collections.data ?? []}
        isLoading={collections.isLoading}
        getRowId={(c) => c.id}
        empty="No collections yet."
      />
      <CollectionDialog
        open={open}
        onOpenChange={setOpen}
        collection={editing}
        groups={groups.data ?? []}
      />
    </>
  )
}
