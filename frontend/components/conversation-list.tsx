"use client"

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { MoreHorizontalIcon, PencilIcon, Trash2Icon } from "lucide-react"
import Link from "next/link"
import { useRouter } from "next/navigation"
import { useState } from "react"
import { toast } from "sonner"

import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import {
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarInput,
  SidebarMenu,
  SidebarMenuAction,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarMenuSkeleton,
} from "@/components/ui/sidebar"
import { useDebouncedValue } from "@/hooks/use-debounced-value"
import { api, ApiError } from "@/lib/api"
import type { Conversation } from "@/lib/types"

export function ConversationList({ activeId }: { activeId?: string }) {
  const router = useRouter()
  const queryClient = useQueryClient()
  const [search, setSearch] = useState("")
  const q = useDebouncedValue(search.trim())
  const { data, isPending } = useQuery({
    queryKey: ["conversations", q],
    queryFn: () => api.conversations(q || undefined),
  })
  const [renaming, setRenaming] = useState<Conversation | null>(null)
  const [title, setTitle] = useState("")
  const [deleting, setDeleting] = useState<Conversation | null>(null)

  const onError = (err: unknown) =>
    toast.error(err instanceof ApiError ? err.message : "Something went wrong")
  const rename = useMutation({
    mutationFn: ({ id, value }: { id: string; value: string }) =>
      api.renameConversation(id, value),
    onSuccess: () => {
      setRenaming(null)
      void queryClient.invalidateQueries({ queryKey: ["conversations"] })
    },
    onError,
  })
  const remove = useMutation({
    mutationFn: (id: string) => api.deleteConversation(id),
    onSuccess: (_, id) => {
      setDeleting(null)
      void queryClient.invalidateQueries({ queryKey: ["conversations"] })
      if (id === activeId) router.push("/app")
    },
    onError,
  })

  return (
    <SidebarGroup>
      <SidebarGroupLabel>Conversations</SidebarGroupLabel>
      <SidebarGroupContent className="flex flex-col gap-2">
        <SidebarInput
          placeholder="Search conversations"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
        <SidebarMenu>
          {isPending &&
            Array.from({ length: 4 }, (_, i) => (
              <SidebarMenuItem key={i}>
                <SidebarMenuSkeleton />
              </SidebarMenuItem>
            ))}
          {data?.length === 0 && (
            <p className="px-2 py-1 text-sm text-muted-foreground">
              {q ? "No matching conversations" : "No conversations yet"}
            </p>
          )}
          {data?.map((c) => (
            <SidebarMenuItem key={c.id}>
              <SidebarMenuButton asChild isActive={c.id === activeId}>
                <Link href={`/app/c/${c.id}`}>
                  <span className="truncate">{c.title}</span>
                </Link>
              </SidebarMenuButton>
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <SidebarMenuAction
                    showOnHover
                    aria-label="Conversation actions"
                  >
                    <MoreHorizontalIcon />
                  </SidebarMenuAction>
                </DropdownMenuTrigger>
                <DropdownMenuContent side="right" align="start">
                  <DropdownMenuItem
                    onSelect={() => {
                      setTitle(c.title)
                      setRenaming(c)
                    }}
                  >
                    <PencilIcon /> Rename
                  </DropdownMenuItem>
                  <DropdownMenuItem
                    variant="destructive"
                    onSelect={() => setDeleting(c)}
                  >
                    <Trash2Icon /> Delete
                  </DropdownMenuItem>
                </DropdownMenuContent>
              </DropdownMenu>
            </SidebarMenuItem>
          ))}
        </SidebarMenu>
      </SidebarGroupContent>

      <Dialog
        open={renaming !== null}
        onOpenChange={(open) => !open && setRenaming(null)}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Rename conversation</DialogTitle>
          </DialogHeader>
          <form
            onSubmit={(e) => {
              e.preventDefault()
              if (renaming && title.trim())
                rename.mutate({ id: renaming.id, value: title.trim() })
            }}
            className="flex flex-col gap-4"
          >
            <div className="flex flex-col gap-2">
              <Label htmlFor="conversation-title">Title</Label>
              <Input
                id="conversation-title"
                value={title}
                maxLength={200}
                onChange={(e) => setTitle(e.target.value)}
              />
            </div>
            <DialogFooter>
              <Button
                type="submit"
                disabled={!title.trim() || rename.isPending}
              >
                Save
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

      <AlertDialog
        open={deleting !== null}
        onOpenChange={(open) => !open && setDeleting(null)}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete this conversation?</AlertDialogTitle>
            <AlertDialogDescription>
              “{deleting?.title}” and its messages will be permanently deleted.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              variant="destructive"
              onClick={() => deleting && remove.mutate(deleting.id)}
            >
              Delete
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </SidebarGroup>
  )
}
