"use client"

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { useState } from "react"

import { PageHeader } from "@/components/admin/page-header"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { Label } from "@/components/ui/label"
import { Switch } from "@/components/ui/switch"
import { adminApi } from "@/lib/admin-api"
import { formatDateTime } from "@/lib/format"

export default function NotificationsPage() {
  const queryClient = useQueryClient()
  const [unreadOnly, setUnreadOnly] = useState(true)
  const { data, isLoading } = useQuery({
    queryKey: ["admin", "notifications", unreadOnly ? "unread" : "all"],
    queryFn: () => adminApi.notifications(unreadOnly),
  })
  const markRead = useMutation({
    mutationFn: adminApi.markNotificationRead,
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: ["admin", "notifications"] }),
  })

  return (
    <>
      <PageHeader
        title="Notifications"
        description="Ingestion failures, cost caps, eval drops and strike locks."
        actions={
          <div className="flex items-center gap-2">
            <Switch
              id="unread-only"
              checked={unreadOnly}
              onCheckedChange={setUnreadOnly}
            />
            <Label htmlFor="unread-only">Unread only</Label>
          </div>
        }
      />
      {isLoading && <p className="text-sm text-muted-foreground">Loading…</p>}
      {data?.length === 0 && (
        <p className="text-sm text-muted-foreground">
          You&apos;re all caught up.
        </p>
      )}
      <div className="grid gap-3">
        {data?.map((note) => (
          <Card
            key={note.id}
            className={note.read_at ? "opacity-70" : undefined}
          >
            <CardHeader className="flex flex-row items-start justify-between gap-4">
              <div className="grid gap-1">
                <CardTitle className="text-base">{note.title}</CardTitle>
                <CardDescription>
                  {formatDateTime(note.created_at)} · {note.body}
                </CardDescription>
              </div>
              {!note.read_at && (
                <Button
                  size="sm"
                  variant="outline"
                  disabled={markRead.isPending}
                  onClick={() => markRead.mutate(note.id)}
                >
                  Mark as read
                </Button>
              )}
            </CardHeader>
          </Card>
        ))}
      </div>
    </>
  )
}
