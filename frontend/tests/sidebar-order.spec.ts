import { test, expect, type Page } from '@playwright/test';
import { loginAs } from './helpers/auth';
import { mockApi, makeArticle } from './helpers/mockApi';

// Haberler sidebar: each section has a ⠿ handle to drag it to another place (or ↑ / ↓ with the
// handle focused). The order is saved per user (PUT /auth/me/sidebar-order) and survives a reload.
const DEFAULT_LABELS = ['Kaynak Türü', 'RSS Beslemeleri', 'Önem Seviyesi', 'Kategoriler', 'Yayın Tarihi', 'İşlenme Tarihi'];

async function openNews(page: Page) {
  await page.goto('/');
  await page.getByRole('button', { name: 'Haberler', exact: true }).click();
}

const handle = (page: Page, label: string) => page.getByRole('button', { name: new RegExp(`^${label} bölümünü taşı`) });

/** Section titles in on-screen order, read from the handles' accessible names. */
async function sectionOrder(page: Page): Promise<string[]> {
  const names = await page.getByRole('button', { name: /bölümünü taşı/ }).evaluateAll(
    (els) => els.map((el) => el.getAttribute('aria-label') ?? ''),
  );
  return names.map((name) => name.replace(/ bölümünü taşı.*$/, ''));
}

test('the sidebar shows its sections in the default order for a user who never moved them', async ({ page }) => {
  await loginAs(page);
  await mockApi(page, { articles: [makeArticle()] });
  await openNews(page);

  await expect.poll(() => sectionOrder(page)).toEqual(DEFAULT_LABELS);
});

test('a saved order is applied, sections it does not list are appended', async ({ page }) => {
  await loginAs(page);
  await mockApi(page, { articles: [makeArticle()], sidebarOrder: ['topics', 'origin'] });
  await openNews(page);

  await expect.poll(() => sectionOrder(page)).toEqual(
    ['Kategoriler', 'Kaynak Türü', 'RSS Beslemeleri', 'Önem Seviyesi', 'Yayın Tarihi', 'İşlenme Tarihi'],
  );
});

test('dragging a section moves it, saves the order and keeps it after a reload', async ({ page }) => {
  await loginAs(page);
  const state = await mockApi(page, { articles: [makeArticle()] });
  await openNews(page);
  await expect.poll(() => sectionOrder(page)).toEqual(DEFAULT_LABELS);

  const saved = page.waitForRequest((r) => r.method() === 'PUT' && r.url().includes('/auth/me/sidebar-order'));
  // Drop "Kategoriler" onto the upper half of "Kaynak Türü": it lands above it, at the top.
  await handle(page, 'Kategoriler').dragTo(page.locator('[data-section-id="origin"]'), { targetPosition: { x: 40, y: 4 } });
  await saved;

  const expected = ['Kategoriler', 'Kaynak Türü', 'RSS Beslemeleri', 'Önem Seviyesi', 'Yayın Tarihi', 'İşlenme Tarihi'];
  await expect.poll(() => sectionOrder(page)).toEqual(expected);
  expect(state.sidebarOrderRequests).toEqual([['topics', 'origin', 'feeds', 'priority', 'published', 'fetched']]);

  await page.reload();
  await expect.poll(() => sectionOrder(page)).toEqual(expected);
});

test('the arrow keys move the section whose handle has focus', async ({ page }) => {
  await loginAs(page);
  const state = await mockApi(page, { articles: [makeArticle()] });
  await openNews(page);

  await handle(page, 'Kaynak Türü').focus();
  await page.keyboard.press('ArrowDown');
  await expect.poll(() => sectionOrder(page)).toEqual(
    ['RSS Beslemeleri', 'Kaynak Türü', 'Önem Seviyesi', 'Kategoriler', 'Yayın Tarihi', 'İşlenme Tarihi'],
  );
  // The focus follows the moved section, so a second press moves it further.
  await page.keyboard.press('ArrowDown');
  await expect.poll(() => sectionOrder(page)).toEqual(
    ['RSS Beslemeleri', 'Önem Seviyesi', 'Kaynak Türü', 'Kategoriler', 'Yayın Tarihi', 'İşlenme Tarihi'],
  );
  // ↑ on the first section does nothing.
  await handle(page, 'RSS Beslemeleri').focus();
  await page.keyboard.press('ArrowUp');
  await expect.poll(() => state.sidebarOrderRequests.length).toBe(2);
});

test('the order goes back when saving it fails', async ({ page }) => {
  await loginAs(page);
  await mockApi(page, { articles: [makeArticle()] });
  await page.route('**/api/auth/me/sidebar-order', (route) =>
    route.request().method() === 'PUT' ? route.fulfill({ status: 500, body: '{}' }) : route.fallback());
  await openNews(page);

  const failed = page.waitForResponse((r) => r.request().method() === 'PUT' && r.url().includes('/auth/me/sidebar-order'));
  await handle(page, 'Kaynak Türü').focus();
  await page.keyboard.press('ArrowDown');
  expect((await failed).status()).toBe(500); // the move was tried…

  await expect.poll(() => sectionOrder(page)).toEqual(DEFAULT_LABELS); // …and undone
});

test('clicking a section header still opens and closes it', async ({ page }) => {
  await loginAs(page);
  await mockApi(page, { articles: [makeArticle()] });
  await openNews(page);

  await expect(page.getByLabel('Manuel eklenen')).toBeVisible();
  await page.getByRole('button', { name: 'Kaynak Türü', exact: true }).click();
  await expect(page.getByLabel('Manuel eklenen')).toHaveCount(0);
});
