"use client"

import { zodResolver } from "@hookform/resolvers/zod"
import { useMutation, useQueryClient } from "@tanstack/react-query"
import { useEffect, useState, type ReactNode } from "react"
import { Controller, useForm } from "react-hook-form"
import { toast } from "sonner"
import { z } from "zod"

import { GroupChecklist } from "@/components/admin/group-checklist"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Field, FieldError, FieldLabel } from "@/components/ui/field"
import { Input } from "@/components/ui/input"
import { NativeSelect, NativeSelectOption } from "@/components/ui/native-select"
import { adminApi } from "@/lib/admin-api"
import { ApiError } from "@/lib/api"
import type { AdminUser, Group, Role } from "@/lib/types"

export const ROLE_LABELS: Record<Role, string> = {
  user: "User",
  admin: "Admin",
  super_admin: "Super admin",
}

/** Every status that applies, most important first; "Active" when nothing else does. */
export function userStatuses(user: AdminUser, now = new Date()): string[] {
  const statuses: string[] = []
  if (!user.is_active) statuses.push("Suspended")
  if (user.locked_until && new Date(user.locked_until) > now)
    statuses.push("Sign-in locked")
  if (user.chat_locked_until && new Date(user.chat_locked_until) > now)
    statuses.push("Chat locked")
  if (user.must_change_password) statuses.push("Must change password")
  return statuses.length ? statuses : ["Active"]
}

const errorText = (error: unknown) =>
  error instanceof ApiError ? error.message : "Something went wrong. Try again."

function useUsersMutation<T>(
  fn: (values: T) => Promise<unknown>,
  done: () => void,
  ok: string
) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: fn,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["admin", "users"] })
      void queryClient.invalidateQueries({ queryKey: ["admin", "groups"] })
      toast.success(ok)
      done()
    },
  })
}

