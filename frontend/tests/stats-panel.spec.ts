import { test, expect } from '@playwright/test';
import { loginAs } from './helpers/auth';
import { mockApi, makeArticle, makeFeed, makeTopic, makeDailyArticleStats } from './helpers/mockApi';

test('shows feed/priority/archive/favorite/category stats on Ana Sayfa without any click', async ({ page }) => {
  await loginAs(page);
  const feedA = makeFeed({ title: 'DW News' });
  const feedB = makeFeed({ title: 'Tech Feed' });
  const politics = makeTopic({ name: 'Politics', color: '#3b82f6' });

  await mockApi(page, {
    feeds: [feedA, feedB],
    topics: [politics],
    articles: [
      makeArticle({ priority: 'high', is_read: false, topics: [politics] }),
      makeArticle({ priority: 'high', is_read: false }),
      makeArticle({ priority: 'med', is_read: false, topics: [politics] }),
      makeArticle({ priority: 'low', is_read: false }),
      makeArticle({ priority: 'high', is_read: true }),
      makeArticle({ is_starred: true, is_read: false }),
    ],
  });

  await page.goto('/');

  await expect(page.getByRole('heading', { name: 'İstatistikler' })).toBeVisible();

  const rssTile = page.locator('.stats-tile').filter({ hasText: 'RSS Kaynağı' });
  await expect(rssTile).toContainText('2');

  // 5 of the 6 fixture articles are unread (the 6th is archived) - its own tile, separate from RSS.
  const unreadTile = page.locator('.stats-tile').filter({ hasText: 'Okunmamış Haber' });
  await expect(unreadTile).toContainText('5');

  const archiveTile = page.locator('.stats-tile').filter({ hasText: 'Arşiv' });
  await expect(archiveTile).toContainText('1');

  const favoriteTile = page.locator('.stats-tile').filter({ hasText: 'Favori' });
  await expect(favoriteTile).toContainText('1');

  const highCard = page.locator('.stats-priority-card').filter({ hasText: 'Yüksek' });
  await expect(highCard).toContainText('2');

  const medCard = page.locator('.stats-priority-card').filter({ hasText: 'Orta' });
  // 1 explicit 'med' article + the starred one (mock default priority is 'med')
  await expect(medCard).toContainText('2');

  const lowCard = page.locator('.stats-priority-card').filter({ hasText: 'Düşük' });
  await expect(lowCard).toContainText('1');

  const politicsBadge = page.locator('.topic-badge').filter({ hasText: 'Politics' });
  await expect(politicsBadge).toContainText('2');
});

test('shows zeroed stats and an empty-category message with no data', async ({ page }) => {
  await loginAs(page);
  await mockApi(page, { feeds: [], topics: [], articles: [] });

  await page.goto('/');

  const rssTile = page.locator('.stats-tile').filter({ hasText: 'RSS Kaynağı' });
  await expect(rssTile).toContainText('0');
  const unreadTile = page.locator('.stats-tile').filter({ hasText: 'Okunmamış Haber' });
  await expect(unreadTile).toContainText('0');
  const archiveTile = page.locator('.stats-tile').filter({ hasText: 'Arşiv' });
  await expect(archiveTile).toContainText('0');
  const favoriteTile = page.locator('.stats-tile').filter({ hasText: 'Favori' });
  await expect(favoriteTile).toContainText('0');

  const highCard = page.locator('.stats-priority-card').filter({ hasText: 'Yüksek' });
  await expect(highCard).toContainText('0');
  await expect(page.getByText('Henüz kategori yok')).toBeVisible();
});

test('shows the last 7 days daily incoming/processed article chart with a Bugün callout', async ({ page }) => {
  await loginAs(page);
  const days = Array.from({ length: 7 }, (_, i) => {
    const d = new Date();
    d.setUTCDate(d.getUTCDate() - (6 - i));
    return { date: d.toISOString().slice(0, 10), incoming: 10 + i, processed: 8 + i };
  });
  const dailyArticleStats = makeDailyArticleStats({ days, today: days[days.length - 1] });

  await mockApi(page, { feeds: [], topics: [], articles: [], dailyArticleStats });

  await page.goto('/');

  await expect(page.getByRole('heading', { name: 'Son 7 Gün' })).toBeVisible();

  const todayBlock = page.locator('.stats-daily-today');
  await expect(todayBlock).toContainText(String(dailyArticleStats.today.incoming));
  await expect(todayBlock).toContainText(String(dailyArticleStats.today.processed));

  await expect(page.locator('.stats-daily-day')).toHaveCount(7);
});
