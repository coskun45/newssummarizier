import { test, expect } from '@playwright/test';
import { loginAs } from './helpers/auth';
import { mockApi, makeArticle } from './helpers/mockApi';

test('Ana Sayfa is the default view and shows the hero carousel, not the article list', async ({ page }) => {
  await loginAs(page);
  await mockApi(page, {
    articles: [makeArticle({ title: 'Default View Hero Story', priority: 'high', is_read: true })],
  });
  await page.goto('/');

  await expect(page.getByText('Default View Hero Story')).toBeVisible();
  await expect(page.getByRole('button', { name: 'Okunmamışlar' })).not.toBeVisible();
  await expect(page.locator('.dashboard-sidebar')).not.toBeVisible();
  await expect(page.locator('.bulletin-panel')).not.toBeVisible();
});

test('clicking Haberler shows the article tabs and sidebar', async ({ page }) => {
  await loginAs(page);
  await mockApi(page, { articles: [] });
  await page.goto('/');

  await page.getByRole('button', { name: 'Haberler', exact: true }).click();

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

  await page.getByRole('button', { name: 'Haberler', exact: true }).click();

  await expect(page.locator('.bulletin-panel')).not.toBeVisible();
  await expect(page.getByRole('button', { name: 'Okunmamışlar' })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Arşiv', exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Favori' })).toBeVisible();
  await expect(page.locator('.dashboard-sidebar')).toBeVisible();
});
