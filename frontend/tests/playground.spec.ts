import { test, expect, type Page } from '@playwright/test';
import { loginAs } from './helpers/auth';
import { mockApi, makeArticle, makeFeed, makePlaygroundSettings } from './helpers/mockApi';

const NATO = makeArticle({ id: 1, title: 'NATO erweitert Präsenz', feedId: 1, cleaned_content: 'Langer NATO Text' });
const OTHER = makeArticle({ id: 2, title: 'Wetter in Berlin', feedId: 2, cleaned_content: 'Regen' });
const FEEDS = [makeFeed({ id: 1, title: 'DW Deutsch' }), makeFeed({ id: 2, title: 'Tagesschau' })];

async function openPlayground(page: Page) {
  await loginAs(page);
  const state = await mockApi(page, { articles: [NATO, OTHER], feeds: FEEDS });
  await page.goto('/');
  await page.getByRole('button', { name: 'Playground', exact: true }).click();
  return state;
}

async function selectArticle(page: Page, title: string) {
  await page.getByRole('button', { name: title }).click();
  await expect(page.getByRole('link', { name: title })).toBeVisible();
}

test('Playground tab shows the current pipeline settings and hides the news sidebar', async ({ page }) => {
  await openPlayground(page);

  await expect(page.getByRole('heading', { name: 'Mevcut pipeline ayarları' })).toBeVisible();
  await expect(page.getByText('gpt-4o-mini', { exact: true }).first()).toBeVisible();
  await expect(page.getByLabel("Sınıflandırma sistem prompt'u")).toHaveValue('CLS prompt');
  await expect(page.getByLabel("Özetleme sistem prompt'u")).toHaveValue('SUM prompt');
  await expect(page.locator('.dashboard-sidebar')).not.toBeVisible();
  await expect(page.getByRole('button', { name: 'Okunmamışlar' })).not.toBeVisible();
});

test('the classification prompt shows the locked system part read-only and never sends it', async ({ page }) => {
  const state = await openPlayground(page);
  await selectArticle(page, 'NATO erweitert Präsenz');

  const locked = page.getByRole('region', { name: 'Kilitli sistem bölümü — sınıflandırma' });
  await expect(locked).toBeVisible();
  await expect(locked).toContainText('- NATO: Bündnis');
  await expect(locked).toContainText('JSON');
  // Only the editable criteria live in a textarea; the locked part cannot be typed into.
  await expect(locked.locator('textarea, input')).toHaveCount(0);
  await expect(page.getByLabel("Sınıflandırma sistem prompt'u")).not.toHaveValue(/NATO|JSON/);

  await page.getByLabel("Sınıflandırma sistem prompt'u").fill('Sadece kriterlerim');
  await page.getByRole('button', { name: 'Sınıflandır', exact: true }).click();
  await expect.poll(() => state.playgroundRuns.length).toBe(1);
  expect(state.playgroundRuns[0].classification_prompt).toBe('Sadece kriterlerim');
});

test('articles can be filtered by RSS feed, and run buttons need a selection', async ({ page }) => {
  await openPlayground(page);

  await expect(page.getByRole('button', { name: 'NATO erweitert Präsenz' })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Wetter in Berlin' })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Tümünü çalıştır' })).toBeDisabled();

  await page.getByLabel('RSS kaynağı').selectOption({ label: 'Tagesschau' });
  await expect(page.getByRole('button', { name: 'NATO erweitert Präsenz' })).not.toBeVisible();
  await expect(page.getByRole('button', { name: 'Wetter in Berlin' })).toBeVisible();

  await selectArticle(page, 'Wetter in Berlin');
  await expect(page.getByRole('button', { name: 'Tümünü çalıştır' })).toBeEnabled();
});

test('running the pipeline shows classification and per-type summary details without overrides', async ({ page }) => {
  const state = await openPlayground(page);
  await selectArticle(page, 'NATO erweitert Präsenz');

  await page.getByRole('button', { name: 'Tümünü çalıştır' }).click();

  const classification = page.getByRole('region', { name: 'Sınıflandırma sonucu' });
  await expect(classification.getByText('Önem: important')).toBeVisible();
  await expect(classification.getByText('Öncelik: high')).toBeVisible();
  await expect(classification.getByText('Pipeline devam eder')).toBeVisible();
  await expect(classification.getByText('Ghost (0.6) — sistemde yok, pipeline atlar')).toBeVisible();
  await expect(classification.getByText('NATO (0.9)')).toBeVisible();

  // Stage detail: the raw prompt/response is inspectable.
  await classification.getByText('Deneme 1').click();
  await expect(classification.getByText('USER PROMPT SENT')).toBeVisible();
  await expect(classification.getByText('RAW MODEL ANSWER')).toBeVisible();

  const summaries = page.getByRole('region', { name: 'Özet sonuçları' });
  await expect(summaries.getByText('Özet (brief) für NATO erweitert Präsenz')).toBeVisible();
  await expect(summaries.getByText("Model'in döndürdüğü yazar: Burak Bir")).toBeVisible();
  await summaries.getByRole('tab', { name: 'standard' }).click();
  await expect(summaries.getByText('Özet (standard) für NATO erweitert Präsenz')).toBeVisible();

  // Untouched prompts are not sent, so the server keeps using the live settings; only the
  // pipeline-enabled summary types (brief, standard) are requested.
  expect(state.playgroundRuns).toHaveLength(1);
  const sent = state.playgroundRuns[0];
  expect(sent.article_id).toBe(1);
  expect(sent.stages).toEqual(['classification', 'summarization']);
  expect(sent.classification_prompt).toBeUndefined();
  expect(sent.summarization_prompt).toBeUndefined();
  expect(sent.summary_types).toEqual(['brief', 'standard']);
});

