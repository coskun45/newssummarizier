import { test, expect } from '@playwright/test';
import { loginAs } from './helpers/auth';
import { mockApi, makeArticle, makeSummary } from './helpers/mockApi';

// Explicit, spaced published_at: the mock API sorts by it, and makeArticle's default
// (real-clock, ms resolution) can tie between calls and flip the slide order under
// parallel load, making "first slide" nondeterministic.
function heroFixtures() {
  const now = Date.now();
  const at = (hoursAgo: number) => new Date(now - hoursAgo * 3600_000).toISOString();
  return [
    makeArticle({ title: 'Hero Story One', priority: 'high', is_read: true, published_at: at(0), cleaned_content: 'Full body of story one.' }),
    makeArticle({ title: 'Hero Story Two', priority: 'high', is_read: true, published_at: at(1), cleaned_content: 'Full body of story two.' }),
    makeArticle({ title: 'Hero Story Three', priority: 'high', is_read: true, published_at: at(2) }),
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

test('falls back to the standard summary when the brief type is disabled in Settings', async ({ page }) => {
  // Regression test: the hero only looked for a 'brief' summary, so with brief
  // turned off in Ayarlar every slide said "Özet mevcut değil" even though the
  // article had summaries.
  await loginAs(page);
  const story = makeArticle({ title: 'Hero Story One', priority: 'high', is_read: true, has_summaries: true });
  await mockApi(page, {
    articles: [story],
    settings: { enabled_summary_types: 'standard,detailed' },
    summaries: new Map([
      [story.id, [
        makeSummary(story.id, { summary_type: 'detailed', summary_text: 'Detaylı, birden fazla cümleden oluşan uzun özet. İkinci cümle.' }),
        makeSummary(story.id, { summary_type: 'standard', summary_text: 'Standart Türkçe özet.' }),
      ]],
    ]),
  });
  await page.clock.install();
  await page.goto('/');

  await expect(page.getByText('Standart Türkçe özet.')).toBeVisible();
  await expect(page.getByText('Özet mevcut değil')).toHaveCount(0);
});

test('shows the shortest summary text when the article has several summary types', async ({ page }) => {
  // The hero card has room for one short blurb: pick by actual text length, not
  // by type — a "brief" can come back longer than the "standard" one.
  await loginAs(page);
  const story = makeArticle({ title: 'Hero Story One', priority: 'high', is_read: true, has_summaries: true });
  await mockApi(page, {
    articles: [story],
    summaries: new Map([
      [story.id, [
        makeSummary(story.id, { summary_type: 'brief', summary_text: 'Kısa diye üretilmiş ama beklenenden epey uzun çıkan bir özet metni.' }),
        makeSummary(story.id, { summary_type: 'standard', summary_text: 'En kısa özet.' }),
        makeSummary(story.id, { summary_type: 'detailed', summary_text: 'Detaylı ve uzun, birden fazla cümleden oluşan bir özet. İkinci cümle.' }),
      ]],
    ]),
  });
  await page.clock.install();
  await page.goto('/');

  await expect(page.getByText('En kısa özet.')).toBeVisible();
  await expect(page.getByText(/beklenenden epey uzun/)).toHaveCount(0);
});

test('shows the summary once it is generated after the slide was first rendered', async ({ page }) => {
  // Regression test: the pipeline sets priority=high before it writes the
  // summaries, so the hero can fetch an empty summary list for a fresh story.
  // useSummaries cached that [] forever (staleTime: Infinity, never invalidated),
  // leaving "Özet mevcut değil" until a full page reload.
  await loginAs(page);
  const story = makeArticle({ title: 'Hero Story One', priority: 'high', is_read: true, has_summaries: false });
  const state = await mockApi(page, { articles: [story] });
  await page.clock.install();
  await page.goto('/');

  await expect(page.getByText('Özet mevcut değil')).toBeVisible();

  // The pipeline finishes summarizing the article.
  state.summaries.set(story.id, [makeSummary(story.id, { summary_type: 'brief', summary_text: 'Sonradan gelen özet.' })]);
  // mockApi clones the fixtures — flip the flag on its copy, which the next
  // 60s article poll will return.
  state.articles.find((a) => a.id === story.id)!.has_summaries = true;
  await page.clock.runFor(61000);

  await expect(page.getByText('Sonradan gelen özet.')).toBeVisible();
});

test('does not keep re-fetching summaries for an article that has none', async ({ page }) => {
  // Regression test: an empty summary list was re-polled every 30s forever, even
  // for articles whose summaries will never be generated.
  await loginAs(page);
  const story = makeArticle({ title: 'Hero Story One', priority: 'high', is_read: true, has_summaries: false });
  await mockApi(page, { articles: [story] });
  let summaryRequests = 0;
  page.on('request', (req) => {
    if (/\/api\/articles\/\d+\/summaries/.test(req.url())) summaryRequests++;
  });
  await page.clock.install();
  await page.goto('/');

  await expect(page.getByText('Özet mevcut değil')).toBeVisible();
  const afterLoad = summaryRequests;

  await page.clock.runFor(5 * 60_000);
  await expect(page.getByText('Özet mevcut değil')).toBeVisible();
  expect(summaryRequests).toBe(afterLoad);
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

for (const scheme of ['light', 'dark'] as const) {
  test(`every carousel pager button label is readable in the ${scheme} theme`, async ({ page }) => {
    // Regression: the pager used a fixed white label on backgrounds that turn light in the dark
    // theme (numbered items on --color-primary-active, "T" on --color-text-primary), so the
    // labels were white on light blue / near-white.
    await page.emulateMedia({ colorScheme: scheme });
    await loginAs(page);
    await mockApi(page, { articles: heroFixtures() });
    await page.goto('/');

    // "1" is the active (highlighted) slide, "2" a regular one, "T" the view-all button
    for (const name of ['1. haber', '2. haber', 'Tüm haberler']) {
      const button = page.getByRole('button', { name, exact: true });
      await expect(button).toBeVisible();
      const ratio = await button.evaluate((el) => {
        const parse = (c: string) => (c.match(/[\d.]+/g) ?? []).slice(0, 3).map(Number);
        const lum = (rgb: number[]) => {
          const [r, g, b] = rgb.map((v) => {
            const s = v / 255;
            return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
          });
          return 0.2126 * r + 0.7152 * g + 0.0722 * b;
        };
        const style = getComputedStyle(el);
        const [l1, l2] = [lum(parse(style.color)), lum(parse(style.backgroundColor))].sort((a, b) => b - a);
        return (l1 + 0.05) / (l2 + 0.05);
      });
      // WCAG AA for normal text
      expect(ratio, `${name} contrast`).toBeGreaterThanOrEqual(4.5);
    }
  });
}
