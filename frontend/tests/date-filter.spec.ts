import { test, expect } from '@playwright/test';
import { loginAs } from './helpers/auth';
import { mockApi, makeArticle } from './helpers/mockApi';

function daysAgoIso(days: number, hour = 12): string {
  const d = new Date();
  d.setDate(d.getDate() - days);
  d.setHours(hour, 0, 0, 0);
  return d.toISOString();
}

function dateInputValue(daysAgo: number): string {
  const d = new Date();
  d.setDate(d.getDate() - daysAgo);
  return d.toISOString().slice(0, 10);
}

function fixtures() {
  return [
    makeArticle({ title: 'Today Article', is_read: false, published_at: daysAgoIso(0) }),
    makeArticle({ title: 'This Week Article', is_read: false, published_at: daysAgoIso(3) }),
    makeArticle({ title: 'Old Article', is_read: false, published_at: daysAgoIso(10) }),
  ];
}

const pubSection = (page: import('@playwright/test').Page) =>
  page.locator('.date-filter-section').filter({ hasText: 'Yayın Tarihi' });
const fetchSection = (page: import('@playwright/test').Page) =>
  page.locator('.date-filter-section').filter({ hasText: 'İşlenme Tarihi' });

test('"Bugün" preset on Yayın Tarihi sends a same-day published_from/to range', async ({ page }) => {
  await loginAs(page);
  await mockApi(page, { articles: fixtures() });
  await page.goto('/');

  await pubSection(page).getByLabel('Bugün').click();

  await expect(page.getByText('Today Article')).toBeVisible();
  await expect(page.getByText('This Week Article')).not.toBeVisible();
  await expect(page.getByText('Old Article')).not.toBeVisible();
});

test('"Son 1 Hafta" preset sends a 7-day range', async ({ page }) => {
  await loginAs(page);
  await mockApi(page, { articles: fixtures() });
  await page.goto('/');

  await pubSection(page).getByLabel('Son 1 Hafta').click();

  await expect(page.getByText('Today Article')).toBeVisible();
  await expect(page.getByText('This Week Article')).toBeVisible();
  await expect(page.getByText('Old Article')).not.toBeVisible();
});

test('"Özel Tarih" reveals date inputs and sends the chosen custom range', async ({ page }) => {
  await loginAs(page);
  await mockApi(page, { articles: fixtures() });
  await page.goto('/');

  const section = pubSection(page);
  await section.getByLabel('Özel Tarih').click();

  const dateInputs = section.locator('input[type="date"]');
  await dateInputs.nth(0).fill(dateInputValue(12));
  await dateInputs.nth(1).fill(dateInputValue(8));

  await expect(page.getByText('Old Article')).toBeVisible();
  await expect(page.getByText('This Week Article')).not.toBeVisible();
  await expect(page.getByText('Today Article')).not.toBeVisible();
});

test('İşlenme Tarihi section filters independently using fetched_from/to', async ({ page }) => {
  await loginAs(page);
  await mockApi(page, {
    articles: [
      makeArticle({ title: 'Fetched Today', is_read: false, fetched_at: daysAgoIso(0) }),
      makeArticle({ title: 'Fetched Long Ago', is_read: false, fetched_at: daysAgoIso(10) }),
    ],
  });
  await page.goto('/');

  const req = page.waitForRequest((r) => !!new URL(r.url()).searchParams.get('fetched_from'));
  await fetchSection(page).getByLabel('Bugün').click();
  await req;

  await expect(page.getByText('Fetched Today')).toBeVisible();
  await expect(page.getByText('Fetched Long Ago')).not.toBeVisible();
});

test('re-selecting the same preset clears it', async ({ page }) => {
  await loginAs(page);
  await mockApi(page, { articles: fixtures() });
  await page.goto('/');

  const section = pubSection(page);
  await section.getByLabel('Bugün').click();
  await expect(page.getByText('Old Article')).not.toBeVisible();

  await section.getByLabel('Bugün').click();

  await expect(page.getByText('Today Article')).toBeVisible();
  await expect(page.getByText('This Week Article')).toBeVisible();
  await expect(page.getByText('Old Article')).toBeVisible();
});
