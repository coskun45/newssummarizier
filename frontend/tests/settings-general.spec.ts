import { test, expect } from '@playwright/test';
import { loginAs } from './helpers/auth';
import { mockApi } from './helpers/mockApi';

async function openSettings(page: import('@playwright/test').Page) {
  await page.getByTitle('Ayarlar').click();
  return page.locator('.settings-modal');
}

// "Özet Türleri" is collapsed by default — expand it before touching its checkboxes.
async function openSummaryTypesSection(page: import('@playwright/test').Page) {
  const modal = await openSettings(page);
  await modal.getByText('Özet Türleri').click();
  return modal;
}

test('opens settings and shows current values', async ({ page }) => {
  await loginAs(page);
  await mockApi(page, {
    articles: [],
    settings: { enabled_summary_types: 'brief,standard' },
  });
  await page.goto('/');

  const modal = await openSummaryTypesSection(page);

  await expect(modal.getByRole('heading', { name: 'Ayarlar' })).toBeVisible();
  await expect(modal.getByRole('checkbox', { name: /Kısa/ })).toBeChecked();
  await expect(modal.getByRole('checkbox', { name: /Detaylı/ })).not.toBeChecked();
});

test('cancel closes without saving', async ({ page }) => {
  await loginAs(page);
  await mockApi(page, { articles: [] });
  let putCalled = false;
  await page.route(
    (url) => url.pathname === '/api/settings/',
    (route) => {
      if (route.request().method() === 'PUT') putCalled = true;
      route.fallback();
    }
  );
  await page.goto('/');

  const modal = await openSettings(page);
  await modal.getByRole('button', { name: 'İptal' }).click();

  await expect(page.locator('.settings-modal')).not.toBeVisible();
  expect(putCalled).toBe(false);
});

test('saving toggled summary types sends PUT and closes the modal', async ({ page }) => {
  await loginAs(page);
  await mockApi(page, {
    articles: [],
    settings: { enabled_summary_types: 'brief,standard,detailed' },
  });
  await page.goto('/');

  const modal = await openSummaryTypesSection(page);
  await modal.getByRole('checkbox', { name: /Detaylı/ }).uncheck();

  const req = page.waitForRequest(
    (r) => r.url().endsWith('/api/settings/') && r.method() === 'PUT' && !r.postDataJSON().enabled_summary_types.includes('detailed')
  );
  await modal.getByRole('button', { name: 'Ayarları kaydet' }).click();
  await req;

  await expect(page.locator('.settings-modal')).not.toBeVisible();
});

test('save button disabled when all summary types are unchecked', async ({ page }) => {
  await loginAs(page);
  await mockApi(page, { articles: [] });
  await page.goto('/');

  const modal = await openSummaryTypesSection(page);
  await modal.getByRole('checkbox', { name: /Kısa/ }).uncheck();
  await modal.getByRole('checkbox', { name: /Standart/ }).uncheck();
  await modal.getByRole('checkbox', { name: /Detaylı/ }).uncheck();

  await expect(modal.getByRole('button', { name: 'Ayarları kaydet' })).toBeDisabled();
});

test('closing via backdrop click', async ({ page }) => {
  await loginAs(page);
  await mockApi(page, { articles: [] });
  await page.goto('/');

  await openSettings(page);
  await page.locator('.settings-overlay').click({ position: { x: 5, y: 5 } });

  await expect(page.locator('.settings-modal')).not.toBeVisible();
});
