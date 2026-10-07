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
  // Leaving the page mid-answer cancels the stream; nothing may navigate or dispatch afterwards.
  const mountedRef = useRef(true)
  useEffect(() => {
    mountedRef.current = true
    return () => {
      mountedRef.current = false
      abortRef.current?.abort()
    }
  }, [])

  const ask = useCallback(
    async (question: string, collectionIds: string[]) => {
      const tempId = `temp-${crypto.randomUUID()}`
      dispatch({ type: "ask", question, tempId })
      const controller = new AbortController()
      abortRef.current = controller
      let started: string | null = null
      let finished = false
      try {
        const body = {
          question,
          collection_ids: collectionIds,
          ...(conversationRef.current
            ? { conversation_id: conversationRef.current }
            : {}),
        }
        for await (const event of streamChat(body, controller.signal)) {
          if (!mountedRef.current) break
          dispatch({ type: "event", event, tempId })
          if (event.event === "done" || event.event === "error") finished = true
          if (event.event === "meta" && !conversationRef.current) {
            started = event.data.conversation_id
            conversationRef.current = started
          }
        }
        // A stream that ends without done/error must not leave the answer spinning.
        if (!finished && mountedRef.current)
          dispatch({ type: "stopped", tempId })
      } catch (err) {
        if (!mountedRef.current) return
        if (controller.signal.aborted) dispatch({ type: "stopped", tempId })
        else if (err instanceof ApiError && err.status === 401) {
          // The stream is outside React Query, so the global 401 handler never sees it.
          dispatch({ type: "stopped", tempId })
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
        // The cached transcript is now stale; the next visit must load fresh. An observed
        // query is refetched in place rather than removed out from under its view.
        const id = started ?? conversationRef.current
        if (id) {
          const queryKey = ["conversation", id]
          queryClient.removeQueries({ queryKey, type: "inactive" })
          void queryClient.invalidateQueries({ queryKey })
        }
        if (started && mountedRef.current) onStarted?.(started)
      }
    },
    [queryClient, onStarted]
  )

  const stop = useCallback(() => abortRef.current?.abort(), [])
  return { ...state, ask, stop }
}
