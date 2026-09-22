import { test, expect } from '@playwright/test';
import { loginAs } from './helpers/auth';
import { mockApi } from './helpers/mockApi';

test('Analiz sits right after Playground in the header', async ({ page }) => {
  await loginAs(page);
  await mockApi(page, { articles: [] });
  await page.goto('/');

  const navLabels = await page.locator('.header-nav').getByRole('button').allTextContents();
  const playgroundIndex = navLabels.findIndex((label) => label.trim() === 'Playground');
  expect(playgroundIndex).toBeGreaterThanOrEqual(0);
  expect(navLabels[playgroundIndex + 1]?.trim()).toBe('Analiz');
});

test('clicking Analiz shows the Coming soon placeholder and hides the news view', async ({ page }) => {
  await loginAs(page);
  await mockApi(page, { articles: [] });
  await page.goto('/');

  await page.getByRole('button', { name: 'Analiz', exact: true }).click();

  await expect(page.getByRole('heading', { name: 'Analiz' })).toBeVisible();
  await expect(page.getByText('Coming soon')).toBeVisible();
  await expect(page.locator('.dashboard-sidebar')).not.toBeVisible();
  await expect(page.getByRole('button', { name: 'Okunmamışlar' })).not.toBeVisible();
});
