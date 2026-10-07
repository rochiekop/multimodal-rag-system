"use client"

import { zodResolver } from "@hookform/resolvers/zod"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { useEffect, useRef, useState } from "react"
import { useForm } from "react-hook-form"
import { toast } from "sonner"
import { z } from "zod"

import { PageHeader } from "@/components/admin/page-header"
import { PasswordDialog } from "@/components/admin/password-dialog"
import { SuperAdminOnly } from "@/components/admin/super-admin-only"
import { BrandMark } from "@/components/branding"
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
  FieldDescription,
  FieldError,
  FieldLabel,
} from "@/components/ui/field"
import { Input } from "@/components/ui/input"
import { adminApi } from "@/lib/admin-api"
import { api, ApiError } from "@/lib/api"
import { formatDateTime } from "@/lib/format"
import type { Branding, KeyStatus } from "@/lib/types"

const errorText = (e: unknown) =>
  e instanceof ApiError ? e.message : "Something went wrong. Try again."

const brandingSchema = z.object({
  app_name: z.string().trim().min(1, "Enter a name").max(60),
  primary_color: z
    .string()
    .trim()
    .refine(
      (v) => v === "" || /^#[0-9a-fA-F]{6}$/.test(v),
      "Use a hex color like #1d4ed8"
    ),
})

function BrandingCard() {
  const queryClient = useQueryClient()
  const fileInput = useRef<HTMLInputElement>(null)
  const { data: branding } = useQuery({
    queryKey: ["branding"],
    queryFn: api.branding,
  })
  const form = useForm<z.infer<typeof brandingSchema>>({
    resolver: zodResolver(brandingSchema),
  })
  useEffect(() => {
    if (branding)
      form.reset({
        app_name: branding.app_name,
        primary_color: branding.primary_color ?? "",
      })
  }, [branding, form])
  const apply = (next: Branding) => queryClient.setQueryData(["branding"], next)
  const save = useMutation({
    mutationFn: adminApi.updateBranding,
    onSuccess: (next) => {
      apply(next)
      toast.success("Branding saved")
    },
    onError: (e) => toast.error(errorText(e)),
  })
  const upload = useMutation({
    mutationFn: adminApi.uploadLogo,
    onSuccess: (next) => {
      apply(next)
      toast.success("Logo updated")
    },
    onError: (e) => toast.error(errorText(e)),
  })
  const remove = useMutation({
    mutationFn: adminApi.removeLogo,
    onSuccess: apply,
    onError: (e) => toast.error(errorText(e)),
  })
  const { errors } = form.formState
  if (!branding) return null // the form fills from saved branding; typing earlier would be lost
  return (
    <Card>
      <CardHeader>
        <CardTitle>Branding</CardTitle>
        <CardDescription>
          Shown on the sign-in page, in both sidebars and the browser tab.
        </CardDescription>
      </CardHeader>
      <CardContent className="grid gap-6">
        <form
          className="grid gap-4 md:grid-cols-2"
          onSubmit={form.handleSubmit((v) =>
            save.mutate({
              app_name: v.app_name,
              primary_color: v.primary_color || null,
            })
          )}
        >
          <Field data-invalid={!!errors.app_name}>
            <FieldLabel htmlFor="brand-name">App name</FieldLabel>
            <Input id="brand-name" {...form.register("app_name")} />
            <FieldError errors={[errors.app_name]} />
          </Field>
          <Field data-invalid={!!errors.primary_color}>
            <FieldLabel htmlFor="brand-color">Primary color</FieldLabel>
            <Input
              id="brand-color"
              placeholder="#1d4ed8 (empty = default)"
              {...form.register("primary_color")}
            />
            <FieldError errors={[errors.primary_color]} />
          </Field>
          <div className="md:col-span-2">
            <Button type="submit" disabled={save.isPending}>
              Save branding
            </Button>
          </div>
        </form>
        <div className="flex flex-wrap items-center gap-3">
          <BrandMark className="size-12" />
          <input
            ref={fileInput}
            type="file"
            accept="image/png,image/jpeg,image/webp"
            aria-label="Logo file"
            className="sr-only"
            onChange={(e) => {
              const file = e.target.files?.[0]
              e.target.value = ""
              if (file) upload.mutate(file)
            }}
          />
          <Button
            variant="outline"
            disabled={upload.isPending}
            onClick={() => fileInput.current?.click()}
          >
            Upload logo
          </Button>
          {branding?.logo_url && (
            <Button
              variant="ghost"
              disabled={remove.isPending}
              onClick={() => remove.mutate()}
            >
              Remove logo
            </Button>
          )}
          <FieldDescription>
            PNG, JPEG or WebP, at most 512 KB.
          </FieldDescription>
        </div>
      </CardContent>
    </Card>
  )
}

