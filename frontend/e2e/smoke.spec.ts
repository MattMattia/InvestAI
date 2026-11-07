import { expect, test } from "@playwright/test";

test("home page renders without uncaught exceptions", async ({ page }) => {
  const pageErrors: Error[] = [];
  page.on("pageerror", (error) => pageErrors.push(error));

  await page.goto("/");

  const root = page.locator("#root");
  await expect(root.locator("> *").first()).toBeVisible();
  expect(await root.locator("*").count()).toBeGreaterThan(0);

  expect(pageErrors, pageErrors.map((e) => e.message).join("\n")).toEqual([]);
});