test('an edited prompt is sent as an override for that run only and never saved', async ({ page }) => {
  const state = await openPlayground(page);
  const persisted: string[] = [];
  page.on('request', (r) => {
    if (r.url().includes('/api/prompts') && r.method() !== 'GET') persisted.push(`${r.method()} ${r.url()}`);
  });
  await selectArticle(page, 'NATO erweitert Präsenz');

  const prompt = page.getByLabel("Sınıflandırma sistem prompt'u");
  await prompt.fill('MY EDITED PROMPT');
  await expect(page.getByText('değiştirildi')).toBeVisible();
  await page.getByRole('button', { name: 'Sınıflandır', exact: true }).click();

  await expect(page.getByRole('region', { name: 'Sınıflandırma sonucu' }).getByText('değiştirilmiş')).toBeVisible();
  expect(state.playgroundRuns[0].stages).toEqual(['classification']);
  expect(state.playgroundRuns[0].classification_prompt).toBe('MY EDITED PROMPT');
  expect(state.playgroundRuns[0].summarization_prompt).toBeUndefined();
  expect(persisted).toEqual([]);

  // Reset restores the live prompt and stops sending the override.
  await page.getByRole('button', { name: 'Sıfırla', exact: true }).click();
  await expect(prompt).toHaveValue('CLS prompt');
  await page.getByRole('button', { name: 'Sınıflandır', exact: true }).click();
  await expect.poll(() => state.playgroundRuns.length).toBe(2);
  expect(state.playgroundRuns[1].classification_prompt).toBeUndefined();
});

test('summary type selection and per-type instruction edits are sent; stage results are kept between runs', async ({ page }) => {
  const state = await openPlayground(page);
  await selectArticle(page, 'NATO erweitert Präsenz');

  await page.getByRole('button', { name: 'Sınıflandır', exact: true }).click();
  await expect(page.getByRole('region', { name: 'Sınıflandırma sonucu' })).toBeVisible();

  await page.getByRole('checkbox', { name: /^standard/ }).uncheck();
  await page.getByRole('checkbox', { name: /^detailed/ }).check();
  await page.getByLabel('detailed talimatı').fill('Nur zwei Sätze.');
  await page.getByRole('button', { name: 'Özetle', exact: true }).click();

  await expect(page.getByRole('region', { name: 'Özet sonuçları' })).toBeVisible();
  // The earlier classification result is still on screen after a summarization-only run.
  await expect(page.getByRole('region', { name: 'Sınıflandırma sonucu' })).toBeVisible();

  const sent = state.playgroundRuns[1];
  expect(sent.stages).toEqual(['summarization']);
  expect(sent.summary_types).toEqual(['brief', 'detailed']);
  expect(sent.summary_instructions).toEqual({ detailed: 'Nur zwei Sätze.' });
});

test('summarization buttons are disabled when no summary type is selected', async ({ page }) => {
  await openPlayground(page);
  await selectArticle(page, 'NATO erweitert Präsenz');

  await page.getByRole('checkbox', { name: /^brief/ }).uncheck();
  await page.getByRole('checkbox', { name: /^standard/ }).uncheck();

  await expect(page.getByRole('button', { name: 'Özetle', exact: true })).toBeDisabled();
  await expect(page.getByRole('button', { name: 'Tümünü çalıştır' })).toBeDisabled();
  await expect(page.getByRole('button', { name: 'Sınıflandır', exact: true })).toBeEnabled();
});

test('a blank prompt or instruction is not sent as an override and the UI says the live one is used', async ({ page }) => {
  const state = await openPlayground(page);
  await selectArticle(page, 'NATO erweitert Präsenz');

  await page.getByLabel("Sınıflandırma sistem prompt'u").fill('');
  await page.getByLabel('brief talimatı').fill('   ');
  await expect(page.getByText('boş — canlı prompt kullanılır')).toBeVisible();
  await page.getByRole('button', { name: 'Tümünü çalıştır' }).click();

  await expect(page.getByRole('region', { name: 'Sınıflandırma sonucu' })).toBeVisible();
  expect(state.playgroundRuns[0].classification_prompt).toBeUndefined();
  expect(state.playgroundRuns[0].summary_instructions).toBeUndefined();
});

