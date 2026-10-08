"use client"

import { zodResolver } from "@hookform/resolvers/zod"
import { useMutation, useQueryClient } from "@tanstack/react-query"
import { useEffect, useState } from "react"
import { Controller, useForm } from "react-hook-form"
import { toast } from "sonner"
import { z } from "zod"

import { GroupChecklist } from "@/components/admin/group-checklist"
import { PasswordDialog } from "@/components/admin/password-dialog"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import {
  Field,
  FieldDescription,
  FieldError,
  FieldLabel,
} from "@/components/ui/field"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Switch } from "@/components/ui/switch"
import { Textarea } from "@/components/ui/textarea"
import { adminApi } from "@/lib/admin-api"
import { ApiError } from "@/lib/api"
import type { AdminCollection, CollectionUpdate, Group } from "@/lib/types"

const schema = z.object({
  name: z.string().trim().min(1, "Enter a name").max(100),
  description: z.string().max(500),
  sensitive: z.boolean(),
  group_ids: z.array(z.string()),
})
type Values = z.infer<typeof schema>

const sameIds = (a: string[], b: string[]) =>
  a.length === b.length &&
  [...a].sort().every((id, i) => id === [...b].sort()[i])

export function CollectionDialog({
  open,
  onOpenChange,
  collection,
  groups,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  collection?: AdminCollection
  groups: Group[]
}) {
  const queryClient = useQueryClient()
  const [formError, setFormError] = useState<string | null>(null)
  const [pending, setPending] = useState<CollectionUpdate | null>(null)
  const form = useForm<Values>({ resolver: zodResolver(schema) })
  const { register, handleSubmit, control, reset, formState } = form

  useEffect(() => {
    if (!open) return
    reset({
      name: collection?.name ?? "",
      description: collection?.description ?? "",
      sensitive: collection?.sensitive ?? false,
      group_ids: collection?.groups.map((g) => g.id) ?? [],
    })
  }, [open, collection, reset])

  const save = useMutation({
    mutationFn: (values: CollectionUpdate) =>
      collection
        ? adminApi.updateCollection(collection.id, values)
        : adminApi.createCollection({
            name: values.name ?? "",
            description: values.description ?? "",
            sensitive: values.sensitive ?? false,
            group_ids: values.group_ids ?? [],
          }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["admin", "collections"] })
      toast.success(collection ? "Collection updated" : "Collection created")
      onOpenChange(false)
    },
  })

  async function onSubmit(values: Values) {
    setFormError(null)
    const base = {
      name: values.name,
      description: values.description,
      sensitive: values.sensitive,
    }
    if (!collection) {
      return save
        .mutateAsync({ ...base, group_ids: values.group_ids })
        .catch(showError)
    }
    const current = collection.groups.map((g) => g.id)
    if (!sameIds(current, values.group_ids)) {
      setPending({ ...base, group_ids: values.group_ids }) // access change: password first
      return
    }
    return save.mutateAsync(base).catch(showError)
  }

  function showError(error: unknown) {
    setFormError(
      error instanceof ApiError ? error.message : "Could not save. Try again."
    )
  }

  return (
    <>
      <Dialog
        open={open && !pending}
        onOpenChange={(next) => {
          if (!next) setFormError(null)
          onOpenChange(next)
        }}
      >
        <DialogContent>
          <form onSubmit={handleSubmit(onSubmit)} className="grid gap-4">
            <DialogHeader>
              <DialogTitle>
                {collection ? "Edit collection" : "New collection"}
              </DialogTitle>
            </DialogHeader>
            <Field data-invalid={!!formState.errors.name}>
              <FieldLabel htmlFor="collection-name">Name</FieldLabel>
              <Input id="collection-name" {...register("name")} />
              <FieldError errors={[formState.errors.name]} />
            </Field>
            <Field>
              <FieldLabel htmlFor="collection-description">
                Description
              </FieldLabel>
              <Textarea
                id="collection-description"
                rows={2}
                {...register("description")}
              />
            </Field>
            <Controller
              control={control}
              name="sensitive"
              render={({ field }) => (
                <div className="flex items-center gap-2">
                  <Switch
                    id="collection-sensitive"
                    checked={field.value}
                    onCheckedChange={field.onChange}
                  />
                  <Label htmlFor="collection-sensitive">Sensitive</Label>
                </div>
              )}
            />
            <Field>
              <FieldLabel>Groups with access</FieldLabel>
              <FieldDescription>
                Members of these groups can ask about this collection&apos;s
                documents.
              </FieldDescription>
              <Controller
                control={control}
                name="group_ids"
                render={({ field }) => (
                  <GroupChecklist
                    groups={groups}
                    value={field.value ?? []}
                    onChange={field.onChange}
                    idPrefix="collection-group"
                  />
                )}
              />
            </Field>
            {formError && (
              <p role="alert" className="text-sm text-destructive">
                {formError}
              </p>
            )}
            <DialogFooter>
              <Button
                type="button"
                variant="outline"
                onClick={() => {
                  setFormError(null)
                  onOpenChange(false)
                }}
              >
                Cancel
              </Button>
              <Button type="submit" disabled={save.isPending}>
                Save
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
      <PasswordDialog
        open={!!pending}
        onOpenChange={(next) => {
          if (!next) setPending(null)
        }}
        title="Change who can access this collection"
        description="Answers will immediately include or exclude these documents for the affected users."
        confirmLabel="Change access"
        onConfirm={(password) => save.mutateAsync({ ...pending, password })}
      />
    </>
  )
}
