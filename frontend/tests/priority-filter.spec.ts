import { test, expect } from '@playwright/test';
import { loginAs } from './helpers/auth';
import { mockApi, makeArticle } from './helpers/mockApi';

function fixtures() {
  return [
    makeArticle({ title: 'High Prio', is_read: false, priority: 'high' }),
    makeArticle({ title: 'Med Prio', is_read: false, priority: 'med' }),
    // The "Önemsiz" checkbox maps to `status=filtered` in the list query
    // (Dashboard.tsx), not the separate `importance` column — the dedicated
    // .../unimportant/* bulk endpoints are the ones that use `importance`.
    makeArticle({ title: 'Unimportant One', is_read: false, importance: 'unimportant', status: 'filtered' }),
  ];
}

test('selecting a priority filters the list', async ({ page }) => {
  await loginAs(page);
  await mockApi(page, { articles: fixtures() });
  await page.goto('/');

  const req = page.waitForRequest((r) => new URL(r.url()).searchParams.get('priority') === 'high');
  await page.getByLabel('Yüksek').click();
  await req;

  await expect(page.getByText('High Prio')).toBeVisible();
  await expect(page.getByText('Med Prio')).not.toBeVisible();
});

test('selecting a priority is single-select', async ({ page }) => {
  await loginAs(page);
  await mockApi(page, { articles: fixtures() });
  await page.goto('/');

  await page.getByLabel('Yüksek').click();
  await expect(page.getByLabel('Yüksek')).toBeChecked();

  const req = page.waitForRequest((r) => new URL(r.url()).searchParams.get('priority') === 'med');
  await page.getByLabel('Orta').click();
  await req;

  await expect(page.getByLabel('Yüksek')).not.toBeChecked();
  await expect(page.getByLabel('Orta')).toBeChecked();
  await expect(page.getByText('Med Prio')).toBeVisible();
  await expect(page.getByText('High Prio')).not.toBeVisible();
});

test('unchecking the active priority clears the filter', async ({ page }) => {
  await loginAs(page);
  await mockApi(page, { articles: fixtures() });
  await page.goto('/');

  await page.getByLabel('Yüksek').click();
  await expect(page.getByText('Med Prio')).not.toBeVisible();

  await page.getByLabel('Yüksek').click();

  await expect(page.getByText('High Prio')).toBeVisible();
  await expect(page.getByText('Med Prio')).toBeVisible();
});

test('"Önemsiz" checkbox filters unimportant articles independently of priority', async ({ page }) => {
  await loginAs(page);
  await mockApi(page, { articles: fixtures() });
  await page.goto('/');

  await page.getByLabel('Önemsiz').click();

  await expect(page.getByText('Unimportant One')).toBeVisible();
  await expect(page.getByText('High Prio')).not.toBeVisible();
  await expect(page.getByText('Med Prio')).not.toBeVisible();
});

test('priority count badges match articleCounts.by_priority', async ({ page }) => {
  await loginAs(page);
  await mockApi(page, {
    articles: [
      ...fixtures(),
      makeArticle({ title: 'High Prio 2', is_read: false, priority: 'high' }),
    ],
  });
  await page.goto('/');

  const highRow = page.locator('.topic-item').filter({ hasText: 'Yüksek' });
  await expect(highRow).toContainText('2');
});
