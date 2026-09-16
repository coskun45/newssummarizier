import { test, expect } from '@playwright/test';
import { loginAs } from './helpers/auth';
import { mockApi, makeArticle } from './helpers/mockApi';

function fixtures() {
  return [
    makeArticle({ title: 'High 1', is_read: false, priority: 'high' }),
    makeArticle({ title: 'High 2', is_read: false, priority: 'high' }),
    makeArticle({ title: 'High 3', is_read: false, priority: 'high' }),
  ];
}

function highRow(page: import('@playwright/test').Page) {
  return page.locator('.category-bulk-row').filter({ hasText: 'Yüksek' });
}

test('archive all by priority fires immediately without confirmation', async ({ page }) => {
  await loginAs(page);
  await mockApi(page, { articles: fixtures() });
  await page.goto('/');
  await page.getByRole('button', { name: 'Haberler', exact: true }).click();

  const req = page.waitForRequest((r) => r.url().includes('/articles/priority/high/archive-all'));
  await highRow(page).getByRole('button', { name: /Tümünü Arşive Gönder/ }).click();
  await req;

  await expect(page.locator('.category-bulk-confirm-overlay')).not.toBeVisible();
});

test('delete all by priority opens a confirm modal with the correct count', async ({ page }) => {
  await loginAs(page);
  await mockApi(page, { articles: fixtures() });
  await page.goto('/');
  await page.getByRole('button', { name: 'Haberler', exact: true }).click();

  await highRow(page).getByRole('button', { name: /Tümünü Sil/ }).click();

  await expect(
    page.getByText('"Yüksek" önceliğindeki tüm okunmamış haberleri (3 adet) silmek istediğinize emin misiniz?')
  ).toBeVisible();
});

test('"Vazgeç" cancels without sending a request', async ({ page }) => {
  await loginAs(page);
  await mockApi(page, { articles: fixtures() });
  let deleteAllCalled = false;
  await page.route(
    (url) => url.pathname === '/api/articles/priority/high/delete-all',
    (route) => {
      deleteAllCalled = true;
      route.fulfill({ json: { deleted_count: 3 } });
    }
  );
  await page.goto('/');
  await page.getByRole('button', { name: 'Haberler', exact: true }).click();

  await highRow(page).getByRole('button', { name: /Tümünü Sil/ }).click();
  await page.getByRole('button', { name: 'Vazgeç' }).click();

  await expect(page.locator('.category-bulk-confirm-overlay')).not.toBeVisible();
  expect(deleteAllCalled).toBe(false);
});

test('confirming "Sil" sends the delete-all request and closes the modal', async ({ page }) => {
  await loginAs(page);
  await mockApi(page, { articles: fixtures() });
  await page.goto('/');
  await page.getByRole('button', { name: 'Haberler', exact: true }).click();

  await highRow(page).getByRole('button', { name: /Tümünü Sil/ }).click();
  const req = page.waitForRequest((r) => r.url().includes('/articles/priority/high/delete-all'));
  // Scoped to the confirm box: ArticleCard's delete buttons also expose an
  // accessible name of "Sil" via their title attribute, which would otherwise collide.
  await page.locator('.category-bulk-confirm-box').getByRole('button', { name: 'Sil', exact: true }).click();
  await req;

  await expect(page.locator('.category-bulk-confirm-overlay')).not.toBeVisible();
});
