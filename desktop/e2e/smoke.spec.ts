import { test, expect } from "@playwright/test";

test("the app shell renders and degrades without a Tauri backend", async ({
  page,
}) => {
  await page.goto("/");

  // The header + tab navigation render.
  await expect(page.getByRole("heading", { name: "yeaboi.ai" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Monitor" })).toBeVisible();
  await expect(page.getByRole("button", { name: "PRs" })).toBeVisible();

  // No Tauri bridge in a plain browser → the monitor stays in its connecting
  // state rather than erroring. (The header also shows a lowercase "connecting…",
  // so match the monitor's capitalized one exactly.)
  await expect(page.getByText("Connecting…", { exact: true })).toBeVisible();

  // The PRs tab switches without a backend and shows its empty state.
  await page.getByRole("button", { name: "PRs" }).click();
  await expect(page.getByText(/no projects/i)).toBeVisible();
});
