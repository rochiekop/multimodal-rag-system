"use client"

import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useState,
  type ReactNode,
} from "react"

/** Key used for a chat that has no conversation yet. */
export const NEW_CHAT_KEY = "new"

interface CollectionSelection {
  get: (key: string) => string[]
  set: (key: string, ids: string[]) => void
  /** Carry a new chat's selection over to the conversation it just created. */
  move: (from: string, to: string) => void
}

const SelectionContext = createContext<CollectionSelection | null>(null)
const EMPTY: string[] = []

/**
 * Picked collections per conversation. Lives above the chat pages so the selection survives
 * the panel remount when a new chat moves to /app/c/<id>.
 */
export function CollectionSelectionProvider({
  children,
}: {
  children: ReactNode
}) {
  const [selection, setSelection] = useState<Map<string, string[]>>(
    () => new Map()
  )
  const set = useCallback(
    (key: string, ids: string[]) =>
      setSelection((prev) => new Map(prev).set(key, ids)),
    []
  )
  const move = useCallback(
    (from: string, to: string) =>
      setSelection((prev) => {
        const ids = prev.get(from)
        if (!ids) return prev
        const next = new Map(prev)
        next.delete(from)
        next.set(to, ids)
        return next
      }),
    []
  )
  const value = useMemo(
    () => ({ get: (key: string) => selection.get(key) ?? EMPTY, set, move }),
    [selection, set, move]
  )
  return (
    <SelectionContext.Provider value={value}>
      {children}
    </SelectionContext.Provider>
  )
}

/** The selection for one conversation; falls back to local state outside the provider. */
export function useCollectionSelection(
  key: string
): [string[], (ids: string[]) => void] {
  const ctx = useContext(SelectionContext)
  const [local, setLocal] = useState<string[]>(EMPTY)
  const setShared = useCallback(
    (ids: string[]) => ctx?.set(key, ids),
    [ctx, key]
  )
  return ctx ? [ctx.get(key), setShared] : [local, setLocal]
}

/** `move` from the provider, or a no-op outside it. */
export function useMoveCollectionSelection(): (
  from: string,
  to: string
) => void {
  return useContext(SelectionContext)?.move ?? noop
}

function noop() {}
