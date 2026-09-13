import { test, expect } from '@playwright/test';
import { loginAs } from './helpers/auth';
import { mockApi, makeArticle, makeSummary } from './helpers/mockApi';

test('expanding shows the summary text and collapses back', async ({ page }) => {
  await loginAs(page);
  const article = makeArticle({ title: 'Summarized Article', is_read: false, has_summaries: true });
  const summaries = new Map([[article.id, [makeSummary(article.id, { summary_type: 'brief', summary_text: 'A short brief summary.' })]]]);
  await mockApi(page, { articles: [article], summaries });
  await page.goto('/');

  await page.getByRole('button', { name: 'Özeti göster' }).click();
  await expect(page.getByText('A short brief summary.')).toBeVisible();

  await page.getByRole('button', { name: 'Daha az göster' }).click();
  await expect(page.getByText('A short brief summary.')).not.toBeVisible();
});

test('switching between summary types shows the matching text', async ({ page }) => {
  await loginAs(page);
  const article = makeArticle({ title: 'Multi Summary Article', is_read: false, has_summaries: true });
  const summaries = new Map([
    [
      article.id,
      [
        makeSummary(article.id, { summary_type: 'brief', summary_text: 'Brief text here.' }),
        makeSummary(article.id, { summary_type: 'standard', summary_text: 'Standard text here.' }),
      ],
    ],
  ]);
  await mockApi(page, { articles: [article], summaries });
  await page.goto('/');

  await page.getByRole('button', { name: 'Özeti göster' }).click();
  await expect(page.getByText('Standard text here.')).toBeVisible();

  await page.getByRole('button', { name: 'Kısa' }).click();
  await expect(page.getByText('Brief text here.')).toBeVisible();
  await expect(page.getByText('Standard text here.')).not.toBeVisible();
});

test('shows "Özet mevcut değil" when no summary of the selected type exists', async ({ page }) => {
  await loginAs(page);
  const article = makeArticle({ title: 'No Summary Yet', is_read: false, has_summaries: true });
  await mockApi(page, { articles: [article], summaries: new Map([[article.id, []]]) });
  await page.goto('/');

  await page.getByRole('button', { name: 'Özeti göster' }).click();

  await expect(page.getByText('Özet mevcut değil')).toBeVisible();
});

test('copy button copies the summary and shows "Kopyalandı"', async ({ page, context }) => {
  await context.grantPermissions(['clipboard-read', 'clipboard-write']);
  await loginAs(page);
  const article = makeArticle({ title: 'Copyable Article', is_read: false, has_summaries: true });
  const summaries = new Map([[article.id, [makeSummary(article.id, { summary_type: 'brief', summary_text: 'Copy this text.' })]]]);
  await mockApi(page, { articles: [article], summaries });
  await page.goto('/');

  await page.getByRole('button', { name: 'Özeti göster' }).click();
  await expect(page.getByText('Copy this text.')).toBeVisible();

  await page.getByRole('button', { name: 'Özeti kopyala' }).click();

  await expect(page.getByRole('button', { name: 'Kopyalandı' })).toBeVisible();
});
