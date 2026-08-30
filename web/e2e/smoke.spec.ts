/** One smoke test (#77; ADR-0006 D15): sign in, open a saved chart, assert
 * a canvas rendered with the expected series count. #9 adds exactly one
 * assertion: revert to an earlier revision and the drawn series count
 * changes. The suite does not grow a second life.
 */

import path from "node:path";
import { fileURLToPath } from "node:url";

import { clerk } from "@clerk/testing/playwright";
import { expect, test } from "@playwright/test";

const SALES_CSV = path.join(path.dirname(fileURLToPath(import.meta.url)), "fixtures", "sales.csv");

const FRAME = `{
  "chart_spec": {
    "chartType": "Bar Chart",
    "encodings": {
      "x": { "field": "quarter" },
      "y": { "field": "revenue" }
    }
  }
}`;

const GROUPED_FRAME = `{
  "chart_spec": {
    "chartType": "Grouped Bar Chart",
    "encodings": {
      "x": { "field": "quarter" },
      "y": { "field": "revenue" },
      "group": { "field": "quarter" }
    }
  }
}`;

test("a saved chart draws a canvas with the expected series count", async ({ page }) => {
  if (process.env.CI && (!process.env.E2E_CLERK_USER_EMAIL || !process.env.CLERK_SECRET_KEY)) {
    throw new Error("E2E_CLERK_USER_EMAIL and CLERK_SECRET_KEY are required in CI");
  }
  test.skip(
    !process.env.E2E_CLERK_USER_EMAIL || !process.env.CLERK_SECRET_KEY,
    "Clerk e2e credentials are not set",
  );

  // Sign-in is unprotected and loads Clerk; then the helper mints a session.
  await page.goto("/sign-in");
  await clerk.signIn({
    page,
    emailAddress: process.env.E2E_CLERK_USER_EMAIL,
  });

  await page.goto("/charts/new");
  await page.getByRole("button", { name: "Add source" }).click();
  await page.locator('input[type="file"]').setInputFiles(SALES_CSV);
  await expect(page.getByLabel("Data source")).not.toHaveValue("", { timeout: 15_000 });

  await page.getByLabel(/input frame/i).fill(FRAME);
  await page.getByRole("button", { name: /bind & draw/i }).click();
  await expect(page.locator(".chart-area")).toHaveAttribute("data-state", "rendered", {
    timeout: 60_000,
  });

  await page.getByRole("button", { name: "Save" }).click();
  await page.waitForURL(/\/charts\/[0-9a-f-]{36}$/i, { timeout: 15_000 });
  const chartPath = new URL(page.url()).pathname;

  // Leave the preview so "open a saved chart" cannot pass on leftover canvas.
  await page.goto("/");
  await expect(page.locator(`a[href="${chartPath}"]`)).toBeVisible({ timeout: 15_000 });
  await page.locator(`a[href="${chartPath}"]`).click();
  await page.waitForURL(`**${chartPath}`);

  await expect(page.locator(".chart-area")).toHaveAttribute("data-state", "rendered", {
    timeout: 60_000,
  });
  await expect(page.locator(".chart-area canvas")).toBeVisible();
  await expect(page.locator(".chart-area")).toHaveAttribute("data-series-count", "1");

  // A second revision that draws two series, then revert to the first.
  await page.getByLabel(/input frame/i).fill(GROUPED_FRAME);
  await page.getByRole("button", { name: "Save" }).click();
  await page.locator(".chart-toolbar .revision-chip", { hasText: "rev 2" }).waitFor({
    timeout: 15_000,
  });
  await page.getByRole("button", { name: "Refresh" }).click();
  await page.locator(".chart-area[data-series-count='2']").waitFor({ timeout: 60_000 });

  await page.getByRole("button", { name: "History" }).click();
  await page.getByRole("button", { name: "Revert to revision 1" }).click();
  await page.getByText("Refresh to bind").waitFor();
  await page.getByRole("button", { name: "Refresh" }).click();
  await expect(page.locator(".chart-area")).toHaveAttribute("data-series-count", "1", {
    timeout: 60_000,
  });
});
