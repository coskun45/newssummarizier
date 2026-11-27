import { test, expect } from '@playwright/test';
import { loginAs } from './helpers/auth';
import { mockApi, makeArticle } from './helpers/mockApi';

// Sidebar "Kaynak Türü": "Ücretsiz kaynaktan" (a free source has the story of a blocked /
// paywalled article) and "Manuel eklenen" (added by an admin). A filter, not a separate tab: the
// articles stay in the normal lists too.
const labelled = { importance: 'important' as const, priority: 'high' as const, status: 'summarized' as const };

function articles() {
  return [
    makeArticle({ ...labelled, title: 'Gewöhnliche Meldung' }),
    makeArticle({
      ...labelled,
      title: 'Bezahlschranke Bericht',
      content_access: 'free_match',
      free_match: { id: 999, title: 'Freie Quelle', url: 'https://free.example.com/a', source: 'DW' },
    }),
    // Its match was deleted: the API reports it as "unavailable", so it is no free match.
    makeArticle({ ...labelled, title: 'Verlorene Quelle', content_access: 'free_match', free_match: null }),
    makeArticle({ ...labelled, title: 'Von Hand ergänzt', source_type: 'manual' }),
    makeArticle({ ...labelled, title: 'Nicht lesbar', content_access: 'unavailable' }),
  ];
}

async function openNews(page: import('@playwright/test').Page) {
  await page.goto('/');
  await page.getByRole('button', { name: 'Haberler', exact: true }).click();
}

const list = (page: import('@playwright/test').Page) => page.locator('.article-list');

test('the Kaynak Türü section shows both groups with their unread counts', async ({ page }) => {
  await loginAs(page);
  await mockApi(page, { articles: articles() });
  await openNews(page);

  await expect(page.getByRole('button', { name: 'Kaynak Türü', exact: true })).toBeVisible();
  // Exact counts: the article whose match was deleted must not make it 2.
  await expect(page.locator('label', { hasText: 'Ücretsiz kaynaktan' }).locator('.topic-count')).toHaveText('1');
  await expect(page.locator('label', { hasText: 'Manuel eklenen' }).locator('.topic-count')).toHaveText('1');
  // "İçerik alınamadı": the unavailable one plus the one whose match was deleted.
  await expect(page.locator('label', { hasText: 'İçerik alınamadı' }).locator('.topic-count')).toHaveText('2');
});

test('Kaynak Türü is the first section of the sidebar, above the feeds', async ({ page }) => {
  await loginAs(page);
  await mockApi(page, { articles: articles() });
  await openNews(page);

  const sidebar = page.locator('.dashboard-sidebar');
  const origin = await sidebar.getByRole('button', { name: 'Kaynak Türü', exact: true }).boundingBox();
  const feeds = await sidebar.getByText('RSS Beslemeleri').boundingBox();
  const priority = await sidebar.getByRole('button', { name: 'Önem Seviyesi', exact: true }).boundingBox();
  expect(origin!.y).toBeLessThan(feeds!.y);
  expect(origin!.y).toBeLessThan(priority!.y);
});

test('"İçerik alınamadı" lists articles without text and without a free source', async ({ page }) => {
  await loginAs(page);
  await mockApi(page, { articles: articles() });
  await openNews(page);

  const req = page.waitForRequest((r) =>
    r.url().includes('/articles/?') && new URL(r.url()).searchParams.get('origin') === 'unavailable');
  await page.getByLabel('İçerik alınamadı').check();
  await req;

  await expect(list(page).getByText('Nicht lesbar')).toBeVisible();
  await expect(list(page).getByText('Verlorene Quelle')).toBeVisible();
  await expect(list(page).getByText('Bezahlschranke Bericht')).toHaveCount(0);
  await expect(list(page).getByText('Gewöhnliche Meldung')).toHaveCount(0);
});

