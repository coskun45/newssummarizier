import { test, expect } from '@playwright/test';
import { loginAs } from './helpers/auth';
import { mockApi, makeFeed, makeArticle } from './helpers/mockApi';

const FEED_A = makeFeed({ id: 101, title: 'DW News' });
const FEED_B = makeFeed({ id: 102, title: 'Tech Feed' });

test('all feeds selected by default (Tüm Beslemeler checked)', async ({ page }) => {
  await loginAs(page);
  await mockApi(page, { feeds: [FEED_A, FEED_B], articles: [] });
  await page.goto('/');

  await expect(page.getByLabel('Tüm Beslemeler')).toBeChecked();
});

test('selecting one feed filters the list and unchecks "all"', async ({ page }) => {
  await loginAs(page);
  await mockApi(page, {
    feeds: [FEED_A, FEED_B],
    articles: [
      makeArticle({ title: 'From A', is_read: false, feedId: FEED_A.id }),
      makeArticle({ title: 'From B', is_read: false, feedId: FEED_B.id }),
    ],
  });
  await page.goto('/');

  const req = page.waitForRequest((r) => r.url().includes(`feed_ids=${FEED_A.id}`));
  await page.getByLabel('DW News').click();
  await req;

  await expect(page.getByText('From A')).toBeVisible();
  await expect(page.getByText('From B')).not.toBeVisible();
  await expect(page.getByLabel('Tüm Beslemeler')).not.toBeChecked();
});

test('selecting multiple feeds sends comma-separated feed_ids', async ({ page }) => {
  await loginAs(page);
  await mockApi(page, {
    feeds: [FEED_A, FEED_B],
    articles: [
      makeArticle({ title: 'From A', is_read: false, feedId: FEED_A.id }),
      makeArticle({ title: 'From B', is_read: false, feedId: FEED_B.id }),
    ],
  });
  await page.goto('/');

  await page.getByLabel('DW News').click();
  const req = page.waitForRequest((r) => {
    const ids = new URL(r.url()).searchParams.get('feed_ids');
    return !!ids && ids.includes(String(FEED_A.id)) && ids.includes(String(FEED_B.id));
  });
  await page.getByLabel('Tech Feed').click();
  await req;

  await expect(page.getByText('From A')).toBeVisible();
  await expect(page.getByText('From B')).toBeVisible();
});

test('clicking "Tüm Beslemeler" clears the selection', async ({ page }) => {
  await loginAs(page);
  await mockApi(page, {
    feeds: [FEED_A, FEED_B],
    articles: [
      makeArticle({ title: 'From A', is_read: false, feedId: FEED_A.id }),
      makeArticle({ title: 'From B', is_read: false, feedId: FEED_B.id }),
    ],
  });
  await page.goto('/');

  await page.getByLabel('DW News').click();
  await expect(page.getByText('From B')).not.toBeVisible();

  await page.getByLabel('Tüm Beslemeler').click();

  await expect(page.getByText('From A')).toBeVisible();
  await expect(page.getByText('From B')).toBeVisible();
  await expect(page.getByLabel('Tüm Beslemeler')).toBeChecked();
});

test('feed count badge matches articleCounts.by_feed', async ({ page }) => {
  await loginAs(page);
  await mockApi(page, {
    feeds: [FEED_A, FEED_B],
    articles: [
      makeArticle({ title: 'From A 1', is_read: false, feedId: FEED_A.id }),
      makeArticle({ title: 'From A 2', is_read: true, feedId: FEED_A.id }),
      makeArticle({ title: 'From B', is_read: false, feedId: FEED_B.id }),
    ],
  });
  await page.goto('/');

  const feedARow = page.locator('.topic-item').filter({ hasText: 'DW News' });
  await expect(feedARow).toContainText('2');
  const feedBRow = page.locator('.topic-item').filter({ hasText: 'Tech Feed' });
  await expect(feedBRow).toContainText('1');
});