function FormDialog({
  open,
  onOpenChange,
  title,
  description,
  error,
  submitLabel,
  pending,
  onSubmit,
  children,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  title: string
  description?: string
  error: string | null
  submitLabel: string
  pending: boolean
  onSubmit: () => void
  children: ReactNode
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <form
          className="grid gap-4"
          onSubmit={(e) => {
            e.preventDefault()
            onSubmit()
          }}
        >
          <DialogHeader>
            <DialogTitle>{title}</DialogTitle>
            {description && (
              <DialogDescription>{description}</DialogDescription>
            )}
          </DialogHeader>
          {children}
          {error && (
            <p role="alert" className="text-sm text-destructive">
              {error}
            </p>
          )}
          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={() => onOpenChange(false)}
            >
              Cancel
            </Button>
            <Button type="submit" disabled={pending}>
              {submitLabel}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

function RoleSelect({
  id,
  canGrantSuperAdmin,
  ...props
}: { id: string; canGrantSuperAdmin: boolean } & React.ComponentProps<
  typeof NativeSelect
>) {
  const roles: Role[] = canGrantSuperAdmin
    ? ["user", "admin", "super_admin"]
    : ["user", "admin"]
  return (
    <NativeSelect id={id} {...props}>
      {roles.map((role) => (
        <NativeSelectOption key={role} value={role}>
          {ROLE_LABELS[role]}
        </NativeSelectOption>
      ))}
    </NativeSelect>
  )
}

const createSchema = z.object({
  username: z.string().trim().min(3, "At least 3 characters").max(64),
  full_name: z.string().trim().min(1, "Enter a name").max(200),
  password: z.string().min(1, "Enter an initial password").max(128),
  role: z.enum(["user", "admin", "super_admin"]),
  group_ids: z.array(z.string()),
})

export function CreateUserDialog({
  open,
  onOpenChange,
  groups,
  canGrantSuperAdmin,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  groups: Group[]
  canGrantSuperAdmin: boolean
}) {
  const [error, setError] = useState<string | null>(null)
  const form = useForm<z.infer<typeof createSchema>>({
    resolver: zodResolver(createSchema),
  })
  const { register, control, reset, handleSubmit, formState } = form
  useEffect(() => {
    if (open) {
      reset({
        username: "",
        full_name: "",
        password: "",
        role: "user",
        group_ids: [],
      })
    }
  }, [open, reset])
  const create = useUsersMutation(
    adminApi.createUser,
    () => onOpenChange(false),
    "User created"
  )
  const submit = handleSubmit((values) =>
    (setError(null), create.mutateAsync(values)).catch((e) =>
      setError(errorText(e))
    )
  )
  return (
    <FormDialog
      open={open}
      onOpenChange={(next) => {
        if (!next) setError(null)
        onOpenChange(next)
      }}
      title="New user"
      description="They must change this password when they first sign in."
      error={error}
      submitLabel="Create user"
      pending={create.isPending}
      onSubmit={() => void submit()}
    >
      <Field data-invalid={!!formState.errors.username}>
        <FieldLabel htmlFor="new-username">Username</FieldLabel>
        <Input id="new-username" autoComplete="off" {...register("username")} />
        <FieldError errors={[formState.errors.username]} />
      </Field>
      <Field data-invalid={!!formState.errors.full_name}>
        <FieldLabel htmlFor="new-full-name">Full name</FieldLabel>
        <Input id="new-full-name" {...register("full_name")} />
        <FieldError errors={[formState.errors.full_name]} />
      </Field>
      <Field data-invalid={!!formState.errors.password}>
        <FieldLabel htmlFor="new-password">Initial password</FieldLabel>
        <Input
          id="new-password"
          type="password"
          autoComplete="new-password"
          {...register("password")}
        />
        <FieldError errors={[formState.errors.password]} />
      </Field>
      <Field>
        <FieldLabel htmlFor="new-role">Role</FieldLabel>
        <RoleSelect
          id="new-role"
          canGrantSuperAdmin={canGrantSuperAdmin}
          {...register("role")}
        />
      </Field>
      <Field>
        <FieldLabel>Groups</FieldLabel>
        <Controller
          control={control}
          name="group_ids"
          render={({ field }) => (
            <GroupChecklist
              groups={groups}
              value={field.value ?? []}
              onChange={field.onChange}
              idPrefix="new-user-group"
            />
          )}
        />
      </Field>
    </FormDialog>
  )
}

const editSchema = z.object({
  full_name: z.string().trim().min(1, "Enter a name").max(200),
  role: z.enum(["user", "admin", "super_admin"]),
  group_ids: z.array(z.string()),
})

export function EditUserDialog({
  user,
  onOpenChange,
  groups,
  canGrantSuperAdmin,
}: {
  user: AdminUser | null
  onOpenChange: (open: boolean) => void
  groups: Group[]
  canGrantSuperAdmin: boolean
}) {
  const [error, setError] = useState<string | null>(null)
  const form = useForm<z.infer<typeof editSchema>>({
    resolver: zodResolver(editSchema),
  })
  const { register, control, reset, handleSubmit, formState } = form
  useEffect(() => {
    if (user) {
      reset({
        full_name: user.full_name,
        role: user.role,
        group_ids: user.groups.map((g) => g.id),
      })
    }
  }, [user, reset])
  const update = useUsersMutation(
    (values: z.infer<typeof editSchema>) =>
      adminApi.updateUser(user!.id, values),
    () => onOpenChange(false),
    "User updated"
  )
  const submit = handleSubmit((values) =>
    (setError(null), update.mutateAsync(values)).catch((e) =>
      setError(errorText(e))
    )
  )
  return (
    <FormDialog
      open={!!user}
      onOpenChange={(next) => {
        if (!next) setError(null)
        onOpenChange(next)
      }}
      title={`Edit ${user?.username ?? ""}`}
      error={error}
      submitLabel="Save"
      pending={update.isPending}
      onSubmit={() => void submit()}
    >
      <Field data-invalid={!!formState.errors.full_name}>
        <FieldLabel htmlFor="edit-full-name">Full name</FieldLabel>
        <Input id="edit-full-name" {...register("full_name")} />
        <FieldError errors={[formState.errors.full_name]} />
      </Field>
      <Field>
        <FieldLabel htmlFor="edit-role">Role</FieldLabel>
        <RoleSelect
          id="edit-role"
          canGrantSuperAdmin={
            canGrantSuperAdmin || user?.role === "super_admin"
          }
          {...register("role")}
        />
      </Field>
      <Field>
        <FieldLabel>Groups</FieldLabel>
        <Controller
          control={control}
          name="group_ids"
          render={({ field }) => (
            <GroupChecklist
              groups={groups}
              value={field.value ?? []}
              onChange={field.onChange}
              idPrefix="edit-user-group"
            />
          )}
        />
      </Field>
    </FormDialog>
  )
}

const resetSchema = z.object({
  new_password: z.string().min(1, "Enter a password").max(128),
})

export function ResetPasswordDialog({
  user,
  onOpenChange,
}: {
  user: AdminUser | null
  onOpenChange: (open: boolean) => void
}) {
  const [error, setError] = useState<string | null>(null)
  const form = useForm<z.infer<typeof resetSchema>>({
    resolver: zodResolver(resetSchema),
  })
  useEffect(() => {
    if (user) {
      form.reset({ new_password: "" })
    }
  }, [user, form])
  const reset = useUsersMutation(
    (values: z.infer<typeof resetSchema>) =>
      adminApi.resetPassword(user!.id, values.new_password),
    () => onOpenChange(false),
    "Password reset; they must change it at next sign-in"
  )
  const submit = form.handleSubmit((values) =>
    (setError(null), reset.mutateAsync(values)).catch((e) =>
      setError(errorText(e))
    )
  )
  return (
    <FormDialog
      open={!!user}
      onOpenChange={(next) => {
        if (!next) setError(null)
        onOpenChange(next)
      }}
      title={`Reset password for ${user?.username ?? ""}`}
      description="This signs them out everywhere."
      error={error}
      submitLabel="Reset password"
      pending={reset.isPending}
      onSubmit={() => void submit()}
    >
      <Field data-invalid={!!form.formState.errors.new_password}>
        <FieldLabel htmlFor="reset-password">New password</FieldLabel>
        <Input
          id="reset-password"
          type="password"
          autoComplete="new-password"
          {...form.register("new_password")}
        />
        <FieldError errors={[form.formState.errors.new_password]} />
      </Field>
    </FormDialog>
  )
}

const groupSchema = z.object({
  name: z.string().trim().min(1, "Enter a name").max(100),
  description: z.string().max(500),
})

export function CreateGroupDialog({
  open,
  onOpenChange,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  const [error, setError] = useState<string | null>(null)
  const form = useForm<z.infer<typeof groupSchema>>({
    resolver: zodResolver(groupSchema),
  })
  useEffect(() => {
    if (open) {
      form.reset({ name: "", description: "" })
    }
  }, [open, form])
  const create = useUsersMutation(
    adminApi.createGroup,
    () => onOpenChange(false),
    "Group created"
  )
  const submit = form.handleSubmit((values) =>
    (setError(null), create.mutateAsync(values)).catch((e) =>
      setError(errorText(e))
    )
  )
  return (
    <FormDialog
      open={open}
      onOpenChange={(next) => {
        if (!next) setError(null)
        onOpenChange(next)
      }}
      title="New group"
      error={error}
      submitLabel="Create group"
      pending={create.isPending}
      onSubmit={() => void submit()}
    >
      <Field data-invalid={!!form.formState.errors.name}>
        <FieldLabel htmlFor="group-name">Name</FieldLabel>
        <Input id="group-name" {...form.register("name")} />
        <FieldError errors={[form.formState.errors.name]} />
      </Field>
      <Field>
        <FieldLabel htmlFor="group-description">Description</FieldLabel>
        <Input id="group-description" {...form.register("description")} />
      </Field>
    </FormDialog>
  )
}
