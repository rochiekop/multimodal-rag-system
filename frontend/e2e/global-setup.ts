import path from "node:path"
import { readFile } from "node:fs/promises"

import { request, type FullConfig } from "@playwright/test"

const CSRF = { "X-CSRF-Protection": "1" }
const GROUP = "e2e-staff"
const COLLECTION = "E2E Handbook"
const PDF = "leave-policy.pdf"

/** Seeds what the specs need, idempotently: the e2e user in a group that can see a collection
 * holding a leave-policy PDF that is fully ingested. */
export default async function globalSetup(config: FullConfig) {
  const baseURL = config.projects[0].use.baseURL!
  const api = await request.newContext({
    baseURL,
    ignoreHTTPSErrors: config.projects[0].use.ignoreHTTPSErrors,
  })
  const login = await api.post("/api/auth/session", {
    data: {
      username: process.env.E2E_USERNAME ?? "root",
      password: process.env.E2E_PASSWORD ?? "root-password-123",
    },
  })
  if (!login.ok()) throw new Error(`e2e login failed: ${login.status()}`)
  const me = await (await api.get("/api/auth/me")).json()

  const groups: { id: string; name: string }[] = await (await api.get("/api/admin/groups")).json()
  let group = groups.find((g) => g.name === GROUP)
  if (!group) {
    group = await (
      await api.post("/api/admin/groups", { headers: CSRF, data: { name: GROUP, description: "" } })
    ).json()
  }
  const myGroups: string[] = me.groups.map((g: { id: string }) => g.id)
  if (!myGroups.includes(group!.id)) {
    await api.patch(`/api/admin/users/${me.id}`, {
      headers: CSRF,
      data: { group_ids: [...myGroups, group!.id] },
    })
  }

  const collections: { id: string; name: string }[] = await (
    await api.get("/api/admin/collections")
  ).json()
  let collection = collections.find((c) => c.name === COLLECTION)
  if (!collection) {
    collection = await (
      await api.post("/api/admin/collections", {
        headers: CSRF,
        data: { name: COLLECTION, description: "", group_ids: [group!.id], sensitive: false },
      })
    ).json()
  }

  const buffer = await readFile(path.join(import.meta.dirname, "fixtures", PDF))
  await api.post(`/api/admin/collections/${collection!.id}/documents`, {
    headers: CSRF,
    multipart: { files: { name: PDF, mimeType: "application/pdf", buffer } },
  }) // a duplicate on reruns is fine

  const deadline = Date.now() + 240_000
  for (;;) {
    const docs: { filename: string; versions: { status: string; version_no: number }[] }[] = await (
      await api.get(`/api/admin/collections/${collection!.id}/documents`)
    ).json()
    const versions = docs.find((d) => d.filename === PDF)?.versions ?? []
    const latest = versions.reduce<(typeof versions)[number] | undefined>(
      (a, v) => (!a || v.version_no > a.version_no ? v : a),
      undefined,
    )
    const status = latest?.status
    if (status === "ready") break
    if (status === "failed" || status === "rejected" || Date.now() > deadline)
      throw new Error(`seed document not ready: ${status ?? "missing"}`)
    await new Promise((r) => setTimeout(r, 3000))
  }
  await api.dispose()
}
