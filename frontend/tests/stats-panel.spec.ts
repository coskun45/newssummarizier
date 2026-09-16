import { test, expect } from '@playwright/test';
import { loginAs } from './helpers/auth';
import { mockApi, makeArticle, makeFeed, makeTopic } from './helpers/mockApi';

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
  await expect(medCard).toContainText('1');

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
