import { test, expect } from '@playwright/test';
import { loginAs } from './helpers/auth';
import { mockApi, makeArticle } from './helpers/mockApi';

test('deleting removes the article from the list and DELETE is sent', async ({ page }) => {
  await loginAs(page);
  await mockApi(page, {
    articles: [
      makeArticle({ title: 'Delete Me', is_read: false }),
      makeArticle({ title: 'Keep Me', is_read: false }),
    ],
  });
  await page.goto('/');
  await page.getByRole('button', { name: 'Haberler', exact: true }).click();

  const card = page.locator('.article-card').filter({ hasText: 'Delete Me' });
  const req = page.waitForRequest((r) => r.method() === 'DELETE' && /\/api\/articles\/\d+$/.test(new URL(r.url()).pathname));
  await card.getByTitle('Sil').click();
  await req;

  await expect(page.getByText('Delete Me')).not.toBeVisible();
  await expect(page.getByText('Keep Me')).toBeVisible();
});

test('article counts refetch after delete', async ({ page }) => {
  await loginAs(page);
  await mockApi(page, {
    articles: [
      makeArticle({ title: 'Delete Me', is_read: false }),
      makeArticle({ title: 'Keep Me', is_read: false }),
    ],
  });
  await page.goto('/');
  await page.getByRole('button', { name: 'Haberler', exact: true }).click();

  await expect(page.getByRole('button', { name: /Okunmamışlar/ })).toContainText('2');

  await page.locator('.article-card').filter({ hasText: 'Delete Me' }).getByTitle('Sil').click();

  await expect(page.getByRole('button', { name: /Okunmamışlar/ })).toContainText('1');
});
