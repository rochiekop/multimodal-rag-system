"use client"

import { Checkbox } from "@/components/ui/checkbox"
import { Label } from "@/components/ui/label"
import type { Group } from "@/lib/types"

/** Multi-select checkboxes over `{id, name}` items (groups, or collections); `value` holds ids. */
export function GroupChecklist({
  groups,
  value,
  onChange,
  idPrefix,
  empty = "No groups yet. Create one first.",
}: {
  groups: Group[]
  value: string[]
  onChange: (ids: string[]) => void
  idPrefix: string
  empty?: string
}) {
  if (groups.length === 0)
    return <p className="text-sm text-muted-foreground">{empty}</p>
  return (
    <div className="grid max-h-48 gap-2 overflow-y-auto">
      {groups.map((group) => {
        const id = `${idPrefix}-${group.id}`
        const checked = value.includes(group.id)
        return (
          <div key={group.id} className="flex items-center gap-2">
            <Checkbox
              id={id}
              checked={checked}
              onCheckedChange={(next) =>
                onChange(
                  next === true
                    ? [...value, group.id]
                    : value.filter((g) => g !== group.id)
                )
              }
            />
            <Label htmlFor={id}>{group.name}</Label>
          </div>
        )
      })}
    </div>
  )
}
