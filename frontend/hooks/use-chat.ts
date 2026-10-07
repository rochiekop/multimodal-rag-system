"use client"

import { useQueryClient } from "@tanstack/react-query"
import { useCallback, useEffect, useReducer, useRef } from "react"

import { ApiError, handleUnauthorized } from "@/lib/api"
import { chatReducer, initialChatState } from "@/lib/chat-state"
import { navigateTo } from "@/lib/navigate"
import { streamChat } from "@/lib/sse"
import type { Message } from "@/lib/types"

/**
 * One chat panel's state. A brand-new chat creates its conversation on the first question;
 * `onStarted` is called once that answer has finished (or was stopped) so the page can move to
 * /app/c/<id>. The URL never changes mid-stream, so the stream is never unmounted.
 */
export function useChat(
  conversationId: string | null,
  initialMessages: Message[],
  onStarted?: (conversationId: string) => void
) {
  const [state, dispatch] = useReducer(
    chatReducer,
    initialChatState(conversationId, initialMessages)
  )
  const queryClient = useQueryClient()
  const abortRef = useRef<AbortController | null>(null)
  const conversationRef = useRef(conversationId)
  useEffect(() => {
    conversationRef.current = state.conversationId
  }, [state.conversationId])

  const ask = useCallback(
    async (question: string, collectionIds: string[]) => {
      const tempId = `temp-${crypto.randomUUID()}`
      dispatch({ type: "ask", question, tempId })
      const controller = new AbortController()
      abortRef.current = controller
      let started: string | null = null
      try {
        const body = {
          question,
          collection_ids: collectionIds,
          ...(conversationRef.current
            ? { conversation_id: conversationRef.current }
            : {}),
        }
        for await (const event of streamChat(body, controller.signal)) {
          dispatch({ type: "event", event, tempId })
          if (event.event === "meta" && !conversationRef.current) {
            started = event.data.conversation_id
            conversationRef.current = started
          }
        }
      } catch (err) {
        if (controller.signal.aborted) dispatch({ type: "stopped", tempId })
        else if (err instanceof ApiError && err.status === 401) {
          // The stream is outside React Query, so the global 401 handler never sees it.
          void handleUnauthorized(navigateTo)
        } else
          dispatch({
            type: "fail",
            tempId,
            message:
              err instanceof ApiError
                ? err.message
                : "Could not reach the assistant.",
          })
      } finally {
        abortRef.current = null
        void queryClient.invalidateQueries({ queryKey: ["conversations"] })
        if (started) onStarted?.(started)
      }
    },
    [queryClient, onStarted]
  )

  const stop = useCallback(() => abortRef.current?.abort(), [])
  return { ...state, ask, stop }
}
