import { test, expect } from '@playwright/test';
import { loginAs } from './helpers/auth';
import { mockApi } from './helpers/mockApi';

async function openSummaryTypesCategory(page: import('@playwright/test').Page) {
  await page.getByRole('button', { name: 'Ayarlar' }).click();
  await page.getByRole('button', { name: 'Özet Türleri' }).click();
  return page.locator('.settings-category');
}

test('opens settings and shows current values', async ({ page }) => {
  await loginAs(page);
  await mockApi(page, {
    articles: [],
    settings: { enabled_summary_types: 'brief,standard' },
  });
  await page.goto('/');

  const content = await openSummaryTypesCategory(page);

  await expect(content.getByRole('heading', { name: 'Özet Türleri' })).toBeVisible();
  await expect(content.getByRole('checkbox', { name: /Kısa/ })).toBeChecked();
  await expect(content.getByRole('checkbox', { name: /Detaylı/ })).not.toBeChecked();
});

test('navigating away without saving does not send a PUT', async ({ page }) => {
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

  await openSummaryTypesCategory(page);
  await page.getByRole('button', { name: 'Haberler' }).click();

  await expect(page.locator('.settings-category')).not.toBeVisible();
  expect(putCalled).toBe(false);
});

test('saving toggled summary types sends PUT', async ({ page }) => {
  await loginAs(page);
  await mockApi(page, {
    articles: [],
    settings: { enabled_summary_types: 'brief,standard,detailed' },
  });
  await page.goto('/');

  const content = await openSummaryTypesCategory(page);
  await content.getByRole('checkbox', { name: /Detaylı/ }).uncheck();

  const req = page.waitForRequest(
    (r) => r.url().endsWith('/api/settings/') && r.method() === 'PUT' && !r.postDataJSON().enabled_summary_types.includes('detailed')
  );
  await content.getByRole('button', { name: 'Ayarları kaydet' }).click();
  await req;
});

test('save button disabled when all summary types are unchecked', async ({ page }) => {
  await loginAs(page);
  await mockApi(page, { articles: [] });
  await page.goto('/');

  const content = await openSummaryTypesCategory(page);
  await content.getByRole('checkbox', { name: /Kısa/ }).uncheck();
  await content.getByRole('checkbox', { name: /Standart/ }).uncheck();
  await content.getByRole('checkbox', { name: /Detaylı/ }).uncheck();

  await expect(content.getByRole('button', { name: 'Ayarları kaydet' })).toBeDisabled();
});
