"use client"

import { useQuery } from "@tanstack/react-query"
import { LibraryIcon } from "lucide-react"

import { Button } from "@/components/ui/button"
import {
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { api } from "@/lib/api"

export function CollectionPicker({
  value,
  onChange,
}: {
  value: string[]
  onChange: (ids: string[]) => void
}) {
  const { data = [] } = useQuery({
    queryKey: ["collections"],
    queryFn: api.collections,
  })
  const label =
    value.length === 0
      ? "All collections"
      : value.length === 1
        ? (data.find((c) => c.id === value[0])?.name ?? "1 collection")
        : `${value.length} collections`
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
          variant="ghost"
          size="sm"
          className="gap-1 text-muted-foreground"
        >
          <LibraryIcon /> {label}
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start" className="w-64">
        <DropdownMenuLabel>Search in</DropdownMenuLabel>
        <DropdownMenuSeparator />
        {data.length === 0 && (
          <p className="px-2 py-1.5 text-sm text-muted-foreground">
            No collections available
          </p>
        )}
        {data.map((c) => (
          <DropdownMenuCheckboxItem
            key={c.id}
            checked={value.includes(c.id)}
            onSelect={(e) => e.preventDefault()}
            onCheckedChange={(checked) =>
              onChange(
                checked ? [...value, c.id] : value.filter((id) => id !== c.id)
              )
            }
          >
            {c.name}
          </DropdownMenuCheckboxItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
