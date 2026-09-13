import { test, expect } from '@playwright/test';
import { loginAs } from './helpers/auth';
import { mockApi, makeFeed } from './helpers/mockApi';

const FEED = makeFeed({ id: 301, title: 'Existing Feed', url: 'https://example.com/existing.xml' });

async function openFeedsSection(page: import('@playwright/test').Page) {
  await page.getByTitle('Ayarlar').click();
  const modal = page.locator('.settings-modal');
  await modal.getByText('RSS Beslemeleri').click();
  return modal;
}

test('adding a feed sends POST and clears the form', async ({ page }) => {
  await loginAs(page);
  await mockApi(page, { feeds: [FEED], articles: [] });
  await page.goto('/');

  const modal = await openFeedsSection(page);
  await modal.getByRole('button', { name: 'Yeni besleme ekle' }).click();
  const form = modal.locator('.add-topic-form');
  await form.getByPlaceholder(/RSS URL/).fill('https://example.com/new.xml');

  const req = page.waitForRequest((r) => r.url().endsWith('/api/feeds/') && r.method() === 'POST');
  await form.getByRole('button', { name: 'Ekle' }).click();
  await req;

  await expect(modal.getByRole('button', { name: 'Yeni besleme ekle' })).toBeVisible();
});

test('add button disabled until a URL is entered', async ({ page }) => {
  await loginAs(page);
  await mockApi(page, { feeds: [FEED], articles: [] });
  await page.goto('/');

  const modal = await openFeedsSection(page);
  await modal.getByRole('button', { name: 'Yeni besleme ekle' }).click();
  const form = modal.locator('.add-topic-form');

  await expect(form.getByRole('button', { name: 'Ekle' })).toBeDisabled();
  await form.getByPlaceholder(/RSS URL/).fill('https://example.com/new.xml');
  await expect(form.getByRole('button', { name: 'Ekle' })).toBeEnabled();
});

test("editing a feed's title sends PUT", async ({ page }) => {
  await loginAs(page);
  await mockApi(page, { feeds: [FEED], articles: [] });
  await page.goto('/');

  const modal = await openFeedsSection(page);
  await modal.getByTitle('Beslemeyi düzenle').click();
  const form = modal.locator('.add-topic-form');
  await form.getByPlaceholder('Ad (isteğe bağlı)').fill('Renamed Feed');

  const req = page.waitForRequest(
    (r) => /\/api\/feeds\/\d+$/.test(new URL(r.url()).pathname) && r.method() === 'PUT'
  );
  await form.getByRole('button', { name: 'Kaydet' }).click();
  await req;

  await expect(modal.getByText('Renamed Feed')).toBeVisible();
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
