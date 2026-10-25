import { test, expect } from '@playwright/test';
import { loginAs } from './helpers/auth';
import { mockApi, makeFeed } from './helpers/mockApi';

const FEED_A = makeFeed({ id: 101, title: 'DW News' });

test('filter panel collapses, expands and remembers its state', async ({ page }) => {
  await loginAs(page);
  await mockApi(page, { feeds: [FEED_A], articles: [] });
  await page.goto('/');
  await page.getByRole('button', { name: 'Haberler', exact: true }).click();

  await expect(page.getByLabel('Tüm Beslemeler')).toBeVisible();

  await page.getByRole('button', { name: 'Filtreleri gizle' }).click();
  await expect(page.getByLabel('Tüm Beslemeler')).toBeHidden();
  await expect(page.getByRole('button', { name: 'Filtreleri göster' })).toBeVisible();

  // Collapsed state survives a reload
  await page.reload();
  await page.getByRole('button', { name: 'Haberler', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Filtreleri göster' })).toBeVisible();
  await expect(page.getByLabel('Tüm Beslemeler')).toBeHidden();

  await page.getByRole('button', { name: 'Filtreleri göster' }).click();
  await expect(page.getByLabel('Tüm Beslemeler')).toBeVisible();
});

test('collapsed panel keeps the active filter selection and shows an indicator', async ({ page }) => {
  await loginAs(page);
  await mockApi(page, { feeds: [FEED_A], articles: [] });
  await page.goto('/');
  await page.getByRole('button', { name: 'Haberler', exact: true }).click();

  await page.getByLabel('DW News').click();
  await page.getByRole('button', { name: 'Filtreleri gizle' }).click();
  await expect(page.getByTestId('filters-active-dot')).toBeVisible();

  await page.getByRole('button', { name: 'Filtreleri göster' }).click();
  await expect(page.getByLabel('DW News')).toBeChecked();
});

test('filter panel sits near the left edge on wide screens (not in a centered column)', async ({ page }) => {
  await page.setViewportSize({ width: 1920, height: 1000 });
  await loginAs(page);
  await mockApi(page, { feeds: [FEED_A], articles: [] });
  await page.goto('/');
  await page.getByRole('button', { name: 'Haberler', exact: true }).click();

  await page.getByRole('button', { name: 'Filtreleri gizle' }).click();
  const box = await page.getByRole('button', { name: 'Filtreleri göster' }).boundingBox();
  // a small gutter (≤3rem + sidebar padding), not the ~276px of the old centered 1400px column
  expect(box!.x).toBeGreaterThan(16);
  expect(box!.x).toBeLessThan(80);
});
