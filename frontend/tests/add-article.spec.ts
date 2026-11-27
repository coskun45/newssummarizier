import { test, expect, type Page } from '@playwright/test';
import { ADMIN_USER, loginAs } from './helpers/auth';
import { mockApi, makeArticle, makeFeed } from './helpers/mockApi';

// "Haber Ekle" (admin): add your own article by form or JSON upload; it is sent to
// POST /articles/manual, which runs it through the same pipeline as feed articles.

const FEEDS = [makeFeed({ id: 1, title: 'DW - Deutsche Welle' }), makeFeed({ id: 2, title: 'BBC Türkçe' })];

async function openDialog(page: Page) {
  await page.goto('/');
  await page.getByRole('button', { name: 'Haberler', exact: true }).click();
  await page.getByRole('button', { name: 'Haber Ekle' }).click();
  return page.getByRole('dialog', { name: 'Haber Ekle' });
}

test('admin adds an article through the form and sees it as "Manuel"', async ({ page }) => {
  await loginAs(page, ADMIN_USER);
  const state = await mockApi(page, {
    feeds: FEEDS,
    articles: [makeArticle({ title: 'Mevcut haber', author: 'Ali Veli' })],
  });
  const dialog = await openDialog(page);

  // Sources come from the existing feeds as a dropdown.
  const feedSelect = dialog.getByLabel('Kaynak');
  await expect(feedSelect.locator('option')).toHaveText(['Kaynak seçin…', 'DW - Deutsche Welle', 'BBC Türkçe']);

  // Missing fields are reported before anything is sent.
  await dialog.getByRole('button', { name: 'Haberi Ekle' }).click();
  await expect(dialog.getByRole('alert')).toContainText('Kaynak (feed veya feed_id) gerekli');
  await expect(dialog.getByRole('alert')).toContainText('İçerik veya URL gerekli');
  expect(state.manualArticleRequests).toHaveLength(0);

  await feedSelect.selectOption({ label: 'BBC Türkçe' });
  await dialog.getByLabel('Başlık').fill('Kendi haberim');
  await dialog.getByLabel('İçerik').fill('Haberin tam metni.');
  await dialog.getByLabel('Yazar').fill('Ayşe Yılmaz');
  await dialog.getByRole('button', { name: 'Haberi Ekle' }).click();

  await expect(dialog.getByRole('status')).toContainText('1 haber eklendi');
  expect(state.manualArticleRequests).toEqual([[expect.objectContaining({
    title: 'Kendi haberim', feed_id: 2, content: 'Haberin tam metni.', author: 'Ayşe Yılmaz', url: null,
  })]]);

  await dialog.getByRole('button', { name: 'Kapat' }).click();
  const card = page.locator('.article-card').filter({ hasText: 'Kendi haberim' }).first();
  await expect(page.getByText('Kendi haberim')).toBeVisible();
  await expect(card.getByText('Manuel')).toBeVisible();
  // No link was given: there is no source page to open.
  await expect(card.getByRole('link', { name: /Kaynağı aç/ })).toHaveCount(0);
});

test('admin uploads articles as JSON with a per-row preview', async ({ page }) => {
  await loginAs(page, ADMIN_USER);
  const state = await mockApi(page, { feeds: FEEDS });
  const dialog = await openDialog(page);
  await dialog.getByRole('tab', { name: 'JSON Yükle' }).click();

  // The valid format is shown in the dialog.
  await dialog.getByText('Geçerli JSON formatı').click();
  await expect(dialog.locator('pre')).toContainText('"articles"');

  await dialog.getByLabel('JSON içeriği').fill('{ bozuk');
  await expect(dialog.getByRole('alert')).toHaveText('Geçersiz JSON: dosya ayrıştırılamadı.');

  const upload = {
    articles: [
      { title: 'Başlıkla kaynak', feed: 'dw - deutsche welle', content: 'Metin' },
      { title: 'Sadece link', feed_id: 2, url: 'https://example.com/haber/1' },
      { title: 'Kaynaksız', feed: 'Yok Böyle', content: 'Metin' },
    ],
  };
  await dialog.getByLabel('JSON dosyası').setInputFiles({
    name: 'haberler.json', mimeType: 'application/json', buffer: Buffer.from(JSON.stringify(upload)),
  });

  await expect(dialog.getByRole('heading', { name: 'Önizleme (3 haber)' })).toBeVisible();
  await expect(dialog.getByRole('row', { name: /Kaynaksız/ })).toContainText('Kaynak bulunamadı');
  await expect(dialog.getByText('1 hatalı kayıt gönderilmeyecek.')).toBeVisible();

  await dialog.getByRole('button', { name: '2 haberi yükle' }).click();
  await expect(dialog.getByRole('status')).toContainText('2 haber eklendi');
  expect(state.manualArticleRequests[0].map((a) => a.title)).toEqual(['Başlıkla kaynak', 'Sadece link']);
});

