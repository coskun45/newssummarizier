import { test, expect } from '@playwright/test';
import { ADMIN_USER, loginAs } from './helpers/auth';
import { mockApi, makeArticle } from './helpers/mockApi';

function fixtures() {
  return [
    makeArticle({ title: 'Unimportant 1', is_read: false, importance: 'unimportant' }),
    makeArticle({ title: 'Unimportant 2', is_read: false, importance: 'unimportant' }),
  ];
}

function unimportantRow(page: import('@playwright/test').Page) {
  return page.locator('.category-bulk-row').filter({ hasText: 'Önemsiz' });
}

test('archive all unimportant fires immediately', async ({ page }) => {
  await loginAs(page);
  await mockApi(page, { articles: fixtures() });
  await page.goto('/');
  await page.getByRole('button', { name: 'Haberler', exact: true }).click();

  const req = page.waitForRequest((r) => r.url().includes('/articles/unimportant/archive-all'));
  await unimportantRow(page).getByRole('button', { name: /Tümünü Arşive Gönder/ }).click();
  await req;

  await expect(page.locator('.category-bulk-confirm-overlay')).not.toBeVisible();
});

test('delete all unimportant requires confirmation, cancel sends nothing', async ({ page }) => {
  await loginAs(page, ADMIN_USER);
  await mockApi(page, { articles: fixtures() });
  let deleteAllCalled = false;
  await page.route(
    (url) => url.pathname === '/api/articles/unimportant/delete-all',
    (route) => {
      deleteAllCalled = true;
      route.fulfill({ json: { deleted_count: 2 } });
    }
  );
  await page.goto('/');
  await page.getByRole('button', { name: 'Haberler', exact: true }).click();

  await unimportantRow(page).getByRole('button', { name: /Tümünü Sil/ }).click();
  await expect(
    page.getByText('Tüm okunmamış önemsiz haberleri (2 adet) silmek istediğinize emin misiniz?')
  ).toBeVisible();

  await page.getByRole('button', { name: 'Vazgeç' }).click();

  await expect(page.locator('.category-bulk-confirm-overlay')).not.toBeVisible();
  expect(deleteAllCalled).toBe(false);
});

test('confirming sends the unimportant delete-all request', async ({ page }) => {
  await loginAs(page, ADMIN_USER);
  await mockApi(page, { articles: fixtures() });
  await page.goto('/');
  await page.getByRole('button', { name: 'Haberler', exact: true }).click();

  await unimportantRow(page).getByRole('button', { name: /Tümünü Sil/ }).click();
  const req = page.waitForRequest((r) => r.url().includes('/articles/unimportant/delete-all'));
  await page.locator('.category-bulk-confirm-box').getByRole('button', { name: 'Sil', exact: true }).click();
  await req;

  await expect(page.locator('.category-bulk-confirm-overlay')).not.toBeVisible();
});
