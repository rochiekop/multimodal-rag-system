import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import type { ColumnDef } from "@tanstack/react-table"
import { describe, expect, it } from "vitest"

import { DataTable } from "@/components/admin/data-table"

type Row = { id: string; name: string }
const data: Row[] = [{ id: "1", name: "Alpha" }]

// Built inline on every call, like a page's render body does.
const buildColumns = (): ColumnDef<Row>[] => [
  { accessorKey: "name", header: () => "Name" },
  { id: "act", header: "Actions", cell: () => <button>Act</button> },
]

describe("DataTable", () => {
  it("keeps cell DOM (and focus) across re-renders with new column identities", async () => {
    const { rerender } = render(
      <DataTable columns={buildColumns()} data={data} getRowId={(r) => r.id} />
    )
    const button = screen.getByRole("button", { name: "Act" })
    await userEvent.setup().click(button)
    button.focus()
    expect(document.activeElement).toBe(button)
    rerender(
      <DataTable columns={buildColumns()} data={data} getRowId={(r) => r.id} />
    )
    expect(screen.getByRole("button", { name: "Act" })).toBe(button)
    expect(document.activeElement).toBe(button)
  })
})
