import { test, expect } from '@playwright/test';
import { loginAs } from './helpers/auth';
import { mockApi, makeFeed } from './helpers/mockApi';

const FEED = makeFeed({ id: 301, title: 'Existing Feed', url: 'https://example.com/existing.xml' });

async function openFeedsSection(page: import('@playwright/test').Page) {
  await page.getByRole('button', { name: 'Ayarlar' }).click();
  await page.getByRole('button', { name: 'RSS Beslemeleri' }).click();
  return page.locator('.settings-category');
}

test('adding a feed tests the connection, then sends POST and clears the form', async ({ page }) => {
  await loginAs(page);
  await mockApi(page, { feeds: [FEED], articles: [] });
  await page.goto('/');

  const modal = await openFeedsSection(page);
  await modal.getByRole('button', { name: 'Yeni besleme ekle' }).click();
  const form = modal.locator('.add-topic-form');
  await form.getByPlaceholder(/RSS URL/).fill('https://example.com/new.xml');

  const testReq = page.waitForRequest((r) => r.url().endsWith('/api/feeds/test') && r.method() === 'POST');
  await form.getByRole('button', { name: 'Bağlantıyı Test Et' }).click();
  await testReq;
  await expect(form.getByText('Bağlantı başarılı')).toBeVisible();

  const req = page.waitForRequest((r) => r.url().endsWith('/api/feeds/') && r.method() === 'POST');
  await form.getByRole('button', { name: 'Ekle' }).click();
  await req;

  await expect(modal.getByRole('button', { name: 'Yeni besleme ekle' })).toBeVisible();
});

test('add button stays disabled until the URL is tested successfully', async ({ page }) => {
  await loginAs(page);
  await mockApi(page, { feeds: [FEED], articles: [] });
  await page.goto('/');

  const modal = await openFeedsSection(page);
  await modal.getByRole('button', { name: 'Yeni besleme ekle' }).click();
  const form = modal.locator('.add-topic-form');
  const testButton = form.getByRole('button', { name: 'Bağlantıyı Test Et' });
  const addButton = form.getByRole('button', { name: 'Ekle' });

  await expect(testButton).toBeDisabled();
  await expect(addButton).toBeDisabled();

  await form.getByPlaceholder(/RSS URL/).fill('https://example.com/new.xml');
  await expect(testButton).toBeEnabled();
  await expect(addButton).toBeDisabled();

  await testButton.click();
  await expect(form.getByText('Bağlantı başarılı')).toBeVisible();
  await expect(addButton).toBeEnabled();

  // Editing the URL again invalidates the previous test result.
  await form.getByPlaceholder(/RSS URL/).fill('https://example.com/new-2.xml');
  await expect(addButton).toBeDisabled();
});

test("editing only a feed's title (URL unchanged) sends PUT without requiring a connection test", async ({ page }) => {
  await loginAs(page);
  await mockApi(page, { feeds: [FEED], articles: [] });
  await page.goto('/');

  const modal = await openFeedsSection(page);
  await modal.getByTitle('Beslemeyi düzenle').click();
  const form = modal.locator('.add-topic-form');
  await form.getByPlaceholder('Ad (isteğe bağlı)').fill('Renamed Feed');

  await expect(form.getByRole('button', { name: 'Kaydet' })).toBeEnabled();

  const req = page.waitForRequest(
    (r) => /\/api\/feeds\/\d+$/.test(new URL(r.url()).pathname) && r.method() === 'PUT'
  );
  await form.getByRole('button', { name: 'Kaydet' }).click();
  await req;

  await expect(modal.getByText('Renamed Feed')).toBeVisible();
});

test('changing the URL while editing requires a successful connection test before saving', async ({ page }) => {
  await loginAs(page);
  await mockApi(page, { feeds: [FEED], articles: [] });
  await page.goto('/');

  const modal = await openFeedsSection(page);
  await modal.getByTitle('Beslemeyi düzenle').click();
  const form = modal.locator('.add-topic-form');
  const saveButton = form.getByRole('button', { name: 'Kaydet' });

  await form.getByPlaceholder('RSS URL').fill('https://example.com/changed.xml');
  await expect(saveButton).toBeDisabled();

  await form.getByRole('button', { name: 'Bağlantıyı Test Et' }).click();
  await expect(form.getByText('Bağlantı başarılı')).toBeVisible();
  await expect(saveButton).toBeEnabled();
});

