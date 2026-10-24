import { test, expect } from '@playwright/test';
import { loginAs } from './helpers/auth';
import { mockApi, makeArticle } from './helpers/mockApi';

test('opens with fetched content and closes via the close button', async ({ page }) => {
  await loginAs(page);
  await mockApi(page, {
    articles: [
      makeArticle({
        title: 'Has Content',
        is_read: false,
        cleaned_content: 'This is the cleaned article body.',
      }),
    ],
  });
  await page.goto('/');
  await page.getByRole('button', { name: 'Haberler', exact: true }).click();

  await page.getByRole('button', { name: 'Orijinal İçerik' }).click();

  await expect(page.getByText('This is the cleaned article body.')).toBeVisible();

  await page.getByRole('button', { name: 'Kapat' }).click();
  await expect(page.locator('.modal-overlay')).not.toBeVisible();
});

test('closes via backdrop click', async ({ page }) => {
  await loginAs(page);
  await mockApi(page, {
    articles: [
      makeArticle({ title: 'Has Content', is_read: false, cleaned_content: 'Body text here.' }),
    ],
  });
  await page.goto('/');
  await page.getByRole('button', { name: 'Haberler', exact: true }).click();

  await page.getByRole('button', { name: 'Orijinal İçerik' }).click();
  await expect(page.locator('.modal-overlay')).toBeVisible();

  await page.locator('.modal-overlay').click({ position: { x: 5, y: 5 } });

  await expect(page.locator('.modal-overlay')).not.toBeVisible();
});

test('shows "İçerik mevcut değil" when content is null', async ({ page }) => {
  await loginAs(page);
  await mockApi(page, {
    articles: [
      makeArticle({ title: 'No Content', is_read: false, cleaned_content: null, raw_content: null }),
    ],
  });
  await page.goto('/');
  await page.getByRole('button', { name: 'Haberler', exact: true }).click();

  await page.getByRole('button', { name: 'Orijinal İçerik' }).click();

  await expect(page.getByText('İçerik mevcut değil')).toBeVisible();
});

test('Escape key does NOT close the modal', async ({ page }) => {
  await loginAs(page);
  await mockApi(page, {
    articles: [
      makeArticle({ title: 'Has Content', is_read: false, cleaned_content: 'Body text here.' }),
    ],
  });
  await page.goto('/');
  await page.getByRole('button', { name: 'Haberler', exact: true }).click();

  await page.getByRole('button', { name: 'Orijinal İçerik' }).click();
  await expect(page.locator('.modal-overlay')).toBeVisible();

  await page.keyboard.press('Escape');

  await expect(page.locator('.modal-overlay')).toBeVisible();
});

test('shows the fetched page, not the RSS teaser, for an article the pipeline never scraped', async ({ page }) => {
  await loginAs(page);
  await mockApi(page, {
    articles: [
      makeArticle({
        title: 'Unscraped',
        is_read: false,
        cleaned_content: null,
        raw_content: 'Short RSS teaser.',
        pageContent: 'The full article body from the page.',
      }),
    ],
  });
  await page.goto('/');
  await page.getByRole('button', { name: 'Haberler', exact: true }).click();

  await page.getByRole('button', { name: 'Orijinal İçerik' }).click();

  await expect(page.getByText('The full article body from the page.')).toBeVisible();
  await expect(page.getByText('Short RSS teaser.')).not.toBeVisible();
});