// Regression (review): after a partial result the JSON stayed as it was, so pressing "yükle"
// again created the content-only rows a second time (each gets a fresh manual:// URL).
test('uploading again after a partial result does not send the created rows twice', async ({ page }) => {
  await loginAs(page, ADMIN_USER);
  const state = await mockApi(page, {
    feeds: FEEDS,
    articles: [makeArticle({ url: 'https://example.com/var-olan' })],
  });
  const dialog = await openDialog(page);
  await dialog.getByRole('tab', { name: 'JSON Yükle' }).click();
  await dialog.getByLabel('JSON içeriği').fill(JSON.stringify({
    articles: [
      { title: 'Yeni A', feed_id: 2, content: 'Metin A' },
      { title: 'Var olan', feed_id: 2, url: 'https://example.com/var-olan' },
      { title: 'Yeni B', feed_id: 2, content: 'Metin B' },
    ],
  }));

  await dialog.getByRole('button', { name: '3 haberi yükle' }).click();
  await expect(dialog.getByRole('status')).toContainText('2 haber eklendi');
  await expect(dialog.getByRole('heading', { name: 'Önizleme (1 haber)' })).toBeVisible();

  await dialog.getByRole('button', { name: '1 haberi yükle' }).click();
  await expect.poll(() => state.manualArticleRequests.length).toBe(2);
  expect(state.manualArticleRequests[1].map((a) => a.title)).toEqual(['Var olan']);
  expect(state.articles.filter((a) => a.title === 'Yeni A')).toHaveLength(1);
});

// Regression (review): the preview was looser / differently cased than the backend — a row it
// called "Hazır" could fail the whole upload with 422, and "BILD" didn't match the feed "Bild".
test('the JSON preview checks rows the way the backend does', async ({ page }) => {
  await loginAs(page, ADMIN_USER);
  const state = await mockApi(page, { feeds: [makeFeed({ id: 1, title: 'Bild' }), makeFeed({ id: 2, title: 'İstanbul Haber' })] });
  const dialog = await openDialog(page);
  await dialog.getByRole('tab', { name: 'JSON Yükle' }).click();

  await dialog.getByLabel('JSON içeriği').fill(JSON.stringify([
    { title: 'Büyük harfli kaynak', feed: 'BILD', content: 'Metin' },
    { title: 'Noktalı İ', feed: 'istanbul haber', content: 'Metin', published_at: '2026-11-27 09:30' },
    { title: 'Kötü tarih', feed_id: 1, content: 'Metin', published_at: '2026/11/27' },
    { title: 'Uzun yazar', feed_id: 1, content: 'Metin', author: 'x'.repeat(201) },
  ]));

  await expect(dialog.getByRole('row', { name: /Büyük harfli kaynak/ })).toContainText('Hazır');
  await expect(dialog.getByRole('row', { name: /Noktalı İ/ })).toContainText('Hazır');
  await expect(dialog.getByRole('row', { name: /Kötü tarih/ })).toContainText('ISO 8601');
  await expect(dialog.getByRole('row', { name: /Uzun yazar/ })).toContainText('Yazar en fazla 200 karakter');

  await dialog.getByRole('button', { name: '2 haberi yükle' }).click();
  await expect(dialog.getByRole('status')).toContainText('2 haber eklendi');
  expect(state.manualArticleRequests[0].map((a) => a.title)).toEqual(['Büyük harfli kaynak', 'Noktalı İ']);
});

test('regular users do not see "Haber Ekle"', async ({ page }) => {
  await loginAs(page);
  await mockApi(page, { feeds: FEEDS, articles: [makeArticle({ title: 'Bir haber' })] });
  await page.goto('/');
  await page.getByRole('button', { name: 'Haberler', exact: true }).click();

  await expect(page.getByText('Bir haber')).toBeVisible();
  await expect(page.getByRole('button', { name: 'Haber Ekle' })).toHaveCount(0);
});

// Regression (review): an offset-less JSON date was sent as-is and stored as UTC, so 09:30
// Istanbul time showed up as 12:30. Like the form, it is read as local time.
test.describe('JSON dates without an offset', () => {
  test.use({ timezoneId: 'Europe/Istanbul' });

  test('are sent as local time, dates with an offset unchanged', async ({ page }) => {
    await loginAs(page, ADMIN_USER);
    const state = await mockApi(page, { feeds: FEEDS });
    const dialog = await openDialog(page);
    await dialog.getByRole('tab', { name: 'JSON Yükle' }).click();
    await dialog.getByLabel('JSON içeriği').fill(JSON.stringify([
      { title: 'Yerel saat', feed_id: 2, content: 'Metin', published_at: '2026-11-27T09:30:00' },
      { title: 'Sadece gün', feed_id: 2, content: 'Metin', published_at: '2026-11-27' },
      { title: 'Ofsetli', feed_id: 2, content: 'Metin', published_at: '2026-11-27T09:30:00+01:00' },
    ]));

    await dialog.getByRole('button', { name: '3 haberi yükle' }).click();
    await expect.poll(() => state.manualArticleRequests.length).toBe(1);
    expect(state.manualArticleRequests[0].map((a) => a.published_at)).toEqual([
      '2026-11-27T06:30:00.000Z', '2026-11-26T21:00:00.000Z', '2026-11-27T09:30:00+01:00',
    ]);
  });
});