test('deleting a feed shows a native confirm dialog; dismissing sends nothing', async ({ page }) => {
  await loginAs(page);
  await mockApi(page, { feeds: [FEED], articles: [] });
  let deleteCalled = false;
  await page.route(
    (url) => /\/api\/feeds\/\d+$/.test(url.pathname),
    (route) => {
      if (route.request().method() === 'DELETE') deleteCalled = true;
      route.fallback();
    }
  );
  await page.goto('/');

  const modal = await openFeedsSection(page);
  page.once('dialog', (dialog) => dialog.dismiss());
  await modal.getByTitle('Beslemeyi sil').click();

  await expect(modal.getByText('Existing Feed')).toBeVisible();
  expect(deleteCalled).toBe(false);
});

test('a failed connection test shows an error and keeps the add form open', async ({ page }) => {
  await loginAs(page);
  await mockApi(page, { feeds: [FEED], articles: [] });
  await page.route(
    (url) => url.pathname === '/api/feeds/test',
    (route) => route.fulfill({
      status: 400,
      contentType: 'application/json',
      body: JSON.stringify({ detail: 'Feed connection test failed: Failed to fetch RSS feed: timeout' }),
    })
  );
  await page.goto('/');

  const modal = await openFeedsSection(page);
  await modal.getByRole('button', { name: 'Yeni besleme ekle' }).click();
  const form = modal.locator('.add-topic-form');
  await form.getByPlaceholder(/RSS URL/).fill('https://example.com/unreachable.xml');
  await form.getByRole('button', { name: 'Bağlantıyı Test Et' }).click();

  await expect(form.getByText(/Feed connection test failed/)).toBeVisible();
  await expect(form.getByRole('button', { name: 'Ekle' })).toBeDisabled();
  await expect(form.getByPlaceholder(/RSS URL/)).toHaveValue('https://example.com/unreachable.xml');
});

test('a failed connection test on edit shows an error and keeps the row unchanged', async ({ page }) => {
  await loginAs(page);
  await mockApi(page, { feeds: [FEED], articles: [] });
  await page.route(
    (url) => url.pathname === '/api/feeds/test',
    (route) => route.fulfill({
      status: 400,
      contentType: 'application/json',
      body: JSON.stringify({ detail: 'Feed connection test failed: Failed to fetch RSS feed: timeout' }),
    })
  );
  await page.goto('/');

  const modal = await openFeedsSection(page);
  await modal.getByTitle('Beslemeyi düzenle').click();
  const form = modal.locator('.add-topic-form');
  await form.getByPlaceholder('RSS URL').fill('https://example.com/unreachable.xml');
  await form.getByRole('button', { name: 'Bağlantıyı Test Et' }).click();

  await expect(form.getByText(/Feed connection test failed/)).toBeVisible();
  await expect(form.getByRole('button', { name: 'Kaydet' })).toBeDisabled();

  await form.getByRole('button', { name: 'İptal' }).click();
  await expect(modal.getByText('Existing Feed')).toBeVisible();
});

test('confirming the delete dialog sends DELETE and removes it from the list', async ({ page }) => {
  await loginAs(page);
  await mockApi(page, { feeds: [FEED], articles: [] });
  await page.goto('/');

  const modal = await openFeedsSection(page);
  page.once('dialog', (dialog) => dialog.accept());
  const req = page.waitForRequest(
    (r) => /\/api\/feeds\/\d+$/.test(new URL(r.url()).pathname) && r.method() === 'DELETE'
  );
  await modal.getByTitle('Beslemeyi sil').click();
  await req;

  await expect(modal.getByText('Existing Feed')).not.toBeVisible();
});
