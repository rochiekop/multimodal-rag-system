import { PageHeader } from "@/components/admin/page-header"
import { CompareView } from "@/components/admin/compare-view"

export default async function ComparePage({
  searchParams,
}: {
  searchParams: Promise<{ a?: string; b?: string }>
}) {
  const { a, b } = await searchParams
  return (
    <>
      <PageHeader
        title="Compare runs"
        description="Per-question changes from A (baseline) to B."
      />
      <CompareView a={a} b={b} />
    </>
  )
}
