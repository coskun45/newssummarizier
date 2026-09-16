import { test, expect } from '@playwright/test';
import { loginAs } from './helpers/auth';
import { mockApi, makeArticle } from './helpers/mockApi';

test('starring sends PATCH with starred:true and label flips', async ({ page }) => {
  await loginAs(page);
  await mockApi(page, {
    articles: [makeArticle({ title: 'Star Me', is_read: false, is_starred: false })],
  });
  await page.goto('/');
  await page.getByRole('button', { name: 'Haberler', exact: true }).click();

  const button = page.getByRole('button', { name: 'Favorilere ekle' });
  await expect(button).toBeVisible();

  const req = page.waitForRequest(
    (r) => r.url().includes('/star') && r.method() === 'PATCH' && r.postDataJSON()?.starred === true
  );
  await button.click();
  await req;

  await expect(page.getByRole('button', { name: 'Favorilerden çıkar' })).toBeVisible();
});

test('unstarring an already-starred article sends starred:false', async ({ page }) => {
  await loginAs(page);
  await mockApi(page, {
    articles: [makeArticle({ title: 'Unstar Me', is_read: false, is_starred: true })],
  });
  await page.goto('/');
  await page.getByRole('button', { name: 'Haberler', exact: true }).click();

  const button = page.getByRole('button', { name: 'Favorilerden çıkar' });
  await expect(button).toBeVisible();

  const req = page.waitForRequest(
    (r) => r.url().includes('/star') && r.postDataJSON()?.starred === false
  );
  await button.click();
  await req;

  await expect(page.getByRole('button', { name: 'Favorilere ekle' })).toBeVisible();
});

test('star button is disabled while the mutation is pending', async ({ page }) => {
  await loginAs(page);
  await mockApi(page, {
    articles: [makeArticle({ title: 'Slow Star', is_read: false, is_starred: false })],
  });
  await page.route(
    (url) => /\/api\/articles\/\d+\/star$/.test(url.pathname),
    async (route) => {
      await new Promise((r) => setTimeout(r, 500));
      await route.fallback();
    }
  );
  await page.goto('/');
  await page.getByRole('button', { name: 'Haberler', exact: true }).click();

  const button = page.getByRole('button', { name: 'Favorilere ekle' });
  await button.click();

  await expect(button).toBeDisabled();
  await expect(page.getByRole('button', { name: 'Favorilerden çıkar' })).toBeEnabled({ timeout: 5000 });
});
