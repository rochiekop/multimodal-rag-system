import { expect, test } from "@playwright/test"

const username = process.env.E2E_USERNAME ?? "root"
const password = process.env.E2E_PASSWORD ?? "root-password-123"

test("sign in, ask, see a cited answer and open its page", async ({ page }) => {
  await page.goto("/app")
  await expect(page).toHaveURL(/\/login/) // no session yet

  await page.getByLabel("Username").fill(username)
  await page.getByLabel("Password").fill(password)
  await page.getByRole("button", { name: "Sign in" }).click()
  await expect(page).toHaveURL(/\/app/)

  await page.getByPlaceholder("Ask a question").fill("How many days of annual leave do employees get?")
  await page.keyboard.press("Enter")

  const citation = page.getByRole("button", { name: /^Source 1:/ })
  await expect(citation).toBeVisible({ timeout: 90_000 })
  await expect(page.getByText(/twenty/i).first()).toBeVisible()
  await expect(page).toHaveURL(/\/app\/c\//)

  await citation.click()
  await expect(page.getByRole("img", { name: /^Page 1 of / })).toBeVisible()
  await expect(page.getByTestId("source-highlight")).toBeVisible()

  await page.keyboard.press("Escape")
  await page.getByRole("button", { name: "Good answer" }).click()
  await expect(page.getByText("Thanks for the feedback")).toBeVisible()
})
