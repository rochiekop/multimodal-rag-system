"use client"

import { useQuery } from "@tanstack/react-query"

import { ChatPanel } from "@/components/chat/chat-panel"
import { Skeleton } from "@/components/ui/skeleton"
import { api } from "@/lib/api"

export function ChatView({ conversationId }: { conversationId?: string }) {
  const { data, isPending, isError } = useQuery({
    queryKey: ["conversation", conversationId],
    queryFn: () => api.conversation(conversationId!),
    enabled: !!conversationId,
  })
  if (!conversationId)
    return <ChatPanel key="new" conversationId={null} initialMessages={[]} />
  if (isPending)
    return (
      <div className="mx-auto flex max-w-3xl flex-col gap-4 p-6">
        <Skeleton className="ml-auto h-10 w-1/2" />
        <Skeleton className="h-24 w-full" />
      </div>
    )
  if (isError || !data)
    return (
      <p className="p-6 text-muted-foreground">
        This conversation isn&apos;t available.
      </p>
    )
  return (
    <ChatPanel
      key={conversationId}
      conversationId={conversationId}
      initialMessages={data.messages}
    />
  )
}
