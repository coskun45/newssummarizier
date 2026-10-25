import { test, expect, type Page } from '@playwright/test';
import { loginAs } from './helpers/auth';
import { mockApi, makeArticle } from './helpers/mockApi';

async function openNews(page: Page) {
  await page.goto('/');
  await page.getByRole('button', { name: 'Haberler', exact: true }).click();
}

function articleCard(page: Page, title: string) {
  return page.locator('.article-card').filter({ hasText: title });
}

function confirmDialog(page: Page) {
  return page.getByRole('dialog', { name: 'Arşive gönder' });
}

/** `count` articles titled "Haber 01".."Haber NN", newest first (the list order). */
function orderedArticles(count: number, overrides: Parameters<typeof makeArticle>[0] = {}) {
  const base = Date.parse('2026-10-20T12:00:00Z');
  return Array.from({ length: count }, (_, i) =>
    makeArticle({
      title: `Haber ${String(i + 1).padStart(2, '0')}`,
      published_at: new Date(base - i * 60_000).toISOString(),
      ...overrides,
    })
  );
}

test('"Bu ve üstündekileri" archives the article and everything above it within the filter', async ({ page }) => {
  await loginAs(page);
  const meds = orderedArticles(5, { priority: 'med' });
  const high = makeArticle({ title: 'Yüksek Haber', priority: 'high', published_at: '2026-10-21T12:00:00Z' });
  await mockApi(page, { articles: [...meds, high] });
  await openNews(page);

  const filtered = page.waitForRequest((r) => new URL(r.url()).searchParams.get('priority') === 'med');
  await page.getByLabel('Orta').click();
  await filtered;
  await expect(articleCard(page, 'Yüksek Haber')).toHaveCount(0);

  await articleCard(page, 'Haber 03').getByRole('button', { name: 'Diğer işlemler' }).click();
  await expect(page.getByRole('menuitem', { name: 'Bu ve üstündekileri arşive gönder (3)' })).toBeVisible();
  await expect(page.getByRole('menuitem', { name: 'Bu ve altındakileri arşive gönder (3)' })).toBeVisible();

  let bulkCalled = false;
  page.on('request', (r) => {
    if (r.url().includes('/api/articles/mark-read-bulk')) bulkCalled = true;
  });
  await page.getByRole('menuitem', { name: /Bu ve üstündekileri/ }).click();

  // An in-app popup asks first — nothing is sent until it is confirmed
  const dialog = confirmDialog(page);
  await expect(dialog).toBeVisible();
  await expect(dialog).toContainText('Bu haber dahil üstteki 3 haber arşive gönderilecek.');
  expect(bulkCalled).toBe(false);

  const req = page.waitForRequest((r) => r.url().includes('/api/articles/mark-read-bulk'));
  await dialog.getByRole('button', { name: 'Arşive gönder' }).click();
  const body = (await req).postDataJSON();

  await expect(dialog).toHaveCount(0);
  expect(body).toMatchObject({ mark_all: true, priority: 'med', is_read: false, anchor_id: meds[2].id, direction: 'above' });
  expect(body.article_ids).toBeUndefined();
  await expect(page.getByText('3 haber arşive gönderildi.')).toBeVisible();

  for (const title of ['Haber 01', 'Haber 02', 'Haber 03']) {
    await expect(articleCard(page, title)).toHaveCount(0);
  }
  await expect(articleCard(page, 'Haber 04')).toBeVisible();
  await expect(articleCard(page, 'Haber 05')).toBeVisible();

  // The high-priority article outside the filter stays unread
  await page.getByLabel('Orta').click();
  await expect(articleCard(page, 'Yüksek Haber')).toBeVisible();
});

test('counts include earlier pages and "Bu ve altındakileri" archives to the end of the list', async ({ page }) => {
  await loginAs(page);
  await mockApi(page, { articles: orderedArticles(25) });
  await openNews(page);

  await page.getByRole('button', { name: 'Sonraki sayfa' }).click();
  await articleCard(page, 'Haber 21').getByRole('button', { name: 'Diğer işlemler' }).click();
  await expect(page.getByRole('menuitem', { name: 'Bu ve üstündekileri arşive gönder (21)' })).toBeVisible();
  await expect(page.getByRole('menuitem', { name: 'Bu ve altındakileri arşive gönder (5)' })).toBeVisible();

  await page.getByRole('menuitem', { name: /Bu ve altındakileri/ }).click();
  await expect(confirmDialog(page)).toContainText('Bu haber dahil alttaki 5 haber arşive gönderilecek.');
  await confirmDialog(page).getByRole('button', { name: 'Arşive gönder' }).click();

  await expect(page.getByText('5 haber arşive gönderildi.')).toBeVisible();
  await expect(page.getByRole('button', { name: 'Okunmamışlar' })).toHaveText(/20/);
  await expect(articleCard(page, 'Haber 01')).toBeVisible();
  await expect(articleCard(page, 'Haber 21')).toHaveCount(0);
});

test('İptal, Escape and the close button dismiss the popup without archiving; Escape closes the menu', async ({ page }) => {
  await loginAs(page);
  await mockApi(page, { articles: orderedArticles(3) });
  await openNews(page);

  let bulkCalled = false;
  page.on('request', (r) => {
    if (r.url().includes('/api/articles/mark-read-bulk')) bulkCalled = true;
  });

  const menuButton = articleCard(page, 'Haber 02').getByRole('button', { name: 'Diğer işlemler' });
  await menuButton.click();
  await expect(page.getByRole('menu')).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(page.getByRole('menu')).toHaveCount(0);

  const dismissals = [
    () => confirmDialog(page).getByRole('button', { name: 'İptal' }).click(),
    () => page.keyboard.press('Escape'),
    () => confirmDialog(page).getByRole('button', { name: 'Kapat' }).click(),
  ];
  for (const dismiss of dismissals) {
    await menuButton.click();
    await page.getByRole('menuitem', { name: /Bu ve üstündekileri/ }).click();
    await expect(confirmDialog(page)).toBeVisible();
    await dismiss();
    await expect(confirmDialog(page)).toHaveCount(0);
  }

  await expect(articleCard(page, 'Haber 01')).toBeVisible();
  await expect(articleCard(page, 'Haber 02')).toBeVisible();
  expect(bulkCalled).toBe(false);
});

test('the archive view has no ⋯ range menu', async ({ page }) => {
  await loginAs(page);
  await mockApi(page, { articles: [makeArticle({ title: 'Zaten Okundu', is_read: true })] });
  await openNews(page);

  await page.getByRole('button', { name: 'Arşiv', exact: true }).click();
  await expect(articleCard(page, 'Zaten Okundu')).toBeVisible();
  await expect(page.getByRole('button', { name: 'Diğer işlemler' })).toHaveCount(0);
});
