"use client"

import { zodResolver } from "@hookform/resolvers/zod"
import { useRouter } from "next/navigation"
import { useEffect, useState } from "react"
import { useForm } from "react-hook-form"
import { z } from "zod"

import { Alert, AlertDescription } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import {
  Field,
  FieldError,
  FieldGroup,
  FieldLabel,
} from "@/components/ui/field"
import { Input } from "@/components/ui/input"
import { api, ApiError } from "@/lib/api"

const schema = z.object({
  username: z.string().trim().min(1, "Enter your username"),
  password: z.string().min(1, "Enter your password"),
})
type Values = z.infer<typeof schema>

/** Only same-site paths are allowed as the post-login destination. */
export function safeNext(next: string | undefined): string {
  if (!next || !next.startsWith("/") || next.startsWith("//")) return "/app"
  if (/[\\\u0000-\u001f\u007f]/.test(next)) return "/app"
  try {
    const url = new URL(next, "http://placeholder.local")
    if (url.origin !== "http://placeholder.local") return "/app"
    return url.pathname + url.search + url.hash
  } catch {
    return "/app"
  }
}

export function LoginForm({ next }: { next?: string }) {
  const router = useRouter()
  const [error, setError] = useState<string | null>(null)
  // Already signed in (e.g. arriving from a cross-site link, where the SameSite=Strict cookie
  // wasn't sent): skip the form. Called directly so a 401 never reaches the global handler.
  useEffect(() => {
    let cancelled = false
    api
      .me()
      .then((user) => {
        if (cancelled) return
        router.replace(
          user.must_change_password ? "/change-password" : safeNext(next)
        )
      })
      .catch(() => undefined)
    return () => {
      cancelled = true
    }
  }, [router, next])
  const form = useForm<Values>({
    resolver: zodResolver(schema),
    defaultValues: { username: "", password: "" },
  })

  async function onSubmit(values: Values) {
    setError(null)
    try {
      const info = await api.login(values.username, values.password)
      router.replace(
        info.must_change_password ? "/change-password" : safeNext(next)
      )
    } catch (err) {
      setError(
        err instanceof ApiError ? err.message : "Could not reach the server"
      )
    }
  }

  const { errors, isSubmitting } = form.formState
  return (
    <Card>
      <CardHeader className="text-center">
        <CardTitle className="text-xl">Sign in</CardTitle>
        <CardDescription>
          Use the account your administrator gave you
        </CardDescription>
      </CardHeader>
      <CardContent>
        <form onSubmit={form.handleSubmit(onSubmit)} noValidate>
          <FieldGroup>
            {error && (
              <Alert variant="destructive">
                <AlertDescription>{error}</AlertDescription>
              </Alert>
            )}
            <Field data-invalid={!!errors.username}>
              <FieldLabel htmlFor="username">Username</FieldLabel>
              <Input
                id="username"
                autoComplete="username"
                {...form.register("username")}
              />
              <FieldError>{errors.username?.message}</FieldError>
            </Field>
            <Field data-invalid={!!errors.password}>
              <FieldLabel htmlFor="password">Password</FieldLabel>
              <Input
                id="password"
                type="password"
                autoComplete="current-password"
                {...form.register("password")}
              />
              <FieldError>{errors.password?.message}</FieldError>
            </Field>
            <Field>
              <Button type="submit" disabled={isSubmitting}>
                {isSubmitting ? "Signing in…" : "Sign in"}
              </Button>
            </Field>
          </FieldGroup>
        </form>
      </CardContent>
    </Card>
  )
}
