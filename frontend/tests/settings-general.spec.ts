import { test, expect } from '@playwright/test';
import { ADMIN_USER, loginAs } from './helpers/auth';
import { mockApi, makeTopic } from './helpers/mockApi';

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
  await page.getByRole('button', { name: 'Haberler', exact: true }).click();

  await expect(page.locator('.settings-category')).not.toBeVisible();
  expect(putCalled).toBe(false);
});

test('saving toggled summary types sends PUT', async ({ page }) => {
  await loginAs(page, ADMIN_USER);
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
  await loginAs(page, ADMIN_USER);
  await mockApi(page, { articles: [] });
  await page.goto('/');

  const content = await openSummaryTypesCategory(page);
  await content.getByRole('checkbox', { name: /Kısa/ }).uncheck();
  await content.getByRole('checkbox', { name: /Standart/ }).uncheck();
  await content.getByRole('checkbox', { name: /Detaylı/ }).uncheck();

  await expect(content.getByRole('button', { name: 'Ayarları kaydet' })).toBeDisabled();
});


test('the last checked category cannot be unchecked', async ({ page }) => {
  // #27: unchecking the last topic emptied the list, and empty means "all topics"
  await loginAs(page, ADMIN_USER);
  const topics = [makeTopic({ id: 1, name: 'NATO' }), makeTopic({ id: 2, name: 'Spor' })];
  await mockApi(page, { articles: [], topics, settings: { enabled_topics: '1' } });
  await page.goto('/');
  await page.getByRole('button', { name: 'Ayarlar' }).click();
  await page.getByRole('button', { name: 'Kategoriler' }).click();

  const content = page.locator('.settings-category');
  const nato = content.getByRole('checkbox', { name: /NATO/ });
  await expect(nato).toBeChecked();
  await expect(nato).toBeDisabled();
  await expect(content.getByRole('checkbox', { name: /Spor/ })).not.toBeChecked();

  await content.getByRole('checkbox', { name: /Spor/ }).check();
  await expect(nato).toBeEnabled();
});

test('the automatic refresh interval is saved from RSS Beslemeleri', async ({ page }) => {
  // #27: the interval was stored but never used and could not be changed in the UI
  await loginAs(page, ADMIN_USER);
  await mockApi(page, { articles: [], settings: { feed_refresh_interval: 3600 } });
  await page.goto('/');
  await page.getByRole('button', { name: 'Ayarlar' }).click();
  await page.getByRole('button', { name: 'RSS Beslemeleri' }).click();

  const select = page.getByLabel('Otomatik yenileme aralığı');
  await expect(select).toHaveValue('3600');
  await select.selectOption({ label: '2 saat' });

  const req = page.waitForRequest(
    (r) => r.url().endsWith('/api/settings/') && r.method() === 'PUT' && r.postDataJSON().feed_refresh_interval === 7200
  );
  await page.getByRole('button', { name: 'Aralığı kaydet' }).click();
  await req;
  await expect(page.getByRole('button', { name: 'Aralığı kaydet' })).toBeDisabled();
});
