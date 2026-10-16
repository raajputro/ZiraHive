import { expect, test } from "@playwright/test";

test.beforeEach(async ({ page }) => {
  const libs = await (await page.request.get("/api/libraries")).json();
  test.skip(!libs.some((l: { kind: string; item_count: number }) => l.kind === "books" && l.item_count > 0),
    "No books on this server (scripts/make-sample-media.sh makes some)");
});

async function bookId(page: import("@playwright/test").Page, title: string) {
  const books = await (await page.request.get(`/api/books?kind=reading&q=${encodeURIComponent(title)}`)).json();
  const b = books.find((x: { title: string }) => x.title === title);
  await page.request.delete(`/api/books/${b.id}/progress`);
  return b.id as string;
}

test("read an EPUB: turn pages, change the text, come back to the same place", async ({ page }) => {
  const errors: string[] = [];
  page.on("console", (m) => { if (m.type() === "error" && /Content.Security.Policy|Refused/i.test(m.text())) errors.push(m.text()); });
  const id = await bookId(page, "The River Journey");
  await page.goto("/read");
  await page.getByRole("link", { name: /The River Journey/ }).first().click();
  const frame = page.frameLocator(".epub-host iframe");
  await expect(frame.getByRole("heading", { name: "Chapter 1" })).toBeVisible({ timeout: 15_000 });

  await page.getByRole("button", { name: "Contents" }).click();
  await page.getByRole("button", { name: "Chapter 3" }).click();
  await expect(frame.getByRole("heading", { name: "Chapter 3" })).toBeVisible();
  await page.getByRole("button", { name: "Next page" }).click();

  await page.getByRole("button", { name: "Reading settings" }).click();
  await page.getByRole("button", { name: "Sepia" }).click();
  await page.getByRole("button", { name: "Larger text" }).click();
  await expect(page.locator(".reader")).toHaveClass(/theme-sepia/);

  await expect.poll(async () => (await (await page.request.get(`/api/books/${id}`)).json()).progress?.locator ?? "",
    { timeout: 8000 }).toContain("epubcfi");
  await page.getByRole("button", { name: "Close the book" }).click();
  await page.goto(`/read/book/${id}`);
  await expect(frame.getByText(/chapter 3/i).first()).toBeVisible({ timeout: 15_000 });
  expect(errors).toEqual([]);
});

test("read a PDF page by page", async ({ page }) => {
  const id = await bookId(page, "Cooking with Mustard Oil");
  await page.goto(`/read/book/${id}`);
  await expect(page.getByRole("img", { name: "Page 1 of 4" })).toBeVisible({ timeout: 15_000 });
  await page.keyboard.press("ArrowRight");
  await expect(page.getByRole("img", { name: "Page 2 of 4" })).toBeVisible();
  await expect(page.getByText("Page 2 of 4", { exact: true })).toBeVisible();
});

test("read a comic, including right-to-left manga and scrolling", async ({ page }) => {
  const id = await bookId(page, "Sky Rider #1: Issue 1");
  await page.goto(`/read/book/${id}`);
  await expect(page.getByRole("img", { name: "Page 1 of 12" })).toBeVisible();
  await page.getByRole("button", { name: "Next page" }).click();
  await page.getByRole("button", { name: "Next page" }).click();
  await expect(page.getByRole("img", { name: "Page 3 of 12" })).toBeVisible();
  await expect.poll(async () => (await (await page.request.get(`/api/books/${id}`)).json()).progress?.position ?? 0).toBe(3);

  await page.getByRole("button", { name: "Reading settings" }).click();
  await page.getByLabel("Layout").selectOption("scroll");
  await expect(page.locator(".comic-scroll img")).toHaveCount(12);

  const manga = await bookId(page, "Moon Cat #1: Issue 1");
  await page.goto(`/read/book/${manga}`);
  await page.getByRole("button", { name: "Reading settings" }).click();
  await page.getByLabel("Layout").selectOption("pages");
  await expect(page.getByLabel("Right to left (manga)")).toBeChecked();
  await page.getByRole("button", { name: "Close", exact: true }).click();
  // in a manga, the left side goes forward
  await page.locator(".tap-zone.left").click();
  await expect(page.getByRole("img", { name: "Page 2 of 5" })).toBeVisible();
});
