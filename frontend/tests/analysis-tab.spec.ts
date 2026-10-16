import { test, expect, type Page } from '@playwright/test';
import { ADMIN_USER, loginAs } from './helpers/auth';
import { mockApi, type MockApiOverrides } from './helpers/mockApi';

const totals = { high: 6, med: 10, low: 4, total: 20, high_ratio: 0.3, prev_high_ratio: 0.2 };

const analysisStats: MockApiOverrides['analysisStats'] = {
  totals,
  topics: [
    { topic_id: 1, name: 'Savaş', color: '#dc2626', high: 5, med: 2, low: 0, total: 7 },
    { topic_id: 2, name: 'Spor', color: null, high: 0, med: 3, low: 4, total: 7 },
  ],
  feeds: [
    { feed_id: 1, title: 'DW - Deutsche Welle', high: 6, med: 10, low: 4, total: 20, high_ratio: 0.3 },
  ],
};

async function openAnalysis(page: Page) {
  await page.goto('/');
  await page.getByRole('button', { name: 'Analiz', exact: true }).click();
}

test('Analiz sits right after Playground in the header', async ({ page }) => {
  await loginAs(page, ADMIN_USER);
  await mockApi(page, { articles: [] });
  await page.goto('/');

  const navLabels = await page.locator('.header-nav').getByRole('button').allTextContents();
  const playgroundIndex = navLabels.findIndex((label) => label.trim() === 'Playground');
  expect(playgroundIndex).toBeGreaterThanOrEqual(0);
  expect(navLabels[playgroundIndex + 1]?.trim()).toBe('Analiz');
});

test('Analiz shows KPIs, trend, topic heatmap and feed profile and hides the news view', async ({ page }) => {
  await loginAs(page);
  await mockApi(page, { articles: [], analysisStats });
  await openAnalysis(page);

  await expect(page.getByRole('heading', { name: 'Analiz' })).toBeVisible();
  await expect(page.locator('.dashboard-sidebar')).not.toBeVisible();
  // The news list's own toolbar lives in the main area, not the sidebar.
  await expect(page.getByRole('button', { name: 'Okunmamışlar' })).not.toBeVisible();

  await expect(page.getByText('Toplam haber')).toBeVisible();
  await expect(page.getByText('Gündem gerginliği')).toBeVisible();
  await expect(page.getByText('%30', { exact: true }).first()).toBeVisible();
  await expect(page.getByText('↑ 10 puan (önceki 30 gün)')).toBeVisible();

  await expect(page.getByRole('heading', { name: 'Önem trendi' })).toBeVisible();
  await expect(page.getByRole('img', { name: 'Son 30 gün önem seviyesine göre haber sayıları' })).toBeVisible();

  await expect(page.getByRole('heading', { name: 'Konu × önem' })).toBeVisible();
  const topicRows = page.getByRole('row').filter({ has: page.getByRole('rowheader') });
  await expect(topicRows.filter({ hasText: 'Savaş' })).toContainText('5');
  await expect(topicRows.filter({ hasText: 'Spor' })).toBeVisible();

  await expect(page.getByRole('heading', { name: 'Kaynak profili' })).toBeVisible();
  await expect(page.getByRole('rowheader', { name: 'DW - Deutsche Welle' })).toBeVisible();
});

test('range selector requests 7/30/90 days, defaulting to 30', async ({ page }) => {
  await loginAs(page);
  const state = await mockApi(page, { articles: [], analysisStats });
  await openAnalysis(page);

  await expect(page.getByRole('button', { name: '30 gün' })).toHaveAttribute('aria-pressed', 'true');
  await expect.poll(() => state.analysisRequests).toEqual([30]);

  await page.getByRole('button', { name: '7 gün' }).click();
  await expect(page.getByRole('button', { name: '7 gün' })).toHaveAttribute('aria-pressed', 'true');
  await expect(page.getByRole('img', { name: 'Son 7 gün önem seviyesine göre haber sayıları' })).toBeVisible();

  await page.getByRole('button', { name: '90 gün' }).click();
  await expect(page.getByRole('img', { name: 'Son 90 gün önem seviyesine göre haber sayıları' })).toBeVisible();
  expect(state.analysisRequests).toEqual([30, 7, 90]);
});

test('Analiz shows an empty state when the range has no labelled articles', async ({ page }) => {
  await loginAs(page);
  await mockApi(page, { articles: [] });
  await openAnalysis(page);

  await expect(page.getByText('Bu aralıkta analiz edilecek haber yok.')).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Önem trendi' })).not.toBeVisible();
});

test('Analiz explains a missing previous period and a range without topics', async ({ page }) => {
  await loginAs(page);
  await mockApi(page, {
    articles: [],
    analysisStats: { ...analysisStats, totals: { ...totals, prev_high_ratio: null }, topics: [] },
  });
  await openAnalysis(page);

  await expect(page.getByText('Önceki dönem verisi yok')).toBeVisible();
  await expect(page.getByText('Bu aralıkta konu atanmış haber yok.')).toBeVisible();
  await expect(page.getByRole('rowheader', { name: 'DW - Deutsche Welle' })).toBeVisible();
});

test('Analiz shows an error when the analysis cannot be loaded', async ({ page }) => {
  await loginAs(page);
  await mockApi(page, { articles: [] });
  await page.route('**/api/stats/analysis**', (route) => route.fulfill({ status: 500, json: { detail: 'boom' } }));
  await openAnalysis(page);

  await expect(page.getByText('Analiz verileri yüklenemedi.')).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Önem trendi' })).not.toBeVisible();
});

test('a failed background refresh keeps the last analysis on screen', async ({ page }) => {
  await page.clock.install();
  await loginAs(page);
  await mockApi(page, { articles: [], analysisStats });
  await openAnalysis(page);
  await expect(page.getByText('Toplam haber')).toBeVisible();

  let failedRequests = 0;
  await page.route('**/api/stats/analysis**', (route) => {
    failedRequests += 1;
    return route.fulfill({ status: 500, json: { detail: 'boom' } });
  });
  await page.clock.fastForward('05:01'); // the 5-minute refetchInterval fires
  await expect.poll(() => failedRequests).toBe(1);
  await page.clock.fastForward('00:05'); // past the single retry's back-off
  await expect.poll(() => failedRequests).toBe(2);

  await expect(page.getByText('Veriler yenilenemedi; son alınan veriler gösteriliyor.')).toBeVisible();
  await expect(page.getByText('Toplam haber')).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Önem trendi' })).toBeVisible();
  await expect(page.getByText('Analiz verileri yüklenemedi.')).not.toBeVisible();
});

test.describe('west of UTC', () => {
  test.use({ timezoneId: 'America/New_York' });

  test('trend date labels show the API day, not the day before', async ({ page }) => {
    const dates = ['2026-02-23', '2026-02-24', '2026-02-25', '2026-02-26', '2026-02-27', '2026-02-28', '2026-03-01'];
    await loginAs(page);
    await mockApi(page, {
      articles: [],
      analysisStats: { ...analysisStats, trend: dates.map((date) => ({ date, high: 1, med: 0, low: 0, total: 1 })) },
    });
    await openAnalysis(page);

    const chart = page.getByRole('img', { name: 'Son 7 gün önem seviyesine göre haber sayıları' });
    await expect(chart).toContainText('23 Şub');
    await expect(chart).toContainText('1 Mar');
    await expect(chart).not.toContainText('22 Şub');
  });
});
