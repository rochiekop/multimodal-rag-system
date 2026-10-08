"use client"

import { zodResolver } from "@hookform/resolvers/zod"
import { useEffect, useState } from "react"
import {
  Controller,
  useFieldArray,
  useForm,
  type Control,
} from "react-hook-form"
import { toast } from "sonner"
import { z } from "zod"

import { ActivateDialog } from "@/components/admin/activate-dialog"
import { PageHeader } from "@/components/admin/page-header"
import { SuperAdminOnly } from "@/components/admin/super-admin-only"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { Field, FieldError, FieldLabel } from "@/components/ui/field"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { NativeSelect, NativeSelectOption } from "@/components/ui/native-select"
import { Switch } from "@/components/ui/switch"
import { Textarea } from "@/components/ui/textarea"
import { ApiError } from "@/lib/api"
import {
  useActiveConfig,
  useConfigVersions,
  useCreateVersion,
} from "@/lib/config-version"
import {
  MODERATION_CATEGORIES,
  type GuardrailSettings,
  type RagConfigVersion,
} from "@/lib/types"

const action = z.enum(["block", "flag", "off"])
const schema = z.object({
  rate_limit_per_minute: z.number().int().min(1).max(600),
  max_question_chars: z.number().int().min(10).max(4000),
  moderation: z.object(
    Object.fromEntries(MODERATION_CATEGORIES.map((c) => [c, action])) as Record<
      (typeof MODERATION_CATEGORIES)[number],
      typeof action
    >
  ),
  self_harm_support: z.boolean(),
  injection_check: z.boolean(),
  exfiltration_check: z.boolean(),
  scope_check: z.boolean(),
  scope_description: z.string().max(1000),
  classifier_model: z.string().trim().min(1).max(100),
  blocked_message: z.string().min(1).max(1000),
  off_topic_message: z.string().min(1).max(1000),
  support_message: z.string().min(1).max(2000),
  pii_redaction: z.boolean(),
  pii_patterns: z
    .array(
      z.object({
        name: z
          .string()
          .regex(/^[a-z0-9_]+$/, "Lowercase letters, digits and _")
          .max(50),
        regex: z.string().min(1).max(300),
      })
    )
    .max(20),
  system_prompt_leak_check: z.boolean(),
  groundedness_check: z.boolean(),
  judge_model: z.string().trim().min(1).max(100),
  strike_limit: z.number().int().min(1).max(20),
  strike_window_hours: z.number().int().min(1).max(720),
  strike_lock_hours: z.number().int().min(1).max(720),
  user_daily_cost_usd: z.number().min(0),
  installation_daily_cost_usd: z.number().min(0),
  cost_alert_ratio: z.number().gt(0).max(1),
})
type Values = z.infer<typeof schema>
type BoolKey = {
  [K in keyof Values]: Values[K] extends boolean ? K : never
}[keyof Values]
type NumberKey = {
  [K in keyof Values]: Values[K] extends number ? K : never
}[keyof Values]
type TextKey = Extract<
  keyof Values,
  | "scope_description"
  | "classifier_model"
  | "judge_model"
  | "blocked_message"
  | "off_topic_message"
  | "support_message"
>

const CATEGORY_LABELS: Record<string, string> = {
  violence: "Violence",
  hate: "Hate",
  harassment: "Harassment",
  sexual: "Sexual",
  illegal: "Illegal activity",
  weapons: "Weapons",
  self_harm: "Self-harm",
}

function Toggle({
  control,
  name,
  label,
}: {
  control: Control<Values>
  name: BoolKey
  label: string
}) {
  return (
    <Controller
      control={control}
      name={name}
      render={({ field }) => (
        <div className="flex items-center gap-2">
          <Switch
            id={`gr-${name}`}
            checked={field.value}
            onCheckedChange={field.onChange}
          />
          <Label htmlFor={`gr-${name}`}>{label}</Label>
        </div>
      )}
    />
  )
}

