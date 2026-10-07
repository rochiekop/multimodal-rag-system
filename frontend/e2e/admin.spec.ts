import path from "node:path"

import { expect, test } from "@playwright/test"

const username = process.env.E2E_USERNAME ?? "root"
const password = process.env.E2E_PASSWORD ?? "root-password-123"

test("admin creates a collection, uploads a document and sees it become ready", async ({ page }) => {
  await page.goto("/admin")
  await expect(page).toHaveURL(/\/login/)
  await page.getByLabel("Username").fill(username)
  await page.getByLabel("Password").fill(password)
  await page.getByRole("button", { name: "Sign in" }).click()
  await expect(page.getByRole("heading", { name: "Dashboard" })).toBeVisible()

  const name = `E2E ${Date.now()}`
  await page.getByRole("link", { name: "Collections & access" }).click()
  await page.getByRole("button", { name: "New collection" }).click()
  await page.getByLabel("Name").fill(name)
  await page.getByRole("button", { name: "Save" }).click()
  await expect(page.getByText(name)).toBeVisible()

  await page.getByRole("link", { name: "Documents" }).click()
  await page.getByLabel("Collection").selectOption({ label: name })
  await page
    .getByLabel("Upload files")
    .setInputFiles(path.join(import.meta.dirname, "fixtures", "e2e-handbook.md"))
  await expect(page.getByText("1 of 1 files queued for processing")).toBeVisible()
  const row = page.getByRole("row", { name: /e2e-handbook\.md/ })
  await expect(row.getByText("Ready")).toBeVisible({ timeout: 180_000 })

  await row.getByRole("button", { name: "e2e-handbook.md" }).click()
  await expect(page.getByText(/premium economy/)).toBeVisible()
  await page.keyboard.press("Escape")

  await page.getByRole("link", { name: "Audit log" }).click()
  await page.getByLabel("Action starts with").fill("document.")
  await page.getByRole("button", { name: "Apply" }).click()
  await expect(page.getByRole("cell", { name: "document.uploaded" }).first()).toBeVisible()
})
