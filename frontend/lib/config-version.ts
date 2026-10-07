"use client"

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"

import { adminApi } from "@/lib/admin-api"
import type { RagConfig } from "@/lib/types"

export const useActiveConfig = () =>
  useQuery({
    queryKey: ["admin", "rag-configs", "active"],
    queryFn: adminApi.activeConfig,
  })

export const useConfigVersions = () =>
  useQuery({ queryKey: ["admin", "rag-configs"], queryFn: adminApi.ragConfigs })

/** Saves a new (inactive) version; activation is a separate, password-confirmed step. */
export function useCreateVersion() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ config, note }: { config: RagConfig; note: string }) =>
      adminApi.createConfig(config, note),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: ["admin", "rag-configs"] }),
  })
}
