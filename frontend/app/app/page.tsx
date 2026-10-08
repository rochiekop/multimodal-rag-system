"use client"

import { ChatView } from "@/components/chat/chat-view"

export default function NewChatPage() {
  // After the first answer the panel moves to /app/c/<id>; "New chat" links back here.
  return <ChatView />
}
