import { expect, test, type Page } from "@playwright/test";

/** A "photo" of a page lying crooked on a dark table, drawn in the browser. */
async function photoOfPaper(page: Page, words: string): Promise<Buffer> {
  const dataUrl = await page.evaluate((text) => {
    const c = document.createElement("canvas");
    c.width = 1600; c.height = 1200;
    const g = c.getContext("2d")!;
    g.fillStyle = "#3a2e26"; g.fillRect(0, 0, 1600, 1200);
    g.translate(800, 600); g.rotate(-0.12);
    g.fillStyle = "#f4f1ea"; g.fillRect(-420, -560, 840, 1120);
    g.fillStyle = "#111"; g.font = "bold 64px sans-serif";
    g.fillText(text, -360, -300);
    g.font = "44px sans-serif";
    g.fillText("Paid in full", -360, -180);
    return c.toDataURL("image/jpeg", 0.92);
  }, words);
  return Buffer.from(dataUrl.split(",")[1], "base64");
}

test("scan a page: it's found, straightened, saved as a searchable PDF", async ({ page }) => {
  const id = Date.now().toString().slice(-6);
  await page.goto("/files");
  await page.getByRole("link", { name: "Scan" }).click();
  await expect(page.getByRole("heading", { name: "Scan documents" })).toBeVisible();
  const photo = await photoOfPaper(page, `Water bill ${id}`);
  await page.locator('input[type="file"][multiple]').setInputFiles({ name: "IMG_scan.jpg", mimeType: "image/jpeg", buffer: photo });

  // the paper was found: the first corner sits on the paper, not on the edge of the photo
  const handle = page.getByRole("button", { name: "Corner 1" });
  await expect(handle).toBeVisible();
  const canvas = await page.getByRole("img", { name: "The photo of the page" }).boundingBox();
  const corner = await handle.boundingBox();
  expect((corner!.x - canvas!.x) / canvas!.width).toBeGreaterThan(0.15);
  await page.getByLabel("Black and white").check();
  await page.getByRole("button", { name: "Done with this page" }).click();

  await page.getByLabel("Name").fill(`Water bill ${id}`);
  await page.getByRole("button", { name: /Save as PDF \(1 pages\)/ }).click();
  await expect(page.getByText(`Saved Water bill ${id}.pdf`)).toBeVisible({ timeout: 60_000 });
  await expect(page).toHaveURL(/\/files\/Scans$/);

  // the words on the paper find it
  await page.getByLabel("Search files").fill(id);
  const hit = page.locator(".search-hits li").first();
  await expect(hit).toContainText(`Water bill ${id}.pdf`);
  await page.getByLabel("Search files").fill("paid in full");
  await expect(page.locator(".search-hits li", { hasText: `Water bill ${id}.pdf` }).locator(".hit-snippet")).toContainText(/paid in full/i);
});
