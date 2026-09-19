import { test, expect } from '@playwright/test';
import { loginAs } from './helpers/auth';
import { mockApi, makeArticle } from './helpers/mockApi';

// "Error" = an article that never received a severity label (Yüksek/Orta/Düşük/Önemsiz).
const errorArticle = (title: string) => makeArticle({ title, importance: null, priority: null });

async function openNews(page: import('@playwright/test').Page) {
  await page.goto('/');
  await page.getByRole('button', { name: 'Haberler', exact: true }).click();
}

test('Error tab sits next to Favori and only lists unlabelled articles', async ({ page }) => {
  await loginAs(page);
  await mockApi(page, {
    articles: [
      errorArticle('Kein Label'),
      makeArticle({ title: 'Hoch', importance: 'important', priority: 'high' }),
      makeArticle({ title: 'Egal', importance: 'unimportant', priority: null, status: 'filtered' }),
      makeArticle({ title: 'Wird gerade verarbeitet', status: 'pending' }),
    ],
  });
  await openNews(page);

  const tabs = page.locator('.section-tabs').getByRole('button');
  await expect(tabs.nth(2)).toHaveAccessibleName('Favori');
  await expect(tabs.nth(3)).toHaveAccessibleName('Error');
  // Badge counts only the unlabelled, non-pending article
  await expect(tabs.nth(3)).toContainText('1');

  await tabs.nth(3).click();
  await expect(page.getByText('Kein Label')).toBeVisible();
  await expect(page.getByText('Hoch')).toHaveCount(0);
  await expect(page.getByText('Egal')).toHaveCount(0);
  await expect(page.getByText('Wird gerade verarbeitet')).toHaveCount(0);
});

test('unlabelled article carries a Hata badge in the normal tabs too', async ({ page }) => {
  await loginAs(page);
  await mockApi(page, {
    articles: [
      errorArticle('Kein Label'),
      makeArticle({ title: 'Hoch', importance: 'important', priority: 'high' }),
    ],
  });
  await openNews(page);

  const errCard = page.locator('.article-card', { hasText: 'Kein Label' });
  const okCard = page.locator('.article-card', { hasText: 'Hoch' });
  await expect(errCard.getByText('Hata')).toBeVisible();
  await expect(okCard.getByText('Hata')).toHaveCount(0);
});

test('single "Tekrar dene" re-runs just that article and it leaves the Error tab', async ({ page }) => {
  await loginAs(page);
  const target = errorArticle('Retry Me');
  await mockApi(page, { articles: [target, errorArticle('Stay Broken')] });
  await openNews(page);
  await page.getByRole('button', { name: 'Error' }).click();

  const req = page.waitForRequest(
    (r) => r.url().endsWith('/articles/reprocess') && r.method() === 'POST'
      && JSON.stringify(r.postDataJSON()) === JSON.stringify({ article_ids: [target.id] })
  );
  await page.locator('.article-card', { hasText: 'Retry Me' }).getByRole('button', { name: 'Tekrar dene' }).click();
  await req;

  await expect(page.getByText('Retry Me')).toHaveCount(0);
  await expect(page.getByText('Stay Broken')).toBeVisible();
});

test('bulk: selected articles are re-run together', async ({ page }) => {
  await loginAs(page);
  const a = errorArticle('Bulk A');
  const b = errorArticle('Bulk B');
  const c = errorArticle('Bulk C');
  await mockApi(page, { articles: [a, b, c] });
  await openNews(page);
  await page.getByRole('button', { name: 'Error' }).click();

  await page.locator('.article-card', { hasText: 'Bulk A' }).getByRole('checkbox').check();
  await page.locator('.article-card', { hasText: 'Bulk B' }).getByRole('checkbox').check();

  const req = page.waitForRequest((r) => {
    if (!r.url().endsWith('/articles/reprocess') || r.method() !== 'POST') return false;
    const ids = (r.postDataJSON()?.article_ids ?? []) as number[];
    return ids.length === 2 && ids.includes(a.id) && ids.includes(b.id);
  });
  await page.getByRole('button', { name: /Seçilenleri Tekrar Dene \(2\)/ }).click();
  await req;

  await expect(page.getByText('Bulk C')).toBeVisible();
  await expect(page.getByText('Bulk A')).toHaveCount(0);
});

test('bulk: "Tümünü Tekrar Dene" asks for confirmation then re-runs every error', async ({ page }) => {
  await loginAs(page);
  await mockApi(page, { articles: [errorArticle('All A'), errorArticle('All B')] });
  await openNews(page);
  await page.getByRole('button', { name: 'Error' }).click();

  page.once('dialog', (d) => d.accept());
  const req = page.waitForRequest(
    (r) => r.url().endsWith('/articles/reprocess') && r.method() === 'POST' && r.postDataJSON()?.all_errors === true
  );
  await page.getByRole('button', { name: 'Tümünü Tekrar Dene' }).click();
  await req;

  await expect(page.getByText('Hatalı haber yok')).toBeVisible();
});

test('empty Error tab says there are no errors instead of "not found / loading"', async ({ page }) => {
  await loginAs(page);
  await mockApi(page, {
    articles: [makeArticle({ title: 'Hoch', importance: 'important', priority: 'high' })],
  });
  await openNews(page);
  await page.getByRole('button', { name: 'Error' }).click();

  await expect(page.getByText('Hatalı haber yok')).toBeVisible();
  await expect(page.getByText('Tüm haberler bir önem etiketi almış.')).toBeVisible();
  await expect(page.getByText('Makale bulunamadı')).toHaveCount(0);
  await expect(page.getByText('Makaleler yükleniyor...')).toHaveCount(0);
});

test('"Tümünü Tekrar Dene" does nothing when the confirmation is dismissed', async ({ page }) => {
  await loginAs(page);
  await mockApi(page, { articles: [errorArticle('Keep Me')] });
  await openNews(page);
  await page.getByRole('button', { name: 'Error' }).click();

  let called = false;
  page.on('request', (r) => { if (r.url().endsWith('/articles/reprocess')) called = true; });
  page.once('dialog', (d) => d.dismiss());
  await page.getByRole('button', { name: 'Tümünü Tekrar Dene' }).click();

  await expect(page.getByText('Keep Me')).toBeVisible();
  expect(called).toBe(false);
});

test('sidebar priority filter does not empty the Error tab', async ({ page }) => {
  await loginAs(page);
  await mockApi(page, {
    articles: [
      errorArticle('Unlabelled'),
      makeArticle({ title: 'High Prio', importance: 'important', priority: 'high' }),
    ],
  });
  await openNews(page);

  // A priority filter is active (needs a label) ...
  await page.getByLabel('Yüksek').click();
  // ... but the Error tab is by definition about articles without one.
  const req = page.waitForRequest((r) => {
    const q = new URL(r.url()).searchParams;
    return q.get('is_error') === 'true' && q.get('priority') === null && q.get('status') === null;
  });
  await page.getByRole('button', { name: 'Error' }).click();
  await req;

  await expect(page.locator('.article-list').getByText('Unlabelled')).toBeVisible();
});
