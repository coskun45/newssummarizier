import { test, expect, type Page } from '@playwright/test';
import { loginAs } from './helpers/auth';
import { mockApi, makeArticle, makeFeed } from './helpers/mockApi';

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
  await expect(page.getByLabel("Sınıflandırma sistem prompt'u")).toHaveValue('CLS prompt {topic_list}');
  await expect(page.getByLabel("Özetleme sistem prompt'u")).toHaveValue('SUM prompt');
  await expect(page.locator('.dashboard-sidebar')).not.toBeVisible();
  await expect(page.getByRole('button', { name: 'Okunmamışlar' })).not.toBeVisible();
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
  await prompt.fill('MY EDITED PROMPT {topic_list}');
  await expect(page.getByText('değiştirildi')).toBeVisible();
  await page.getByRole('button', { name: 'Sınıflandır', exact: true }).click();

  await expect(page.getByRole('region', { name: 'Sınıflandırma sonucu' }).getByText('değiştirilmiş')).toBeVisible();
  expect(state.playgroundRuns[0].stages).toEqual(['classification']);
  expect(state.playgroundRuns[0].classification_prompt).toBe('MY EDITED PROMPT {topic_list}');
  expect(state.playgroundRuns[0].summarization_prompt).toBeUndefined();
  expect(persisted).toEqual([]);

  // Reset restores the live prompt and stops sending the override.
  await page.getByRole('button', { name: 'Sıfırla' }).click();
  await expect(prompt).toHaveValue('CLS prompt {topic_list}');
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