function GuardrailsEditor() {
  const active = useActiveConfig()
  const versions = useConfigVersions()
  const create = useCreateVersion()
  const [note, setNote] = useState("")
  const [saved, setSaved] = useState<RagConfigVersion | null>(null)
  const [activating, setActivating] = useState<RagConfigVersion | null>(null)
  const [formError, setFormError] = useState<string | null>(null)
  const form = useForm<Values>({ resolver: zodResolver(schema) })
  const { register, control, formState } = form
  const patterns = useFieldArray({ control, name: "pii_patterns" })

  useEffect(() => {
    if (active.data) form.reset(active.data.config.guardrails)
  }, [active.data, form])

  async function onSubmit(values: Values) {
    if (!active.data) return
    setFormError(null)
    try {
      const version = await create.mutateAsync({
        config: {
          ...active.data.config,
          guardrails: values as GuardrailSettings,
        },
        note: note || "Guardrail settings",
      })
      setSaved(version)
      toast.success(`Saved as v${version.version}. Activate it to use it.`)
    } catch (error) {
      setFormError(
        error instanceof ApiError ? error.message : "Could not save. Try again."
      )
    }
  }

  const number = (name: NumberKey, label: string, step = "1") => (
    <Field data-invalid={!!formState.errors[name]}>
      <FieldLabel htmlFor={`gr-${name}`}>{label}</FieldLabel>
      <Input
        id={`gr-${name}`}
        type="number"
        step={step}
        {...register(name, { valueAsNumber: true })}
      />
      <FieldError errors={[formState.errors[name]]} />
    </Field>
  )
  const text = (name: TextKey, label: string, rows = 0) => (
    <Field data-invalid={!!formState.errors[name]}>
      <FieldLabel htmlFor={`gr-${name}`}>{label}</FieldLabel>
      {rows ? (
        <Textarea id={`gr-${name}`} rows={rows} {...register(name)} />
      ) : (
        <Input id={`gr-${name}`} {...register(name)} />
      )}
      <FieldError errors={[formState.errors[name]]} />
    </Field>
  )

  if (!active.data)
    return <p className="text-sm text-muted-foreground">Loading…</p>
  return (
    <>
      <form className="grid gap-4" onSubmit={form.handleSubmit(onSubmit)}>
        <p className="text-sm text-muted-foreground">
          New versions start from the active configuration (
          {active.data.version ? `v${active.data.version}` : "defaults"}).
        </p>
        <Card>
          <CardHeader>
            <CardTitle>Input checks</CardTitle>
            <CardDescription>
              Run before retrieval; blocked questions never reach the model.
            </CardDescription>
          </CardHeader>
          <CardContent className="grid gap-4 md:grid-cols-2">
            {number("rate_limit_per_minute", "Questions per minute per user")}
            {number("max_question_chars", "Max question length (characters)")}
            <Toggle
              control={control}
              name="injection_check"
              label="Prompt-injection check"
            />
            <Toggle
              control={control}
              name="exfiltration_check"
              label="Exfiltration check (sensitive collections)"
            />
            <Toggle control={control} name="scope_check" label="Scope check" />
            {text("classifier_model", "Classifier model")}
            <div className="md:col-span-2">
              {text("scope_description", "In-scope topics", 2)}
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>Content moderation</CardTitle>
          </CardHeader>
          <CardContent className="grid gap-4 md:grid-cols-3">
            {MODERATION_CATEGORIES.map((category) => (
              <Field key={category}>
                <FieldLabel htmlFor={`gr-mod-${category}`}>
                  {CATEGORY_LABELS[category]}
                </FieldLabel>
                <NativeSelect
                  id={`gr-mod-${category}`}
                  {...register(`moderation.${category}`)}
                >
                  <NativeSelectOption value="block">Block</NativeSelectOption>
                  <NativeSelectOption value="flag">
                    Flag for review
                  </NativeSelectOption>
                  <NativeSelectOption value="off">Off</NativeSelectOption>
                </NativeSelect>
              </Field>
            ))}
            <div className="md:col-span-3">
              <Toggle
                control={control}
                name="self_harm_support"
                label="Answer self-harm messages with support resources"
              />
            </div>
            <div className="md:col-span-3">
              {text("support_message", "Support message", 3)}
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>Output checks</CardTitle>
          </CardHeader>
          <CardContent className="grid gap-4">
            <div className="grid gap-4 md:grid-cols-2">
              <Toggle
                control={control}
                name="pii_redaction"
                label="PII redaction"
              />
              <Toggle
                control={control}
                name="system_prompt_leak_check"
                label="System-prompt leak check"
              />
              <Toggle
                control={control}
                name="groundedness_check"
                label="Groundedness check"
              />
              {text("judge_model", "Judge model")}
            </div>
            <div className="grid gap-2">
              <Label>Company identifiers to redact</Label>
              {patterns.fields.map((field, index) => (
                <div
                  key={field.id}
                  className="grid gap-2 md:grid-cols-[1fr_2fr_auto]"
                >
                  <Input
                    aria-label={`Pattern ${index + 1} name`}
                    placeholder="employee_number"
                    {...register(`pii_patterns.${index}.name`)}
                  />
                  <Input
                    aria-label={`Pattern ${index + 1} regex`}
                    className="font-mono"
                    placeholder="\bEMP-\d{6}\b"
                    {...register(`pii_patterns.${index}.regex`)}
                  />
                  <Button
                    type="button"
                    variant="ghost"
                    onClick={() => patterns.remove(index)}
                  >
                    Remove
                  </Button>
                  <FieldError
                    className="md:col-span-3"
                    errors={[
                      formState.errors.pii_patterns?.[index]?.name,
                      formState.errors.pii_patterns?.[index]?.regex,
                    ]}
                  />
                </div>
              ))}
              <div>
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={() => patterns.append({ name: "", regex: "" })}
                >
                  Add pattern
                </Button>
              </div>
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>Accounts and cost</CardTitle>
          </CardHeader>
          <CardContent className="grid gap-4 md:grid-cols-3">
            {number("strike_limit", "Strikes before a lock")}
            {number("strike_window_hours", "Strike window (hours)")}
            {number("strike_lock_hours", "Lock length (hours)")}
            {number(
              "user_daily_cost_usd",
              "Daily cost cap per user (USD, 0 = off)",
              "0.01"
            )}
            {number(
              "installation_daily_cost_usd",
              "Daily cost cap, whole installation (USD, 0 = off)",
              "0.01"
            )}
            {number(
              "cost_alert_ratio",
              "Alert at this share of a cap (0–1)",
              "0.05"
            )}
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>Messages</CardTitle>
          </CardHeader>
          <CardContent className="grid gap-4 md:grid-cols-2">
            {text("blocked_message", "Blocked message", 2)}
            {text("off_topic_message", "Off-topic message", 2)}
          </CardContent>
        </Card>
        <Field>
          <FieldLabel htmlFor="gr-note">Note</FieldLabel>
          <Input
            id="gr-note"
            value={note}
            onChange={(e) => setNote(e.target.value)}
          />
        </Field>
        {formError && (
          <p role="alert" className="text-sm text-destructive">
            {formError}
          </p>
        )}
        <div className="flex flex-wrap gap-2">
          <Button type="submit" disabled={create.isPending}>
            Save as new version
          </Button>
          {saved && (
            <Button
              type="button"
              variant="outline"
              onClick={() => setActivating(saved)}
            >
              Activate v{saved.version}
            </Button>
          )}
        </div>
      </form>
      {/* Outside the form: React portals still bubble submit events to ancestors. */}
      <ActivateDialog
        target={activating}
        versions={versions.data ?? []}
        onOpenChange={(open) => {
          if (!open) setActivating(null)
        }}
      />
    </>
  )
}

export default function GuardrailsPage() {
  return (
    <>
      <PageHeader
        title="Guardrails"
        description="Checks on questions and answers. Changes are saved as a new RAG config version."
      />
      <SuperAdminOnly>
        <GuardrailsEditor />
      </SuperAdminOnly>
    </>
  )
}
