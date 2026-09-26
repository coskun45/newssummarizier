import { test, expect } from '@playwright/test';
import { ADMIN_USER, loginAs } from './helpers/auth';
import { mockApi, makeArticle, makeBulletinCategory, makeGeneratedBulletin } from './helpers/mockApi';

async function openBulletinTab(page: import('@playwright/test').Page) {
  await page.getByRole('button', { name: 'Bülten' }).click();
  return page.locator('.bulletin-panel');
}

function dateInputValue(daysAgo: number): string {
  const d = new Date();
  d.setDate(d.getDate() - daysAgo);
  return d.toISOString().slice(0, 10);
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
  await expect(panel.getByRole('heading', { name: 'Daha Önce Oluşturulan Bültenler' })).toBeVisible();
  await expect(panel.getByText('Henüz oluşturulmuş bülten yok.')).toBeVisible();

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
  await mockApi(page, { articles: [makeArticle()] });
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
  await mockApi(page, { articles: [makeArticle()], bulletinCategories: [category] });
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
  await expect(page.getByRole('alert')).toHaveText('Bülten oluşturuldu ve indirildi.');
});

test('generating a bulletin for a past custom range downloads a file named for that period, not today', async ({ page }) => {
  // Regression test: handleGenerate used to build the download filename from
  // the browser's current date (`new Date()`) instead of the backend's
  // Content-Disposition header, which reflects the report's actual
  // published_to — so a bulletin for a past range was misleadingly saved
  // under today's date.
  await loginAs(page);
  const category = makeBulletinCategory({ name: 'Avrupa' });
  const inRange = new Date();
  inRange.setDate(inRange.getDate() - 17);
  await mockApi(page, { articles: [makeArticle({ published_at: inRange.toISOString() })], bulletinCategories: [category] });
  await page.goto('/');

  const panel = await openBulletinTab(page);
  const section = panel.locator('.date-filter-section').filter({ hasText: 'Yayın Tarihi' });
  await section.getByLabel('Özel Tarih').click();

  const fromValue = dateInputValue(20);
  const toValue = dateInputValue(15);
  const dateInputs = section.locator('input[type="date"]');
  await dateInputs.nth(0).fill(fromValue);
  await dateInputs.nth(1).fill(toValue);

  const downloadPromise = page.waitForEvent('download');
  await panel.getByRole('button', { name: 'Oluştur ve İndir' }).click();
  const download = await downloadPromise;

  // Mirrors Bulletin.tsx's own resolveDateRange('custom') construction, so
  // the expected filename is correct regardless of the test runner's timezone.
  const expectedDate = new Date(`${toValue}T23:59:59`).toISOString().slice(0, 10);
  const todayDate = new Date().toISOString().slice(0, 10);
  expect(expectedDate).not.toBe(todayDate);
  expect(download.suggestedFilename()).toBe(`bulten-${expectedDate}.docx`);
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
  await mockApi(page, { articles: [makeArticle({ is_starred: true })], bulletinCategories: [category] });
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

test('previously generated bulletins are listed with their metadata', async ({ page }) => {
  await loginAs(page);
  const generatedBulletins = [
    makeGeneratedBulletin({
      filename: 'bulten-2026-09-16.docx',
      priorities: ['high'],
      include_favorites: true,
      article_count: 7,
      generated_at: '2026-09-16T10:00:00Z',
    }),
  ];
  await mockApi(page, { articles: [], generatedBulletins });
  await page.goto('/');

  const panel = await openBulletinTab(page);

  const item = panel.locator('.generated-bulletin-item');
  await expect(item).toHaveCount(1);
  await expect(item.getByText(/Yüksek/)).toBeVisible();
  await expect(item.getByText(/Favoriler/)).toBeVisible();
  await expect(item.getByText(/7 haber özeti/)).toBeVisible();
});

test('downloading a previously generated bulletin requests and downloads its file', async ({ page }) => {
  await loginAs(page);
  const generatedBulletins = [makeGeneratedBulletin({ filename: 'eski-bulten.docx' })];
  await mockApi(page, { articles: [], generatedBulletins });
  await page.goto('/');

  const panel = await openBulletinTab(page);

  const req = page.waitForRequest(
    (r) => /\/api\/bulletin\/generated\/\d+\/download$/.test(new URL(r.url()).pathname) && r.method() === 'GET'
  );
  const downloadPromise = page.waitForEvent('download');
  await panel.locator('.generated-bulletin-item').getByLabel('İndir').click();
  await req;
  const download = await downloadPromise;

  expect(download.suggestedFilename()).toBe('eski-bulten.docx');
  await expect(page.getByRole('alert')).toHaveText('Bülten indirildi.');
});

test('deleting a previously generated bulletin shows a confirm dialog and removes it on accept', async ({ page }) => {
  await loginAs(page, ADMIN_USER);
  const generatedBulletins = [makeGeneratedBulletin({ filename: 'eski-bulten.docx' })];
  await mockApi(page, { articles: [], generatedBulletins });
  await page.goto('/');

  const panel = await openBulletinTab(page);
  page.once('dialog', (dialog) => dialog.accept());
  const req = page.waitForRequest(
    (r) => /\/api\/bulletin\/generated\/\d+$/.test(new URL(r.url()).pathname) && r.method() === 'DELETE'
  );
  await panel.locator('.generated-bulletin-item').getByLabel('Sil').click();
  await req;

  await expect(panel.locator('.generated-bulletin-item')).toHaveCount(0);
  await expect(panel.getByText('Henüz oluşturulmuş bülten yok.')).toBeVisible();
  await expect(page.getByRole('alert')).toHaveText('Bülten silindi.');
});

test('generating a bulletin adds it to the previously generated list', async ({ page }) => {
  await loginAs(page);
  const category = makeBulletinCategory({ name: 'Avrupa' });
  await mockApi(page, { articles: [makeArticle()], bulletinCategories: [category] });
  await page.goto('/');

  const panel = await openBulletinTab(page);
  await expect(panel.getByText('Henüz oluşturulmuş bülten yok.')).toBeVisible();

  const downloadPromise = page.waitForEvent('download');
  await panel.getByRole('button', { name: 'Oluştur ve İndir' }).click();
  await downloadPromise;

  await expect(panel.locator('.generated-bulletin-item')).toHaveCount(1);
});

test('generate is disabled while the selection matches no articles', async ({ page }) => {
  // Regression: the button stayed enabled at "0 haber özeti" and the backend then
  // rejected the request ("Seçilen aralıkta haber bulunamadı").
  await loginAs(page);
  const category = makeBulletinCategory({ name: 'Avrupa' });
  await mockApi(page, { articles: [makeArticle({ priority: 'med' })], bulletinCategories: [category] });
  await page.goto('/');

  const panel = await openBulletinTab(page);
  const generate = panel.getByRole('button', { name: 'Oluştur ve İndir' });
  await expect(panel.getByText('Bu seçimlerle 1 haber özeti bültende yer alacak.')).toBeVisible();
  await expect(generate).toBeEnabled();

  // Only Yüksek selected -> nothing matches
  await panel.getByLabel('Yüksek').check();
  await expect(panel.getByText('Bu seçimlerle 0 haber özeti bültende yer alacak.')).toBeVisible();
  await expect(generate).toBeDisabled();
  await expect(generate).toHaveAttribute('title', 'Bu seçimlerle bültene girecek haber yok');

  await panel.getByLabel('Orta').check();
  await expect(generate).toBeEnabled();
});
