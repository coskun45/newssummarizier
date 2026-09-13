import { test, expect } from '@playwright/test';
import { loginAs } from './helpers/auth';
import { mockApi, makeArticle } from './helpers/mockApi';

async function mockLargeTotal(page: import('@playwright/test').Page, total: number) {
  const fixed = [makeArticle({ title: 'Page Item', is_read: false })];
  await page.route((url) => url.pathname === '/api/articles/', (route) => {
    const u = new URL(route.request().url());
    const skip = parseInt(u.searchParams.get('skip') ?? '0', 10);
    const limit = parseInt(u.searchParams.get('limit') ?? '20', 10);
    route.fulfill({ json: { articles: fixed, total, skip, limit } });
  });
}

test('hidden when totalPages <= 1', async ({ page }) => {
  await loginAs(page);
  await mockApi(page, { articles: [makeArticle({ title: 'Only One', is_read: false })] });
  await page.goto('/');

  await expect(page.getByRole('navigation', { name: 'Sayfalama' })).not.toBeVisible();
});

test('next/prev buttons navigate and send correct skip', async ({ page }) => {
  await loginAs(page);
  await mockApi(page, { articles: [] });
  await mockLargeTotal(page, 45);
  await page.goto('/');

  await expect(page.getByRole('navigation', { name: 'Sayfalama' })).toBeVisible();

  const req = page.waitForRequest((r) => new URL(r.url()).searchParams.get('skip') === '20');
  await page.getByRole('button', { name: 'Sonraki sayfa' }).click();
  await req;

  await expect(page.getByRole('button', { name: '2', exact: true })).toHaveAttribute('aria-current', 'page');

  // Page 1 (skip=0) was already fetched on initial load and is still fresh
  // (staleTime), so React Query serves it from cache — no second request fires.
  await page.getByRole('button', { name: 'Önceki sayfa' }).click();

  await expect(page.getByRole('button', { name: '1', exact: true })).toHaveAttribute('aria-current', 'page');
});

test('prev button disabled on first page, next disabled on last page', async ({ page }) => {
  await loginAs(page);
  await mockApi(page, { articles: [] });
  await mockLargeTotal(page, 45); // 3 pages
  await page.goto('/');

  await expect(page.getByRole('button', { name: 'Önceki sayfa' })).toBeDisabled();

  await page.getByRole('button', { name: '3', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Sonraki sayfa' })).toBeDisabled();
});

test('clicking a specific page number navigates directly', async ({ page }) => {
  await loginAs(page);
  await mockApi(page, { articles: [] });
  await mockLargeTotal(page, 45); // 3 pages
  await page.goto('/');

  const req = page.waitForRequest((r) => new URL(r.url()).searchParams.get('skip') === '20');
  await page.getByRole('button', { name: '2', exact: true }).click();
  await req;

  await expect(page.getByRole('button', { name: '2', exact: true })).toHaveAttribute('aria-current', 'page');
});

test('ellipsis appears for a large page count and jumps to the last page', async ({ page }) => {
  await loginAs(page);
  await mockApi(page, { articles: [] });
  await mockLargeTotal(page, 400); // 20 pages
  await page.goto('/');

  await expect(page.locator('.pagination-ellipsis')).toBeVisible();

  const req = page.waitForRequest((r) => new URL(r.url()).searchParams.get('skip') === '380');
  await page.getByRole('button', { name: '20', exact: true }).click();
  await req;

  await expect(page.getByRole('button', { name: '20', exact: true })).toHaveAttribute('aria-current', 'page');
});
