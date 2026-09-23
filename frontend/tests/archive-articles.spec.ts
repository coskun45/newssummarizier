import { test, expect } from '@playwright/test';
import { loginAs } from './helpers/auth';
import { mockApi, makeArticle } from './helpers/mockApi';

async function openNews(page: import('@playwright/test').Page) {
  await page.goto('/');
  await page.getByRole('button', { name: 'Haberler', exact: true }).click();
}

function articleCard(page: import('@playwright/test').Page, title: string) {
  return page.locator('.article-card').filter({ hasText: title });
}

test('selected articles are archived via mark-read-bulk and move to Arşiv', async ({ page }) => {
  await loginAs(page);
  const first = makeArticle({ title: 'Archive Me One', is_read: false });
  const second = makeArticle({ title: 'Archive Me Two', is_read: false });
  const kept = makeArticle({ title: 'Keep Me Unread', is_read: false });
  await mockApi(page, { articles: [first, second, kept] });
  await openNews(page);

  // The selection button only appears once something is selected
  await expect(page.getByRole('button', { name: /Seçilenleri Arşive Gönder/ })).toHaveCount(0);
  await articleCard(page, 'Archive Me One').getByRole('checkbox', { name: 'Seç' }).check();
  await articleCard(page, 'Archive Me Two').getByRole('checkbox', { name: 'Seç' }).check();

  const req = page.waitForRequest((r) => r.url().includes('/api/articles/mark-read-bulk') && r.method() === 'POST');
  await page.getByRole('button', { name: 'Seçilenleri Arşive Gönder (2)' }).click();
  const body = (await req).postDataJSON();
  expect(body).toEqual({ article_ids: expect.arrayContaining([first.id, second.id]) });
  expect(body.article_ids).toHaveLength(2);

  await expect(page.getByText('Archive Me One')).not.toBeVisible();
  await expect(page.getByText('Archive Me Two')).not.toBeVisible();
  await expect(page.getByText('Keep Me Unread')).toBeVisible();
  // Selection is cleared after a successful archive
  await expect(page.getByRole('button', { name: /Seçilenleri Arşive Gönder/ })).toHaveCount(0);

  await page.getByRole('button', { name: 'Arşiv', exact: true }).click();
  await expect(page.getByText('Archive Me One')).toBeVisible();
  await expect(page.getByText('Archive Me Two')).toBeVisible();
  await expect(page.getByText('Keep Me Unread')).not.toBeVisible();
});

test('Tümünü Arşive Gönder sends mark_all with the active filters', async ({ page }) => {
  await loginAs(page);
  await mockApi(page, {
    articles: [
      makeArticle({ title: 'High One', priority: 'high', is_read: false }),
      makeArticle({ title: 'Medium One', priority: 'med', is_read: false }),
    ],
  });
  await openNews(page);

  // Narrow to Yüksek, then archive "all" — only the filtered set may be archived
  const filtered = page.waitForRequest((r) => new URL(r.url()).searchParams.get('priority') === 'high');
  await page.getByLabel('Yüksek').click();
  await filtered;
  await expect(page.locator('.article-list').getByText('Medium One')).not.toBeVisible();

  let message = '';
  page.once('dialog', (dialog) => {
    message = dialog.message();
    void dialog.accept();
  });
  const req = page.waitForRequest((r) => r.url().includes('/api/articles/mark-read-bulk'));
  await page.locator('.bulk-action-bar').getByRole('button', { name: 'Tümünü Arşive Gönder' }).click();
  const body = (await req).postDataJSON();
  expect(message).toBe('Listelenen 1 haberin tümü arşive gönderilecek. Devam edilsin mi?');
  expect(body).toMatchObject({ mark_all: true, priority: 'high', is_read: false });
  expect(body.article_ids).toBeUndefined();

  // Clear the priority filter: the medium article is still unread
  await page.getByLabel('Yüksek').click();
  await expect(page.locator('.article-list').getByText('Medium One')).toBeVisible();
  await expect(page.locator('.article-list').getByText('High One')).not.toBeVisible();
});

test('Tümünü Arşive Gönder asks for confirmation; dismissing archives nothing', async ({ page }) => {
  await loginAs(page);
  await mockApi(page, {
    articles: [makeArticle({ title: 'Stay One', is_read: false }), makeArticle({ title: 'Stay Two', is_read: false })],
  });
  await openNews(page);

  let bulkCalled = false;
  page.on('request', (r) => {
    if (r.url().includes('/api/articles/mark-read-bulk')) bulkCalled = true;
  });
  let message = '';
  page.once('dialog', (dialog) => {
    message = dialog.message();
    void dialog.dismiss();
  });
  await page.locator('.bulk-action-bar').getByRole('button', { name: 'Tümünü Arşive Gönder' }).click();

  expect(message).toBe('Listelenen 2 haberin tümü arşive gönderilecek. Devam edilsin mi?');
  await expect(page.getByText('Stay One')).toBeVisible();
  await expect(page.getByText('Stay Two')).toBeVisible();
  expect(bulkCalled).toBe(false);
});

test('a single article can be archived from its card', async ({ page }) => {
  await loginAs(page);
  const target = makeArticle({ title: 'Read This One', is_read: false });
  await mockApi(page, { articles: [target, makeArticle({ title: 'Other Unread', is_read: false })] });
  await openNews(page);
  await expect(page.getByRole('button', { name: 'Okunmamışlar' })).toHaveText(/2/);

  const req = page.waitForRequest((r) => r.url().endsWith(`/api/articles/${target.id}/read`) && r.method() === 'PATCH');
  await articleCard(page, 'Read This One').getByRole('button', { name: 'Arşive gönder' }).click();
  await req;

  await expect(page.getByText('Read This One')).not.toBeVisible();
  await expect(page.getByText('Other Unread')).toBeVisible();
  await expect(page.getByRole('button', { name: 'Okunmamışlar' })).toHaveText(/1/);

  // In the archive the article is listed without the button (it is already read)
  await page.getByRole('button', { name: 'Arşiv', exact: true }).click();
  await expect(articleCard(page, 'Read This One')).toBeVisible();
  await expect(articleCard(page, 'Read This One').getByRole('button', { name: 'Arşive gönder' })).toHaveCount(0);
});

test('archive view has no selection checkboxes or archive buttons', async ({ page }) => {
  await loginAs(page);
  await mockApi(page, { articles: [makeArticle({ title: 'Already Read', is_read: true })] });
  await openNews(page);

  await page.getByRole('button', { name: 'Arşiv', exact: true }).click();
  await expect(page.getByText('Already Read')).toBeVisible();
  await expect(page.getByRole('checkbox', { name: 'Seç' })).toHaveCount(0);
  await expect(page.getByRole('button', { name: /Arşive Gönder/i })).toHaveCount(0);
});
