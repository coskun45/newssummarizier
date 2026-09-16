import { test, expect } from '@playwright/test';
import { loginAs } from './helpers/auth';
import { mockApi, makeArticle, makeBulletinCategory } from './helpers/mockApi';

async function openBulletinTab(page: import('@playwright/test').Page) {
  await page.getByRole('button', { name: 'Bülten' }).click();
  return page.locator('.bulletin-panel');
}

test('Bülten tab activates and shows the report config form', async ({ page }) => {
  await loginAs(page);
  await mockApi(page, { articles: [] });
  await page.goto('/');

  const panel = await openBulletinTab(page);

  await expect(panel).toBeVisible();
  await expect(panel.getByText('Zaman Aralığı')).toBeVisible();
  await expect(panel.getByRole('heading', { name: 'Önem Seviyesi' })).toBeVisible();
  await expect(panel.getByLabel('Yüksek')).toBeVisible();
  await expect(panel.getByLabel('Orta')).toBeVisible();
  await expect(panel.getByLabel('Düşük')).toBeVisible();
  await expect(panel.getByLabel('Favoriler')).toBeVisible();
  await expect(panel.getByText('Üst Düzey Kategoriler')).toBeVisible();
  await expect(panel.getByPlaceholder('Yeni kategori (ör. Avrupa)')).toBeVisible();
  await expect(panel.getByRole('button', { name: 'Oluştur ve İndir' })).toBeVisible();

  // No article browser chrome (sidebar filters, search) while on this tab.
  await expect(page.locator('.dashboard-sidebar')).not.toBeVisible();
});

test('generate is disabled until at least one category exists', async ({ page }) => {
  await loginAs(page);
  await mockApi(page, { articles: [] });
  await page.goto('/');

  const panel = await openBulletinTab(page);
  await expect(panel.getByRole('button', { name: 'Oluştur ve İndir' })).toBeDisabled();
});

test('adding a category sends POST and shows it in the list', async ({ page }) => {
  await loginAs(page);
  await mockApi(page, { articles: [] });
  await page.goto('/');

  const panel = await openBulletinTab(page);
  await panel.getByPlaceholder('Yeni kategori (ör. Avrupa)').fill('Avrupa');

  const req = page.waitForRequest(
    (r) => r.url().endsWith('/api/bulletin/categories') && r.method() === 'POST'
  );
  await panel.getByRole('button', { name: 'Ekle' }).click();
  await req;

  await expect(panel.locator('.bulletin-category-name')).toHaveText('Avrupa');
  await expect(panel.getByRole('button', { name: 'Oluştur ve İndir' })).toBeEnabled();
});

test('deleting a category shows a confirm dialog and sends DELETE on accept', async ({ page }) => {
  await loginAs(page);
  const category = makeBulletinCategory({ name: 'Amerika' });
  await mockApi(page, { articles: [], bulletinCategories: [category] });
  await page.goto('/');

  const panel = await openBulletinTab(page);
  page.once('dialog', (dialog) => dialog.accept());
  const req = page.waitForRequest(
    (r) => /\/api\/bulletin\/categories\/\d+$/.test(new URL(r.url()).pathname) && r.method() === 'DELETE'
  );
  await panel.locator('.bulletin-category-item').filter({ hasText: 'Amerika' }).getByLabel('Sil').click();
  await req;

  await expect(panel.locator('.bulletin-category-item')).toHaveCount(0);
});

test('clicking "Oluştur ve İndir" requests the report and downloads it', async ({ page }) => {
  await loginAs(page);
  const category = makeBulletinCategory({ name: 'Avrupa' });
  await mockApi(page, { articles: [], bulletinCategories: [category] });
  await page.goto('/');

  const panel = await openBulletinTab(page);

  const req = page.waitForRequest(
    (r) => r.url().endsWith('/api/bulletin/generate') && r.method() === 'POST'
  );
  const downloadPromise = page.waitForEvent('download');
  await panel.getByRole('button', { name: 'Oluştur ve İndir' }).click();
  await req;
  const download = await downloadPromise;

  expect(download.suggestedFilename()).toMatch(/^bulten-\d{4}-\d{2}-\d{2}\.docx$/);
  await expect(panel.getByText('Bülten oluşturuldu ve indirildi.')).toBeVisible();
});

test('live preview count reflects priority and favorites selections', async ({ page }) => {
  await loginAs(page);
  const articles = [
    makeArticle({ title: 'A', priority: 'high', is_starred: false }),
    makeArticle({ title: 'B', priority: 'low', is_starred: true }),
    makeArticle({ title: 'C', priority: 'med', is_starred: false }),
    // Matches both the priority filter and favorites once selections overlap —
    // must still be counted once, not twice.
    makeArticle({ title: 'D', priority: 'high', is_starred: true }),
  ];
  await mockApi(page, { articles });
  await page.goto('/');

  const panel = await openBulletinTab(page);

  await expect(panel.getByText('Bu seçimlerle 4 haber özeti bültende yer alacak.')).toBeVisible();

  await panel.getByLabel('Yüksek').check();
  await expect(panel.getByText('Bu seçimlerle 2 haber özeti bültende yer alacak.')).toBeVisible();

  await panel.getByLabel('Favoriler').check();
  await expect(panel.getByText('Bu seçimlerle 3 haber özeti bültende yer alacak.')).toBeVisible();
});

test('include_favorites is sent to /generate when Favoriler is checked', async ({ page }) => {
  await loginAs(page);
  const category = makeBulletinCategory({ name: 'Avrupa' });
  await mockApi(page, { articles: [], bulletinCategories: [category] });
  await page.goto('/');

  const panel = await openBulletinTab(page);
  await panel.getByLabel('Favoriler').check();

  const req = page.waitForRequest(
    (r) => r.url().endsWith('/api/bulletin/generate') && r.method() === 'POST'
  );
  const downloadPromise = page.waitForEvent('download');
  await panel.getByRole('button', { name: 'Oluştur ve İndir' }).click();
  const request = await req;
  await downloadPromise;

  expect(request.postDataJSON()).toMatchObject({ include_favorites: true });
});
