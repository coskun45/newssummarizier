import { test, expect } from '@playwright/test';
import { loginAs } from './helpers/auth';
import { mockApi, makeArticle } from './helpers/mockApi';

// Blocked / paywalled sources: the card says whether a free source has the same story (and links
// to it) or the content could not be read at all.
test('a blocked article links to the same story in a free source', async ({ page }) => {
  await loginAs(page);
  await mockApi(page, {
    articles: [makeArticle({
      title: 'Palestinians flock back to northern Gaza',
      source: 'WSJ',
      content_access: 'free_match',
      free_match: { id: 99, title: "Filistinliler Gazze'nin kuzeyine dönüyor", url: 'https://dw.example/gazze', source: 'DW Türkçe' },
    })],
  });
  await page.goto('/');
  await page.getByRole('button', { name: 'Haberler', exact: true }).click();

  await expect(page.getByText('Ücretsiz kaynakta var')).toBeVisible();
  const link = page.getByRole('link', { name: /DW Türkçe: Filistinliler Gazze'nin kuzeyine dönüyor/ });
  await expect(link).toHaveAttribute('href', 'https://dw.example/gazze');
  await expect(link).toHaveAttribute('target', '_blank');
  await expect(page.getByText('İçerik alınamadı')).toHaveCount(0);
});

test('a blocked article without a free source is marked as unavailable', async ({ page }) => {
  await loginAs(page);
  await mockApi(page, {
    articles: [makeArticle({ title: 'Iran is running out of time', source: 'Haaretz', content_access: 'unavailable' })],
  });
  await page.goto('/');
  await page.getByRole('button', { name: 'Haberler', exact: true }).click();

  await expect(page.getByText('İçerik alınamadı')).toBeVisible();
  await expect(page.getByText('Ücretsiz kaynakta var')).toHaveCount(0);
});

// Regression (review): a free_match whose matched article is gone must not promise a link.
test('a free match without a linked article is shown as unavailable', async ({ page }) => {
  await loginAs(page);
  await mockApi(page, {
    articles: [makeArticle({ title: 'Orphaned match', source: 'WSJ', content_access: 'free_match', free_match: null })],
  });
  await page.goto('/');
  await page.getByRole('button', { name: 'Haberler', exact: true }).click();

  await expect(page.getByText('İçerik alınamadı')).toBeVisible();
  await expect(page.getByText('Ücretsiz kaynakta var')).toHaveCount(0);
});

test('a fully read article shows no access badge', async ({ page }) => {
  await loginAs(page);
  await mockApi(page, { articles: [makeArticle({ title: 'Normal haber' })] });
  await page.goto('/');
  await page.getByRole('button', { name: 'Haberler', exact: true }).click();

  await expect(page.getByText('Normal haber')).toBeVisible();
  await expect(page.getByText('Ücretsiz kaynakta var')).toHaveCount(0);
  await expect(page.getByText('İçerik alınamadı')).toHaveCount(0);
});
