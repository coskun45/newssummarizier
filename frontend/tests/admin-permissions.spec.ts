import { test, expect, type Page } from '@playwright/test';
import { ADMIN_USER, loginAs } from './helpers/auth';
import { mockApi, makeArticle, makeGeneratedBulletin } from './helpers/mockApi';

// #32: bulk delete, re-processing, the Playground, deleting shared bulletins and changing the
// global settings are admin-only on the backend (403 for others) — regular users don't see them.

const errorArticle = makeArticle({ title: 'Etiketsiz Haber', importance: null, priority: null, status: 'failed' });
const highArticle = makeArticle({ title: 'Önemli Haber', priority: 'high', importance: 'important' });

async function openNews(page: Page) {
  await page.goto('/');
  await page.getByRole('button', { name: 'Haberler', exact: true }).click();
}

test('regular user: no Playground tab, admin sees it', async ({ page, browser }) => {
  await loginAs(page);
  await mockApi(page, { articles: [] });
  await page.goto('/');
  await expect(page.getByRole('button', { name: 'Analiz', exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Playground', exact: true })).toHaveCount(0);

  const adminPage = await browser.newPage();
  await loginAs(adminPage, ADMIN_USER);
  await mockApi(adminPage, { articles: [] });
  await adminPage.goto('/');
  await expect(adminPage.getByRole('button', { name: 'Playground', exact: true })).toBeVisible();
  await adminPage.close();
});

test('regular user: bulk delete buttons are hidden, bulk archive stays', async ({ page }) => {
  await loginAs(page);
  await mockApi(page, { articles: [highArticle] });
  await openNews(page);

  const highRow = page.locator('.category-bulk-row').filter({ hasText: 'Yüksek' });
  await expect(highRow.getByRole('button', { name: /Tümünü Arşive Gönder/ })).toBeVisible();
  await expect(page.locator('.category-bulk-actions').getByRole('button', { name: /Tümünü Sil/ })).toHaveCount(0);
});

test('regular user: Error tab offers no re-processing', async ({ page }) => {
  await loginAs(page);
  await mockApi(page, { articles: [errorArticle] });
  await openNews(page);
  await page.getByRole('button', { name: 'Error' }).click();

  await expect(page.getByText('Etiketsiz Haber')).toBeVisible();
  await expect(page.getByRole('button', { name: /Tekrar Dene/i })).toHaveCount(0);
});

test('regular user: generated bulletins can be downloaded but not deleted', async ({ page }) => {
  await loginAs(page);
  await mockApi(page, { articles: [], generatedBulletins: [makeGeneratedBulletin({ filename: 'ortak.docx' })] });
  await page.goto('/');
  await page.getByRole('button', { name: 'Bülten', exact: true }).click();

  const item = page.locator('.generated-bulletin-item');
  await expect(item.getByLabel('İndir')).toBeVisible();
  await expect(item.getByLabel('Sil')).toHaveCount(0);
});

test('regular user: settings are read-only', async ({ page }) => {
  await loginAs(page);
  await mockApi(page, { articles: [] });
  await page.goto('/');
  await page.getByRole('button', { name: 'Ayarlar' }).click();
  await page.getByRole('button', { name: 'Özet Türleri' }).click();

  const content = page.locator('.settings-category');
  await expect(content.getByRole('checkbox', { name: /Kısa/ })).toBeDisabled();
  await expect(content.getByRole('button', { name: 'Ayarları kaydet' })).toHaveCount(0);
  await expect(content.getByText('Bu ayarları yalnızca yöneticiler değiştirebilir.')).toBeVisible();

  await page.getByRole('button', { name: 'RSS Beslemeleri' }).click();
  await expect(page.getByLabel('Otomatik yenileme aralığı')).toBeDisabled();
});
