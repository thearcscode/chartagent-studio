/** One smoke test (#77; ADR-0006 D15): sign in, open a saved chart, assert
 * a canvas rendered with the expected series count. #9 adds exactly one
 * assertion: revert to an earlier revision and the drawn series count
 * changes. #33 adds steps for the custom-rail page; #41 adds steps that open
 * a saved custom chart; #42 refreshes it against a changed source. The suite does not grow a second life.
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

const CUSTOM_RECIPE = {
  spec_version: "1.2",
  transform: {
    filter: {
      kind: "gt",
      args: [
        { kind: "col", name: "revenue" },
        { kind: "lit", value: 50 },
      ],
    },
  },
  source_schema: { revenue: "number" },
  escape_reason: { bucket: 1 },
  theme_spec: null,
  document: {
    module: `var plotted = [];
window.render = function (data, el) {
  el.textContent = data.length + " rows";
  plotted = [{ name: "revenue", x: "quarter", y: "revenue", points: data.length }];
};
window.getPlottedSeries = function () { return plotted; };`,
    styles: null,
    libraries: [],
    contract_version: 1,
  },
};

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

  const sourceId = await page.getByLabel("Data source").inputValue();

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

  // #33: the custom rail's parent side, in a real opaque-origin iframe.
  await page.goto("/custom-rail");
  const frame = page.locator("iframe.paint-frame");
  await expect(frame).toHaveAttribute("sandbox", "allow-scripts");
  const signal = page.locator(".paint-signal");
  await expect(signal).toHaveAttribute("data-signal", "painted", { timeout: 15_000 });
  await expect(signal).toHaveAttribute("data-series-count", "1");
  await expect(signal).toContainText("Painted");
  await expect(signal).toHaveAttribute("data-paint-count", "1");

  await page.getByRole("button", { name: /(light|dark) theme/i }).click();
  await expect(signal).toHaveAttribute("data-paint-count", "2", { timeout: 15_000 });
  await expect(signal).toHaveAttribute("data-signal", "painted");

  await page.getByRole("button", { name: "throwing" }).click();
  await expect(signal).toHaveAttribute("data-signal", "failed", { timeout: 15_000 });
  await expect(signal).toContainText("Did not paint");
  await expect(signal).toContainText("The document reported that it did not paint");
  await expect(signal).not.toContainText("Painted");
  await expect(page).toHaveURL(/\/custom-rail\/throwing$/);

  // #41: a saved custom chart opens from the cache, in the same sandboxed
  // mount, with no backend picker.
  const customId = await page.evaluate(
    async ({ recipe, source }) => {
      const clerk = (window as unknown as { Clerk: { session: { getToken(): Promise<string> } } })
        .Clerk;
      const headers = {
        Authorization: `Bearer ${await clerk.session.getToken()}`,
        "Content-Type": "application/json",
      };
      const created = await fetch("/api/specs", {
        method: "POST",
        headers,
        body: JSON.stringify({ content: recipe, source_id: source }),
      });
      if (!created.ok) throw new Error(`create failed: ${created.status}`);
      const chart = (await created.json()) as { id: string };
      const bound = await fetch(`/api/specs/${chart.id}/bind`, {
        method: "POST",
        headers,
        body: JSON.stringify({ trigger: "refresh" }),
      });
      if (!bound.ok) throw new Error(`refresh failed: ${bound.status}`);
      return chart.id;
    },
    { recipe: CUSTOM_RECIPE, source: sourceId },
  );
  await page.goto(`/charts/${customId}`);
  await expect(page.locator("iframe.paint-frame")).toHaveAttribute("sandbox", "allow-scripts");
  await expect(page.locator(".paint-signal")).toHaveAttribute("data-signal", "painted", {
    timeout: 15_000,
  });
  await expect(page.locator(".paint-signal")).toHaveAttribute("data-series-count", "1");
  await expect(page.getByRole("radiogroup", { name: "Backend" })).toHaveCount(0);

  // #42: refresh against a source whose rows differ repaints in place — a
  // second paint, no reload, and the as-of line moves.
  const changedSource = await page.evaluate(async () => {
    const clerk = (window as unknown as { Clerk: { session: { getToken(): Promise<string> } } })
      .Clerk;
    const form = new FormData();
    form.append(
      "file",
      new File(["quarter,revenue\nQ1,100\nQ2,200\nQ3,300\n"], "sales-changed.csv", {
        type: "text/csv",
      }),
    );
    const response = await fetch("/api/sources/upload", {
      method: "POST",
      headers: { Authorization: `Bearer ${await clerk.session.getToken()}` },
      body: form,
    });
    if (!response.ok) throw new Error(`upload failed: ${response.status}`);
    return ((await response.json()) as { id: string }).id;
  });
  await page.reload();
  const customSignal = page.locator(".paint-signal");
  await expect(customSignal).toHaveAttribute("data-signal", "painted", { timeout: 15_000 });
  await expect(customSignal).toHaveAttribute("data-paint-count", "1");
  const asOfBefore = await page.locator(".cost-line").textContent();
  await page.getByLabel("Data source").selectOption(changedSource);
  await page.getByRole("button", { name: "Refresh" }).click();
  await expect(customSignal).toHaveAttribute("data-paint-count", "2", { timeout: 15_000 });
  await expect(customSignal).toHaveAttribute("data-signal", "painted");
  await expect(page.frameLocator("iframe.paint-frame").locator("body")).toContainText("3 rows");
  await expect(page.locator(".cost-line")).toContainText("3 rows");
  expect(await page.locator(".cost-line").textContent()).not.toBe(asOfBefore);

  await page.goto("/custom-rail/nonesuch");
  await expect(page.getByText("Not found.")).toBeVisible();
  await expect(page.locator("iframe.paint-frame")).toHaveCount(0);
});