test('the summarization prompt shows the selected summary types read-only and follows the selection', async ({ page }) => {
  await openPlayground(page);
  const locked = page.getByRole('region', { name: 'Kilitli sistem bölümü — özetleme' });

  // Mock pipeline: brief + standard are enabled, detailed is off.
  await expect(locked).toContainText('brief: Provide a very brief');
  await expect(locked).toContainText('standard: Provide a concise');
  await expect(locked).not.toContainText('detailed:');
  await expect(locked).toContainText('DİL: Write the summary in Turkish.');
  await expect(locked.locator('textarea, input')).toHaveCount(0);

  await page.getByRole('checkbox', { name: /^detailed/ }).check();
  await expect(locked).toContainText('detailed: Provide a detailed');
  await page.getByRole('checkbox', { name: /^brief/ }).uncheck();
  await expect(locked).not.toContainText('brief:');

  // A per-run instruction edit shows up in the block; a blank one falls back to the default.
  await page.getByLabel('detailed talimatı').fill('Nur zwei Sätze.');
  await expect(locked).toContainText('detailed: Nur zwei Sätze.');
  await page.getByLabel('detailed talimatı').fill('   ');
  await expect(locked).toContainText('detailed: Provide a detailed');

  await page.getByRole('checkbox', { name: /^standard/ }).uncheck();
  await page.getByRole('checkbox', { name: /^detailed/ }).uncheck();
  await expect(locked).toContainText('(özet türü seçilmedi)');
  await expect(locked).toContainText('DİL: Write the summary in Turkish.');
});

test('"Sistem ayarlarına döndür" restores prompts, instructions and summary types', async ({ page }) => {
  const state = await openPlayground(page);
  await selectArticle(page, 'NATO erweitert Präsenz');
  const reset = page.getByRole('button', { name: 'Sistem ayarlarına döndür' });
  const classification = page.getByLabel("Sınıflandırma sistem prompt'u");
  const summarization = page.getByLabel("Özetleme sistem prompt'u");
  const locked = page.getByRole('region', { name: 'Kilitli sistem bölümü — özetleme' });

  await expect(reset).toBeDisabled(); // nothing edited yet

  await classification.fill('MY CLS');
  await summarization.fill('MY SUM');
  await page.getByRole('checkbox', { name: /^detailed/ }).check();
  await page.getByRole('checkbox', { name: /^brief/ }).uncheck();
  await page.getByLabel('standard talimatı').fill('Nur ein Satz.');
  await expect(reset).toBeEnabled();

  await reset.click();

  await expect(classification).toHaveValue('CLS prompt');
  await expect(summarization).toHaveValue('SUM prompt');
  await expect(page.getByRole('checkbox', { name: /^brief/ })).toBeChecked();
  await expect(page.getByRole('checkbox', { name: /^standard/ })).toBeChecked();
  await expect(page.getByRole('checkbox', { name: /^detailed/ })).not.toBeChecked();
  await expect(page.getByLabel('standard talimatı')).toHaveValue('Provide a concise summary in one paragraph.');
  await expect(locked).toContainText('brief: Provide a very brief');
  await expect(locked).not.toContainText('detailed:');
  await expect(page.getByRole('button', { name: 'Sıfırla', exact: true })).toHaveCount(0);
  await expect(reset).toBeDisabled();

  // The next run uses the live settings: no overrides, only the system's summary types.
  await page.getByRole('button', { name: 'Tümünü çalıştır' }).click();
  await expect.poll(() => state.playgroundRuns.length).toBe(1);
  const sent = state.playgroundRuns[0];
  expect(sent.classification_prompt).toBeUndefined();
  expect(sent.summarization_prompt).toBeUndefined();
  expect(sent.summary_instructions).toBeUndefined();
  expect(sent.summary_types).toEqual(['brief', 'standard']);
});

test('"Sistem ayarlarına döndür" re-reads the current system settings', async ({ page }) => {
  const state = await openPlayground(page);
  const classification = page.getByLabel("Sınıflandırma sistem prompt'u");
  const reset = page.getByRole('button', { name: 'Sistem ayarlarına döndür' });

  await classification.fill('MY CLS');
  // The system prompt was changed in Ayarlar after the Playground was opened.
  state.playgroundSettings = makePlaygroundSettings({
    classification_prompt: { text: 'NEW LIVE CLS', source: 'db' },
  });
  const refetched = page.waitForRequest((r) => r.url().endsWith('/api/playground/settings') && r.method() === 'GET');
  await reset.click();
  await refetched;

  await expect(classification).toHaveValue('NEW LIVE CLS');
  await expect(reset).toBeDisabled();
});