function keyDescription(status: KeyStatus): string {
  switch (status.source) {
    case "database":
      return `Saved in Settings (…${status.last4})${status.updated_at ? `, updated ${formatDateTime(status.updated_at)}` : ""}.`
    case "environment":
      return `Using RAG_OPENAI_API_KEY from deploy/.env (…${status.last4}).`
    case "unreadable":
      return "The saved key can't be decrypted with the current RAG_SECRETS_KEY; RAG_OPENAI_API_KEY is used if set. Save the key again."
    default:
      return "No key is configured: chat, ingestion and evaluation won't work until you add one."
  }
}

function OpenAIKeyCard() {
  const queryClient = useQueryClient()
  const { data: status } = useQuery({
    queryKey: ["admin", "openai-key"],
    queryFn: adminApi.openaiKey,
  })
  const [key, setKey] = useState("")
  const [confirming, setConfirming] = useState<"save" | "clear" | null>(null)
  const apply = (next: KeyStatus) =>
    queryClient.setQueryData(["admin", "openai-key"], next)
  if (!status) return null
  const disabled = !status.secrets_key_configured
  return (
    <Card>
      <CardHeader>
        <CardTitle>OpenAI API key</CardTitle>
        <CardDescription>
          Encrypted at rest; only the last 4 characters are ever shown. Every
          service picks up a new key within 30 seconds.
        </CardDescription>
      </CardHeader>
      <CardContent className="grid gap-4">
        <p className="text-sm">{keyDescription(status)}</p>
        {disabled && (
          <Alert>
            <AlertDescription>
              Set RAG_SECRETS_KEY in deploy/.env (a Fernet key) and restart to
              save keys here.
            </AlertDescription>
          </Alert>
        )}
        <form
          className="flex flex-wrap items-end gap-3"
          onSubmit={(e) => {
            e.preventDefault()
            if (key.trim().length >= 20) setConfirming("save")
          }}
        >
          <Field className="min-w-72 flex-1">
            <FieldLabel htmlFor="openai-key">New OpenAI API key</FieldLabel>
            <Input
              id="openai-key"
              type="password"
              autoComplete="off"
              spellCheck={false}
              disabled={disabled}
              value={key}
              onChange={(e) => setKey(e.target.value)}
            />
          </Field>
          <Button type="submit" disabled={disabled || key.trim().length < 20}>
            Save key
          </Button>
          {(status.source === "database" || status.source === "unreadable") && (
            <Button
              type="button"
              variant="ghost"
              onClick={() => setConfirming("clear")}
            >
              Remove saved key
            </Button>
          )}
        </form>
      </CardContent>
      <PasswordDialog
        open={confirming === "save"}
        onOpenChange={(open) => !open && setConfirming(null)}
        title="Save the OpenAI API key?"
        description="It replaces the key every answer, upload and evaluation uses."
        confirmLabel="Save key securely"
        onConfirm={async (password) => {
          apply(await adminApi.setOpenaiKey(key.trim(), password))
          setKey("")
          toast.success("API key saved")
        }}
      />
      <PasswordDialog
        open={confirming === "clear"}
        onOpenChange={(open) => !open && setConfirming(null)}
        title="Remove the saved key?"
        description="The installation falls back to RAG_OPENAI_API_KEY from deploy/.env, if set."
        confirmLabel="Remove key"
        destructive
        onConfirm={async (password) => {
          apply(await adminApi.clearOpenaiKey(password))
          toast.success("Saved key removed")
        }}
      />
    </Card>
  )
}

export default function SettingsPage() {
  return (
    <>
      <PageHeader
        title="Settings"
        description="Installation-wide settings. Cost caps and the fallback model are versioned with the RAG config."
      />
      <SuperAdminOnly>
        <div className="grid gap-6">
          <BrandingCard />
          <OpenAIKeyCard />
        </div>
      </SuperAdminOnly>
    </>
  )
}
