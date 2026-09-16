import { test, expect } from '@playwright/test';
import { loginAs } from './helpers/auth';
import { mockApi, makeArticle, makeSummary } from './helpers/mockApi';

function heroFixtures() {
  return [
    makeArticle({ title: 'Hero Story One', priority: 'high', is_read: true, cleaned_content: 'Full body of story one.' }),
    makeArticle({ title: 'Hero Story Two', priority: 'high', is_read: true, cleaned_content: 'Full body of story two.' }),
    makeArticle({ title: 'Hero Story Three', priority: 'high', is_read: true }),
    // Not high priority - must never appear in the hero.
    makeArticle({ title: 'Low Priority Piece', priority: 'low', is_read: false }),
  ];
}

// The hero auto-rotates every 6s on a real interval. Every test but the
// dedicated auto-rotate one below freezes the clock first, so a slow CI/parallel
// run can never let the interval fire mid-test and jump the slide out from
// under an assertion.

test('Ana Sayfa shows the hero carousel with the first high-priority story on load', async ({ page }) => {
  await loginAs(page);
  await mockApi(page, { articles: heroFixtures() });
  await page.clock.install();
  await page.goto('/');

  await expect(page.getByText('Hero Story One')).toBeVisible();
  await expect(page.getByText('Low Priority Piece')).not.toBeVisible();
  await expect(page.getByRole('heading', { name: 'Top News' })).toBeVisible();
  // One pager number per slide, plus the "T" (Tümü) shortcut.
  await expect(page.getByRole('button', { name: '1. haber' })).toBeVisible();
  await expect(page.getByRole('button', { name: '3. haber' })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Tüm haberler' })).toBeVisible();
});

test('shows the Turkish brief summary directly on the card, no image, without needing a click', async ({ page }) => {
  await loginAs(page);
  const story = makeArticle({
    title: 'Hero Story One',
    priority: 'high',
    is_read: true,
    has_summaries: true,
  });
  await mockApi(page, {
    articles: [story],
    summaries: new Map([
      [story.id, [makeSummary(story.id, { summary_type: 'brief', summary_text: 'Kısa Türkçe özet metni.' })]],
    ]),
  });
  await page.clock.install();
  await page.goto('/');

  await expect(page.getByText('Kısa Türkçe özet metni.')).toBeVisible();
  await expect(page.locator('.home-hero-slide')).not.toHaveCSS('background-image', /url/);
});

test('does not render the hero when there are no high-priority articles', async ({ page }) => {
  await loginAs(page);
  await mockApi(page, { articles: [makeArticle({ title: 'Only Medium', priority: 'med', is_read: false })] });
  await page.clock.install();
  await page.goto('/');

  await expect(page.getByText('Only Medium')).not.toBeVisible();
  await expect(page.getByRole('button', { name: '1. haber' })).toHaveCount(0);
});

test('next/prev arrows navigate between slides', async ({ page }) => {
  await loginAs(page);
  await mockApi(page, { articles: heroFixtures() });
  await page.clock.install();
  await page.goto('/');

  await expect(page.getByText('Hero Story One')).toBeVisible();
  await page.getByRole('button', { name: 'Sonraki haber' }).click();
  await expect(page.getByText('Hero Story Two')).toBeVisible();
  await expect(page.getByText('Hero Story One')).not.toBeVisible();

  await page.getByRole('button', { name: 'Önceki haber' }).click();
  await expect(page.getByText('Hero Story One')).toBeVisible();
});

test('clicking a pager number jumps directly to that slide', async ({ page }) => {
  await loginAs(page);
  await mockApi(page, { articles: heroFixtures() });
  await page.clock.install();
  await page.goto('/');

  await page.getByRole('button', { name: '3. haber' }).click();

  await expect(page.getByText('Hero Story Three')).toBeVisible();
  await expect(page.getByText('Hero Story One')).not.toBeVisible();
});

test('the "T" pager button switches to the Haberler list', async ({ page }) => {
  await loginAs(page);
  await mockApi(page, { articles: heroFixtures() });
  await page.clock.install();
  await page.goto('/');

  await page.getByRole('button', { name: 'Tüm haberler' }).click();

  await expect(page.getByRole('button', { name: 'Okunmamışlar' })).toBeVisible();
});

test('clicking a slide opens its detail inline below, without a blocking overlay', async ({ page }) => {
  await loginAs(page);
  await mockApi(page, { articles: heroFixtures() });
  await page.clock.install();
  await page.goto('/');

  await page.getByRole('button', { name: 'Hero Story One' }).click();

  await expect(page.getByText('Full body of story one.')).toBeVisible();
  // Inline, not a modal: no blocking overlay, and the rest of the page (header
  // nav) stays interactive.
  await expect(page.locator('.modal-overlay')).toHaveCount(0);
  await page.getByRole('button', { name: 'Haberler', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Okunmamışlar' })).toBeVisible();
});

test('clicking the open slide again closes the detail panel', async ({ page }) => {
  await loginAs(page);
  await mockApi(page, { articles: heroFixtures() });
  await page.clock.install();
  await page.goto('/');

  await page.getByRole('button', { name: 'Hero Story One' }).click();
  await expect(page.getByText('Full body of story one.')).toBeVisible();

  await page.getByRole('button', { name: 'Hero Story One' }).click();
  await expect(page.getByText('Full body of story one.')).not.toBeVisible();
});

test('auto-rotates to the next slide after the interval', async ({ page }) => {
  await loginAs(page);
  await mockApi(page, { articles: heroFixtures() });
  await page.clock.install();
  await page.goto('/');

  await expect(page.getByText('Hero Story One')).toBeVisible();

  await page.clock.runFor(6500);

  await expect(page.getByText('Hero Story Two')).toBeVisible();
});

test('a background poll that shrinks the high-priority list past the current slide does not crash the hero', async ({ page }) => {
  // Regression test: `useArticles`' 60s refetchInterval can resolve with fewer
  // high-priority articles than before while the hero is sitting on a later
  // slide — `current = articles[index]` was undefined for one render (before
  // the index-clamping effect caught up), and reading `current.published_at`
  // threw, crashing the whole app (no error boundary wraps the Home view).
  await loginAs(page);
  // heroFixtures()'s default published_at (real-clock, millisecond
  // resolution) can tie between calls and flip the mock's sort order —
  // space these explicitly so slide order is deterministic regardless.
  const now = Date.now();
  const fixtures = [
    makeArticle({ title: 'Hero Story One', priority: 'high', is_read: true, published_at: new Date(now).toISOString() }),
    makeArticle({ title: 'Hero Story Two', priority: 'high', is_read: true, published_at: new Date(now - 3600_000).toISOString() }),
    makeArticle({ title: 'Hero Story Three', priority: 'high', is_read: true, published_at: new Date(now - 7200_000).toISOString() }),
  ];
  const state = await mockApi(page, { articles: fixtures });
  await page.clock.install();
  await page.goto('/');

  await expect(page.getByText('Hero Story One')).toBeVisible();

  // Jump to the last slide.
  await page.getByRole('button', { name: '3. haber' }).click();
  await expect(page.getByText('Hero Story Three')).toBeVisible();

  // The next poll returns only one high-priority article — index 2 is now
  // out of range.
  state.articles = fixtures.filter((a) => a.priority === 'high').slice(0, 1);
  await page.clock.runFor(61000);

  // Must not crash: the hero recovers and shows the sole remaining article.
  await expect(page.getByText('Hero Story One')).toBeVisible();
});
