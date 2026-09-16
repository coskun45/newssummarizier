import { test, expect } from '@playwright/test';
import { loginAs } from './helpers/auth';
import { mockApi, makeArticle } from './helpers/mockApi';

test('typing narrows the list after debounce', async ({ page }) => {
  await loginAs(page);
  await mockApi(page, {
    articles: [
      makeArticle({ title: 'Quantum Computing News', is_read: false }),
      makeArticle({ title: 'Regular News', is_read: false }),
    ],
  });
  await page.goto('/');
  await page.getByRole('button', { name: 'Haberler', exact: true }).click();
  await expect(page.getByText('Quantum Computing News')).toBeVisible();
  await expect(page.getByText('Regular News')).toBeVisible();

  const searchReq = page.waitForRequest((req) => req.url().includes('search=Quantum'));
  await page.getByPlaceholder('Makalelerde ara...').fill('Quantum');
  await searchReq;

  await expect(page.getByText('Quantum Computing News')).toBeVisible();
  await expect(page.getByText('Regular News')).not.toBeVisible();
});

test('clear button resets the search and list', async ({ page }) => {
  await loginAs(page);
  await mockApi(page, {
    articles: [
      makeArticle({ title: 'Quantum Computing News', is_read: false }),
      makeArticle({ title: 'Regular News', is_read: false }),
    ],
  });
  await page.goto('/');
  await page.getByRole('button', { name: 'Haberler', exact: true }).click();

  const searchReq = page.waitForRequest((req) => req.url().includes('search=Quantum'));
  await page.getByPlaceholder('Makalelerde ara...').fill('Quantum');
  await searchReq;
  await expect(page.getByText('Regular News')).not.toBeVisible();

  // The empty-search query was already fetched on initial load and is still
  // fresh (staleTime), so clearing serves it from cache — no new request fires.
  await page.getByRole('button', { name: 'Aramayı temizle' }).click();

  await expect(page.getByText('Regular News')).toBeVisible();
  await expect(page.getByRole('button', { name: 'Aramayı temizle' })).not.toBeVisible();
});

test('clear button is hidden when input is empty', async ({ page }) => {
  await loginAs(page);
  await mockApi(page, { articles: [] });
  await page.goto('/');
  await page.getByRole('button', { name: 'Haberler', exact: true }).click();

  await expect(page.getByRole('button', { name: 'Aramayı temizle' })).not.toBeVisible();
});