test('picking Önemsiz drops "İçerik alınamadı" (unimportant articles are never scraped)', async ({ page }) => {
  await loginAs(page);
  await mockApi(page, { articles: articles() });
  await openNews(page);

  const unavailable = page.getByLabel('İçerik alınamadı');
  await unavailable.check();
  await page.getByLabel('Önemsiz').check();

  await expect(unavailable).not.toBeChecked();
});

test('picking Önemsiz drops "Ücretsiz kaynaktan" (unimportant articles never get a free match)', async ({ page }) => {
  await loginAs(page);
  await mockApi(page, {
    articles: [...articles(), makeArticle({ title: 'Unwichtig', importance: 'unimportant', status: 'filtered' })],
  });
  await openNews(page);

  const freeMatch = page.getByLabel('Ücretsiz kaynaktan');
  await freeMatch.check();
  await page.getByLabel('Önemsiz').check();

  await expect(freeMatch).not.toBeChecked();
  await expect(list(page).getByText('Unwichtig')).toBeVisible();
});

test('picking Önemsiz keeps "Manuel eklenen" (manual articles can be unimportant)', async ({ page }) => {
  await loginAs(page);
  await mockApi(page, {
    articles: [makeArticle({ title: 'Manuell unwichtig', importance: 'unimportant', status: 'filtered', source_type: 'manual' })],
  });
  await openNews(page);

  await page.getByLabel('Manuel eklenen').check();
  await page.getByLabel('Önemsiz').check();

  await expect(page.getByLabel('Manuel eklenen')).toBeChecked();
  await expect(list(page).getByText('Manuell unwichtig')).toBeVisible();
});

test('the priority bulk actions are hidden while a Kaynak Türü filter is active', async ({ page }) => {
  // They act on every unread article of a priority, not on the filtered list — "Tümünü Arşive
  // Gönder" on a "Manuel eklenen" list must not archive every high-priority article.
  await loginAs(page);
  await mockApi(page, { articles: articles() });
  await openNews(page);

  const panel = page.getByText('Önem seviyesi bazlı toplu işlemler');
  await expect(panel).toBeVisible();

  await page.getByLabel('Manuel eklenen').check();
  await expect(panel).toHaveCount(0);

  await page.getByLabel('Manuel eklenen').uncheck();
  await expect(panel).toBeVisible();
});

test('"Ücretsiz kaynaktan" lists only articles with a free match', async ({ page }) => {
  await loginAs(page);
  await mockApi(page, { articles: articles() });
  await openNews(page);
  // Without the filter every article is in the unread list.
  await expect(list(page).getByText('Von Hand ergänzt')).toBeVisible();

  const req = page.waitForRequest((r) =>
    r.url().includes('/articles/?') && new URL(r.url()).searchParams.get('origin') === 'free_match');
  await page.getByLabel('Ücretsiz kaynaktan').check();
  await req;

  await expect(list(page).getByText('Bezahlschranke Bericht')).toBeVisible();
  await expect(list(page).getByText('Verlorene Quelle')).toHaveCount(0);
  await expect(list(page).getByText('Gewöhnliche Meldung')).toHaveCount(0);
  await expect(list(page).getByText('Von Hand ergänzt')).toHaveCount(0);
});

test('"Manuel eklenen" lists only manual articles and unchecking clears it', async ({ page }) => {
  await loginAs(page);
  await mockApi(page, { articles: articles() });
  await openNews(page);

  const manual = page.getByLabel('Manuel eklenen');
  await manual.check();
  await expect(list(page).getByText('Von Hand ergänzt')).toBeVisible();
  await expect(list(page).getByText('Gewöhnliche Meldung')).toHaveCount(0);

  // The two groups are exclusive, like the priorities: picking one unpicks the other.
  await page.getByLabel('Ücretsiz kaynaktan').check();
  await expect(manual).not.toBeChecked();

  await page.getByLabel('Ücretsiz kaynaktan').uncheck();
  await expect(list(page).getByText('Gewöhnliche Meldung')).toBeVisible();
  await expect(list(page).getByText('Von Hand ergänzt')).toBeVisible();
});
