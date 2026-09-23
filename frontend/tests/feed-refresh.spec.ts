import { test, expect, type Page } from '@playwright/test';
import { loginAs } from './helpers/auth';
import { mockApi, makeArticle, makeFeed } from './helpers/mockApi';

const FEED_A = makeFeed({ id: 1, title: 'DW - Deutsche Welle' });
const FEED_B = makeFeed({ id: 2, title: 'Guardian' });

type Status = { status: string; new_articles?: number; processed?: number };

/** Answer refresh-status per feed: `running` for the first poll, then the given final status.
 * Registered after mockApi(), so it takes precedence over the mock's always-idle handler. */
async function mockRefreshStatus(page: Page, finals: Record<number, Status>) {
  const polls: Record<number, number> = {};
  await page.route(/\/api\/feeds\/\d+\/refresh-status$/, (route) => {
    const id = parseInt(new URL(route.request().url()).pathname.split('/')[3], 10);
    polls[id] = (polls[id] ?? 0) + 1;
    return route.fulfill({ json: polls[id] === 1 ? { status: 'running' } : finals[id] });
  });
  return polls;
}

async function openNews(page: Page) {
  await page.goto('/');
  await page.getByRole('button', { name: 'Haberler', exact: true }).click();
}

test('refresh with all feeds refreshes every feed, shows progress, then the aggregated result', async ({ page }) => {
  await loginAs(page);
  const state = await mockApi(page, { feeds: [FEED_A, FEED_B], articles: [makeArticle({ title: 'Old News' })] });
  const polls = await mockRefreshStatus(page, {
    1: { status: 'done', new_articles: 2, processed: 3 },
    2: { status: 'done', new_articles: 1, processed: 1 },
  });
  await openNews(page);

  const refreshed: number[] = [];
  page.on('request', (r) => {
    const m = r.url().match(/\/api\/feeds\/(\d+)\/refresh$/);
    if (m && r.method() === 'POST') refreshed.push(parseInt(m[1], 10));
  });

  // Once polling finishes, the list must be refetched to show the new articles
  const button = page.getByRole('button', { name: 'Haberleri Güncelle' });
  await button.click();
  await expect(page.getByText('Makaleler işleniyor...')).toBeVisible();
  await expect(button).toBeDisabled();
  state.articles.push(makeArticle({ title: 'Fresh From RSS' }));

  await expect(page.getByText('3 yeni makale eklendi (4 işlendi)')).toBeVisible({ timeout: 10_000 });
  expect(refreshed.sort()).toEqual([1, 2]);
  expect(polls[1]).toBeGreaterThanOrEqual(2);
  expect(polls[2]).toBeGreaterThanOrEqual(2);
  await expect(button).toBeEnabled();
  await expect(page.getByText('Fresh From RSS')).toBeVisible();

  // The result message disappears after a few seconds
  await expect(page.getByText('3 yeni makale eklendi (4 işlendi)')).not.toBeVisible({ timeout: 8_000 });
});

test('refresh only targets the feeds selected in the sidebar', async ({ page }) => {
  await loginAs(page);
  await mockApi(page, { feeds: [FEED_A, FEED_B] });
  await mockRefreshStatus(page, { 2: { status: 'done', new_articles: 0, processed: 5 } });
  await openNews(page);

  await page.getByLabel('Guardian').check();

  const refreshed: number[] = [];
  page.on('request', (r) => {
    const m = r.url().match(/\/api\/feeds\/(\d+)\/refresh$/);
    if (m && r.method() === 'POST') refreshed.push(parseInt(m[1], 10));
  });
  await page.getByRole('button', { name: 'Haberleri Güncelle' }).click();

  await expect(page.getByText('5 makale işlendi, yeni makale yok')).toBeVisible({ timeout: 10_000 });
  expect(refreshed).toEqual([2]);
});

test('a failed refresh request resets the button without a result message', async ({ page }) => {
  await loginAs(page);
  await mockApi(page, { feeds: [FEED_A] });
  await page.route(/\/api\/feeds\/\d+\/refresh$/, (route) =>
    route.fulfill({ status: 500, json: { detail: 'boom' } })
  );
  await openNews(page);

  const button = page.getByRole('button', { name: 'Haberleri Güncelle' });
  await button.click();

  await expect(button).toBeEnabled();
  await expect(page.getByText('Makaleler işleniyor...')).not.toBeVisible();
  await expect(page.getByText(/yeni makale/)).toHaveCount(0);
});
