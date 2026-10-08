"use client"

import { useQueryClient } from "@tanstack/react-query"
import { toast } from "sonner"

import { PasswordDialog } from "@/components/admin/password-dialog"
import { adminApi } from "@/lib/admin-api"
import { formatPercent } from "@/lib/format"
import type { RagConfigVersion } from "@/lib/types"

const scoreText = (v: RagConfigVersion | undefined) =>
  v?.latest_eval ? formatPercent(v.latest_eval.score) : "no eval yet"

/** Activation (or rollback) with the spec §7.1 warning: latest eval score vs the active one. */
export function ActivateDialog({
  target,
  versions,
  onOpenChange,
}: {
  target: RagConfigVersion | null
  versions: RagConfigVersion[]
  onOpenChange: (open: boolean) => void
}) {
  const queryClient = useQueryClient()
  const active = versions.find((v) => v.is_active)
  const differentSets =
    !!target?.latest_eval &&
    !!active?.latest_eval &&
    target.latest_eval.eval_set_id !== active.latest_eval.eval_set_id
  const comparison = target
    ? active
      ? `v${target.version} scored ${scoreText(target)}; the active v${active.version} scored ${scoreText(active)}${differentSets ? " (on a different test set)" : ""}.`
      : `v${target.version} scored ${scoreText(target)}; no version is active yet.`
    : ""
  return (
    <PasswordDialog
      open={!!target}
      onOpenChange={onOpenChange}
      title={`Activate v${target?.version ?? ""}?`}
      description={`${comparison} Every new answer will use this configuration.`}
      confirmLabel="Activate"
      onConfirm={async (password) => {
        await adminApi.activateConfig(target!.id, password)
        await queryClient.invalidateQueries({
          queryKey: ["admin", "rag-configs"],
        })
        toast.success(`v${target!.version} is now active`)
      }}
    />
  )
}
