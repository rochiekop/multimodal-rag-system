"use client"

import { zodResolver } from "@hookform/resolvers/zod"
import { useState } from "react"
import { useForm } from "react-hook-form"
import { z } from "zod"

import { Alert, AlertDescription } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import {
  Field,
  FieldError,
  FieldGroup,
  FieldLabel,
} from "@/components/ui/field"
import { Input } from "@/components/ui/input"
import { api, ApiError } from "@/lib/api"
import type { SessionInfo } from "@/lib/types"

const schema = z
  .object({
    current: z.string().min(1, "Enter your current password"),
    next: z.string().min(1, "Enter a new password"),
    confirm: z.string(),
  })
  .refine((v) => v.next === v.confirm, {
    message: "Passwords don't match",
    path: ["confirm"],
  })
type Values = z.infer<typeof schema>

export function ChangePasswordForm({
  onDone,
}: {
  onDone: (info: SessionInfo) => void
}) {
  const [error, setError] = useState<string | null>(null)
  const form = useForm<Values>({
    resolver: zodResolver(schema),
    defaultValues: { current: "", next: "", confirm: "" },
  })

  async function onSubmit(values: Values) {
    setError(null)
    try {
      onDone(await api.changePassword(values.current, values.next))
      form.reset()
    } catch (err) {
      setError(
        err instanceof ApiError ? err.message : "Could not reach the server"
      )
    }
  }

  const { errors, isSubmitting } = form.formState
  const fields = [
    ["current", "Current password", "current-password"],
    ["next", "New password", "new-password"],
    ["confirm", "Confirm new password", "new-password"],
  ] as const
  return (
    <form onSubmit={form.handleSubmit(onSubmit)} noValidate>
      <FieldGroup>
        {error && (
          <Alert variant="destructive">
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        )}
        {fields.map(([name, label, autoComplete]) => (
          <Field key={name} data-invalid={!!errors[name]}>
            <FieldLabel htmlFor={name}>{label}</FieldLabel>
            <Input
              id={name}
              type="password"
              autoComplete={autoComplete}
              {...form.register(name)}
            />
            <FieldError>{errors[name]?.message}</FieldError>
          </Field>
        ))}
        <Field>
          <Button type="submit" disabled={isSubmitting}>
            {isSubmitting ? "Saving…" : "Change password"}
          </Button>
        </Field>
      </FieldGroup>
    </form>
  )
}
