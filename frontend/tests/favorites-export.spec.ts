import { test, expect, type Page } from '@playwright/test';
import { readFile } from 'node:fs/promises';
import { loginAs } from './helpers/auth';
import { mockApi, makeArticle, makeSummary } from './helpers/mockApi';

const STARRED_A = makeArticle({ title: 'Starred Alpha', is_starred: true, priority: 'high', author: 'Jane Doe' });
const STARRED_B = makeArticle({ title: 'Starred Beta', is_starred: true });
const NOT_STARRED = makeArticle({ title: 'Plain Gamma', is_starred: false });

function summaries() {
  return new Map([
    [STARRED_A.id, [makeSummary(STARRED_A.id, { summary_type: 'brief', summary_text: 'Alpha brief summary.' })]],
    [STARRED_B.id, [makeSummary(STARRED_B.id, { summary_type: 'standard', summary_text: 'Beta standard summary.' })]],
  ]);
}

async function openFavorites(page: Page) {
  await page.goto('/');
  await page.getByRole('button', { name: 'Haberler', exact: true }).click();
  await page.getByRole('button', { name: 'Favori', exact: true }).click();
  await expect(page.locator('.article-list').getByText('Starred Alpha')).toBeVisible();
}

function articleCard(page: Page, title: string) {
  return page.locator('.article-card').filter({ hasText: title });
}

test('Favori lists only starred articles; export buttons need a selection', async ({ page }) => {
  await loginAs(page);
  await mockApi(page, { articles: [STARRED_A, STARRED_B, NOT_STARRED], summaries: summaries() });
  await openFavorites(page);

  await expect(page.locator('.article-list').getByText('Starred Beta')).toBeVisible();
  await expect(page.locator('.article-list').getByText('Plain Gamma')).not.toBeVisible();
  await expect(page.getByRole('button', { name: 'Word indir' })).toBeDisabled();
  await expect(page.getByRole('button', { name: 'WhatsApp' })).toBeDisabled();
});

test('Tümünü Seç selects every favorite and Seçimi Temizle clears it', async ({ page }) => {
  await loginAs(page);
  await mockApi(page, { articles: [STARRED_A, STARRED_B], summaries: summaries() });
  await openFavorites(page);

  await page.getByRole('button', { name: 'Tümünü Seç' }).click();
  await expect(page.getByRole('checkbox', { name: 'Seç' })).toHaveCount(2);
  for (const box of await page.getByRole('checkbox', { name: 'Seç' }).all()) await expect(box).toBeChecked();
  await expect(page.getByRole('button', { name: 'Word indir' })).toBeEnabled();

  await page.getByRole('button', { name: 'Seçimi Temizle (2)' }).click();
  await expect(page.getByRole('button', { name: /Seçimi Temizle/ })).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Word indir' })).toBeDisabled();
});

test('Word indir downloads only the selected favorites with their summaries', async ({ page }) => {
  await loginAs(page);
  await mockApi(page, { articles: [STARRED_A, STARRED_B], summaries: summaries() });
  await openFavorites(page);

  await articleCard(page, 'Starred Alpha').getByRole('checkbox', { name: 'Seç' }).check();

  const downloadPromise = page.waitForEvent('download');
  await page.getByRole('button', { name: 'Word indir' }).click();
  const download = await downloadPromise;

  expect(download.suggestedFilename()).toMatch(/^favori-haberler-\d{4}-\d{2}-\d{2}\.doc$/);
  const html = await readFile((await download.path())!, 'utf-8');
  expect(html).toContain('Starred Alpha');
  expect(html).toContain('Alpha brief summary.');
  expect(html).toContain('Jane Doe');
  expect(html).toContain('1 makale');
  expect(html).not.toContain('Starred Beta');

  await expect(page.getByText('1 makale Word olarak indirildi.')).toBeVisible();
});

test('WhatsApp copies a formatted message of the selected favorites to the clipboard', async ({ page, context }) => {
  await context.grantPermissions(['clipboard-read', 'clipboard-write']);
  await loginAs(page);
  await mockApi(page, { articles: [STARRED_A, STARRED_B], summaries: summaries() });
  await openFavorites(page);

  await page.getByRole('button', { name: 'Tümünü Seç' }).click();
  await page.getByRole('button', { name: 'WhatsApp' }).click();

  await expect(page.getByText("2 makale panoya kopyalandı — WhatsApp'a yapıştırabilirsiniz.")).toBeVisible();
  const clip = await page.evaluate(() => navigator.clipboard.readText());
  expect(clip).toContain('*📰 Favori Haberler');
  expect(clip).toContain('Starred Alpha');
  expect(clip).toContain('Öncelik: Yüksek');
  expect(clip).toContain('Alpha brief summary.');
  expect(clip).toContain('Starred Beta');
  expect(clip).toContain('Beta standard summary.');
  expect(clip).toContain(STARRED_A.url);
});

test('Listeyi Temizle asks for confirmation; dismissing sends nothing', async ({ page }) => {
  await loginAs(page);
  await mockApi(page, { articles: [STARRED_A, STARRED_B] });
  await openFavorites(page);

  let unstarCalled = false;
  page.on('request', (r) => {
    if (r.url().includes('/api/articles/unstar-all')) unstarCalled = true;
  });
  let message = '';
  page.once('dialog', (dialog) => {
    message = dialog.message();
    void dialog.dismiss();
  });
  await page.getByRole('button', { name: 'Listeyi Temizle' }).click();

  expect(message).toBe('Tüm favorileri kaldırmak istediğinizden emin misiniz?');
  await expect(page.locator('.article-list').getByText('Starred Alpha')).toBeVisible();
  expect(unstarCalled).toBe(false);
});

test('confirming Listeyi Temizle unstars everything and empties the Favori tab', async ({ page }) => {
  await loginAs(page);
  await mockApi(page, { articles: [STARRED_A, STARRED_B] });
  await openFavorites(page);
  await expect(page.getByRole('button', { name: 'Favori', exact: true })).toHaveText(/Favori\s*2/);

  page.once('dialog', (dialog) => void dialog.accept());
  const req = page.waitForRequest((r) => r.url().includes('/api/articles/unstar-all') && r.method() === 'POST');
  await page.getByRole('button', { name: 'Listeyi Temizle' }).click();
  await req;

  await expect(page.getByText('Makale bulunamadı')).toBeVisible();
  await expect(page.getByRole('button', { name: 'Favori', exact: true })).toHaveText(/^\s*Favori\s*$/);
});
