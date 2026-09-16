import { test, expect } from '@playwright/test';
import { loginAs } from './helpers/auth';
import { mockApi } from './helpers/mockApi';

test('Haberler is the default view and shows the article tabs and sidebar', async ({ page }) => {
  await loginAs(page);
  await mockApi(page, { articles: [] });
  await page.goto('/');

  await expect(page.getByRole('button', { name: 'Okunmamışlar' })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Arşiv', exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Favori' })).toBeVisible();
  await expect(page.locator('.dashboard-sidebar')).toBeVisible();
  await expect(page.locator('.bulletin-panel')).not.toBeVisible();
});

test('clicking Bülten in the header shows the bulletin panel and hides the news tabs', async ({ page }) => {
  await loginAs(page);
  await mockApi(page, { articles: [] });
  await page.goto('/');

  await page.getByRole('button', { name: 'Bülten' }).click();

  await expect(page.locator('.bulletin-panel')).toBeVisible();
  await expect(page.locator('.dashboard-sidebar')).not.toBeVisible();
  await expect(page.getByRole('button', { name: 'Okunmamışlar' })).not.toBeVisible();
  await expect(page.getByRole('button', { name: 'Arşiv', exact: true })).not.toBeVisible();
  await expect(page.getByRole('button', { name: 'Favori' })).not.toBeVisible();
});

test('clicking Haberler after Bülten restores the news tabs and sidebar', async ({ page }) => {
  await loginAs(page);
  await mockApi(page, { articles: [] });
  await page.goto('/');

  await page.getByRole('button', { name: 'Bülten' }).click();
  await expect(page.locator('.bulletin-panel')).toBeVisible();

  await page.getByRole('button', { name: 'Haberler' }).click();

  await expect(page.locator('.bulletin-panel')).not.toBeVisible();
  await expect(page.getByRole('button', { name: 'Okunmamışlar' })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Arşiv', exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Favori' })).toBeVisible();
  await expect(page.locator('.dashboard-sidebar')).toBeVisible();
});
