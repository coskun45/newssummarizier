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

test('waits for a slow page fetch instead of giving up at the default request timeout', async ({ page }) => {
  // The backend scrapes the page synchronously (robots.txt, delay, retries) — easily over 20s.
  test.setTimeout(60_000);
  await loginAs(page);
  await mockApi(page, {
    articles: [makeArticle({ id: 4242, title: 'Slow Page', is_read: false, cleaned_content: null, raw_content: 'Teaser.' })],
  });
  await page.route('**/api/articles/4242/content', async (route) => {
    await new Promise((resolve) => setTimeout(resolve, 21_000));
    await route.fulfill({ json: makeArticle({ id: 4242, title: 'Slow Page', cleaned_content: 'Slowly fetched body.' }) });
  });
  await page.goto('/');
  await page.getByRole('button', { name: 'Haberler', exact: true }).click();

  await page.getByRole('button', { name: 'Orijinal İçerik' }).click();

  await expect(page.getByText('Slowly fetched body.')).toBeVisible({ timeout: 30_000 });
});
