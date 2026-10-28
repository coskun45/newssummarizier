import { test, expect, type Page } from '@playwright/test';
import { ADMIN_USER, loginAs } from './helpers/auth';
import { mockApi } from './helpers/mockApi';
import { makeEmbeddingStatus, makeTools, mockChat } from './helpers/mockChat';

async function openAssistantSettings(page: Page) {
  await page.goto('/');
  await page.getByRole('button', { name: 'Ayarlar', exact: true }).click();
  await page.locator('.settings-nav').getByRole('button', { name: 'Asistan' }).click();
}

test('admins switch tools and plan approval and save only those fields', async ({ page }) => {
  await loginAs(page, ADMIN_USER);
  const api = await mockApi(page, { articles: [] });
  await mockChat(page, [], { apiState: api });
  await openAssistantSettings(page);

  const tools = page.getByRole('region', { name: 'Araçlar' });
  await expect(tools.getByText('Henüz kurulmadı — Python sandbox\'ı sonraki aşamada gelecek.')).toBeVisible();
  await expect(tools.getByRole('checkbox', { name: /Code interpreter/ })).toBeDisabled();
  await expect(page.getByRole('button', { name: 'Kaydet' })).toBeDisabled();

  await tools.getByRole('checkbox', { name: /Grafik/ }).uncheck();
  await page.getByRole('checkbox', { name: 'Analiz planını çalıştırmadan önce onay iste' }).check();

  const request = page.waitForRequest((r) => r.url().endsWith('/api/settings/') && r.method() === 'PUT');
  await page.getByRole('button', { name: 'Kaydet' }).click();
  expect((await request).postDataJSON()).toEqual({
    chat_enabled_tools: 'time,sql,semantic_search',
    chat_require_plan_approval: true,
  });
  await expect(page.getByText('Kaydedildi.')).toBeVisible();
});

test('the last usable data tool cannot be switched off', async ({ page }) => {
  await loginAs(page, ADMIN_USER);
  await mockApi(page, { articles: [] });
  await mockChat(page, [], { tools: makeTools({ semantic_search: { available: false, unavailable_reason: 'pgvector yok', enabled: false, active: false } }) });
  await openAssistantSettings(page);

  await page.getByRole('checkbox', { name: /Veritabanı/ }).uncheck();

  await expect(page.getByText('En az bir veri aracı (Veritabanı veya Vektör arama) açık kalmalı.')).toBeVisible();
  await expect(page.getByRole('button', { name: 'Kaydet' })).toBeDisabled();
});

test('vector search status shows coverage and admins vectorize the missing articles', async ({ page }) => {
  await loginAs(page, ADMIN_USER);
  await mockApi(page, { articles: [] });
  const chat = await mockChat(page, [], { embedding: makeEmbeddingStatus({ summarized: 44, embedded: 40, chunks: 200 }) });
  await openAssistantSettings(page);

  const vectors = page.getByRole('region', { name: 'Vektör arama' });
  await expect(vectors).toContainText('40 / 44 özetli haber vektörleştirildi');
  await vectors.getByRole('button', { name: 'Eksik 4 haberi vektörleştir' }).click();

  await expect(vectors).toContainText('44 / 44');
  await expect(vectors).toContainText('Son toplu işlem: 4 haber vektörleştirildi');
  await expect(vectors.getByRole('button', { name: 'Tüm haberler vektörleştirildi' })).toBeDisabled();
  expect(chat.backfillStarted).toBe(1);
});

test('regular users see the settings read-only', async ({ page }) => {
  await loginAs(page);
  await mockApi(page, { articles: [] });
  await mockChat(page, []);
  await openAssistantSettings(page);

  await expect(page.getByText('Bu ayarları yalnızca yöneticiler değiştirebilir.')).toBeVisible();
  await expect(page.getByRole('checkbox', { name: /Veritabanı/ })).toBeDisabled();
  await expect(page.getByRole('button', { name: 'Kaydet' })).toHaveCount(0);
  await expect(page.getByRole('button', { name: /vektörleştir/ })).toHaveCount(0);
});

test('articles without any text are not counted as missing, and an empty run says so', async ({ page }) => {
  // Server case: 2.095 articles from paywalled / robots.txt-blocked sources have no scraped page;
  // most carry their story in the RSS text (now embedded), a few have no text at all.
  await loginAs(page, ADMIN_USER);
  await mockApi(page, { articles: [] });
  const chat = await mockChat(page, [], {
    embedding: makeEmbeddingStatus({ summarized: 3871, embedded: 3864, no_text: 7, chunks: 20000 }),
  });
  await openAssistantSettings(page);

  const vectors = page.getByRole('region', { name: 'Vektör arama' });
  await expect(vectors).toContainText('3864 / 3864 özetli haber vektörleştirildi');
  await expect(vectors).toContainText('7 haberin hiç metni yok');
  await expect(vectors.getByRole('button', { name: 'Tüm haberler vektörleştirildi' })).toBeDisabled();

  // A finished run that found nothing to do must say so instead of looking like nothing happened.
  chat.embedding = { ...chat.embedding, job: { status: 'done', total: 0, done: 0, failed: 0, cost: 0, error: null } };
  await page.reload();
  await openAssistantSettings(page);
  await expect(vectors).toContainText('vektörleştirilecek yeni haber yoktu');
});
