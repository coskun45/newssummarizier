import { test, expect } from '@playwright/test';
import { ADMIN_USER, loginAs } from './helpers/auth';
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

test('error articles are kept out of the unread list and its counts', async ({ page }) => {
  await loginAs(page);
  await mockApi(page, {
    articles: [
      errorArticle('Kein Label'),
      makeArticle({ title: 'Hoch', importance: 'important', priority: 'high' }),
    ],
  });
  await openNews(page);

  const unreadTab = page.getByRole('button', { name: 'Okunmamışlar' });
  // Only the labelled article counts as unread
  await expect(unreadTab).toContainText('1');
  await expect(page.locator('.article-list').getByText('Hoch')).toBeVisible();
  await expect(page.getByText('Kein Label')).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Error' })).toContainText('1');
});

test('the unread list asks the API to exclude error articles', async ({ page }) => {
  await loginAs(page);
  await mockApi(page, { articles: [errorArticle('Kein Label')] });
  const req = page.waitForRequest((r) => {
    const q = new URL(r.url()).searchParams;
    return r.url().includes('/articles/?') && q.get('is_read') === 'false' && q.get('is_error') === 'false';
  });
  await openNews(page);
  await req;
});

test('an unread-tab "archive all" leaves error articles alone', async ({ page }) => {
  await loginAs(page);
  await mockApi(page, {
    articles: [
      errorArticle('Kein Label'),
      makeArticle({ title: 'Hoch', importance: 'important', priority: 'high' }),
    ],
  });
  await openNews(page);

  const req = page.waitForRequest((r) => r.url().endsWith('/articles/mark-read-bulk')
    && r.postDataJSON()?.mark_all === true && r.postDataJSON()?.is_error === false);
  page.once('dialog', (dialog) => void dialog.accept()); // "archive all" asks for confirmation
  await page.getByRole('button', { name: 'Tümünü Arşive Gönder', exact: true }).first().click();
  await req;

  await page.getByRole('button', { name: 'Error' }).click();
  await expect(page.getByText('Kein Label')).toBeVisible();
});

test('a read error article shows the Hata badge in the archive', async ({ page }) => {
  await loginAs(page);
  await mockApi(page, {
    articles: [
      makeArticle({ title: 'Kein Label', importance: null, priority: null, is_read: true }),
      makeArticle({ title: 'Hoch', importance: 'important', priority: 'high', is_read: true }),
    ],
  });
  await openNews(page);
  await page.getByRole('button', { name: 'Arşiv', exact: true }).click();

  await expect(page.locator('.article-card', { hasText: 'Kein Label' }).getByText('Hata')).toBeVisible();
  await expect(page.locator('.article-card', { hasText: 'Hoch' }).getByText('Hata')).toHaveCount(0);
});

test('a successfully re-processed error article moves to the unread list and counts update', async ({ page }) => {
  await loginAs(page, ADMIN_USER);
  await mockApi(page, {
    articles: [
      makeArticle({ title: 'Retry Me', importance: null, priority: null, is_read: true }),
    ],
  });
  await openNews(page);
  await expect(page.getByRole('button', { name: 'Okunmamışlar' })).not.toContainText('1');

  await page.getByRole('button', { name: 'Error' }).click();
  await page.locator('.article-card', { hasText: 'Retry Me' }).getByRole('button', { name: 'Tekrar dene' }).click();
  await expect(page.getByText('Hatalı haber yok')).toBeVisible();

  await expect(page.getByRole('button', { name: 'Okunmamışlar' })).toContainText('1');
  await page.getByRole('button', { name: 'Okunmamışlar' }).click();
  await expect(page.locator('.article-list').getByText('Retry Me')).toBeVisible();
});

test('single "Tekrar dene" re-runs just that article and it leaves the Error tab', async ({ page }) => {
  await loginAs(page, ADMIN_USER);
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
  await loginAs(page, ADMIN_USER);
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
  await loginAs(page, ADMIN_USER);
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

test('a labelled article whose processing failed (no summary) is an error and can be retried', async ({ page }) => {
  await loginAs(page, ADMIN_USER);
  const failed = makeArticle({ title: 'High No Summary', importance: 'important', priority: 'high', status: 'failed' });
  await mockApi(page, {
    articles: [failed, makeArticle({ title: 'Fine', importance: 'important', priority: 'high' })],
  });
  await openNews(page);

  // kept out of the unread list, listed in the Error tab
  await expect(page.locator('.article-list').getByText('High No Summary')).toHaveCount(0);
  await page.getByRole('button', { name: 'Error' }).click();
  const card = page.locator('.article-card', { hasText: 'High No Summary' });
  await expect(card.getByText('Hata')).toBeVisible();

  const req = page.waitForRequest((r) => r.url().endsWith('/articles/reprocess')
    && JSON.stringify(r.postDataJSON()) === JSON.stringify({ article_ids: [failed.id] }));
  await card.getByRole('button', { name: 'Tekrar dene' }).click();
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
  await loginAs(page, ADMIN_USER);
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
