import { test, expect } from '@playwright/test';
import { loginAs, DEFAULT_USER } from './helpers/auth';
import { mockApi, makeArticle } from './helpers/mockApi';

test('renders article list after login', async ({ page }) => {
  await loginAs(page);
  await mockApi(page, {
    articles: [
      makeArticle({ title: 'First Unread Article', is_read: false }),
      makeArticle({ title: 'Second Unread Article', is_read: false }),
    ],
  });

  await page.goto('/');

  await expect(page.getByRole('heading', { name: 'Haber Özetleyici' })).toBeVisible();
  await expect(page.getByText('First Unread Article')).toBeVisible();
  await expect(page.getByText('Second Unread Article')).toBeVisible();
  await expect(page.getByText('2 makale bulundu')).toBeVisible();
});

test('shows empty state when no articles', async ({ page }) => {
  await loginAs(page);
  await mockApi(page, { articles: [] });

  await page.goto('/');

  await expect(page.getByText('📭 Makale bulunamadı')).toBeVisible();
});

test('shows error state when articles request fails', async ({ page }) => {
  await loginAs(page);
  await mockApi(page, { articles: [] });
  await page.route(
    (url) => url.pathname === '/api/articles/',
    (route) => route.fulfill({ status: 500, json: { detail: 'Internal Server Error' } })
  );

  await page.goto('/');

  await expect(page.getByText('⚠️ Makaleler yüklenirken hata oluştu')).toBeVisible();
});

test('shows loading state before response resolves', async ({ page }) => {
  await loginAs(page);
  await mockApi(page, {
    articles: [makeArticle({ title: 'Slow Article', is_read: false })],
  });
  await page.route(
    (url) => url.pathname === '/api/articles/',
    async (route) => {
      await new Promise((r) => setTimeout(r, 600));
      await route.fallback();
    }
  );

  await page.goto('/');

  await expect(page.getByText('⏳ Makaleler yükleniyor...')).toBeVisible();
  await expect(page.getByText('Slow Article')).toBeVisible({ timeout: 5000 });
});

test('switches between unread/archive/important tabs and refetches with different filters', async ({ page }) => {
  await loginAs(page);
  await mockApi(page, {
    articles: [
      makeArticle({ title: 'Unread Piece', is_read: false, is_starred: false }),
      makeArticle({ title: 'Archived Piece', is_read: true, is_starred: false }),
      makeArticle({ title: 'Starred Piece', is_read: false, is_starred: true }),
    ],
  });

  await page.goto('/');

  await expect(page.getByText('Unread Piece')).toBeVisible();
  await expect(page.getByText('Starred Piece')).toBeVisible();
  await expect(page.getByText('Archived Piece')).not.toBeVisible();

  const archiveReq = page.waitForRequest((req) => {
    const u = new URL(req.url());
    return u.pathname === '/api/articles/' && u.searchParams.get('is_read') === 'true';
  });
  // Scoped to the emoji: "Arşiv" is also a substring of the bulk-action
  // buttons' "Arşive Gönder" text.
  await page.getByRole('button', { name: /🗄️/ }).click();
  await archiveReq;
  await expect(page.getByText('Archived Piece')).toBeVisible();
  await expect(page.getByText('Unread Piece')).not.toBeVisible();

  // "Favori" is also a substring of each ArticleCard's "Favorilere ekle" button.
  await page.getByRole('button', { name: /⭐/ }).click();
  await expect(page.getByText('Starred Piece')).toBeVisible();
  await expect(page.getByText('Archived Piece')).not.toBeVisible();
});

test('section tab badge counts reflect articleCounts', async ({ page }) => {
  await loginAs(page);
  await mockApi(page, {
    articles: [
      makeArticle({ title: 'A', is_read: false, is_starred: false }),
      makeArticle({ title: 'B', is_read: true, is_starred: false }),
      makeArticle({ title: 'C', is_read: false, is_starred: true }),
    ],
  });

  await page.goto('/');

  await expect(page.getByRole('button', { name: /📥/ })).toContainText('2');
  await expect(page.getByRole('button', { name: /🗄️/ })).toContainText('1');
  await expect(page.getByRole('button', { name: /⭐/ })).toContainText('1');
});

test('header shows app version and logged-in user email', async ({ page }) => {
  await loginAs(page);
  await mockApi(page, { articles: [] });

  await page.goto('/');

  await expect(page.getByText('v1.0.0')).toBeVisible();
  await expect(page.getByText(DEFAULT_USER.email)).toBeVisible();
});
