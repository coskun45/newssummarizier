import { test, expect } from '@playwright/test';
import { loginAs } from './helpers/auth';
import { mockApi, makeArticle } from './helpers/mockApi';

// The card shows the feed name as "Kaynak" above the (person) author.
test('the card shows Kaynak above Yazar', async ({ page }) => {
  await loginAs(page);
  await mockApi(page, {
    articles: [makeArticle({ title: 'Guterres uyardı', source: 'Anadolu Ajansı', author: 'Burak Bir' })],
  });
  await page.goto('/');
  await page.getByRole('button', { name: 'Haberler', exact: true }).click();

  const source = page.getByText('Kaynak: Anadolu Ajansı');
  const author = page.getByText('Yazar: Burak Bir');
  await expect(source).toBeVisible();
  await expect(author).toBeVisible();
  const [sourceBox, authorBox] = [await source.boundingBox(), await author.boundingBox()];
  expect(sourceBox!.y).toBeLessThan(authorBox!.y);
});

test('without a person author only Kaynak is shown', async ({ page }) => {
  await loginAs(page);
  await mockApi(page, {
    articles: [makeArticle({ title: 'Sputnik haberi', source: 'Sputnik Türkiye', author: null })],
  });
  await page.goto('/');
  await page.getByRole('button', { name: 'Haberler', exact: true }).click();

  await expect(page.getByText('Kaynak: Sputnik Türkiye')).toBeVisible();
  await expect(page.getByText(/^Yazar:/)).toHaveCount(0);
});
