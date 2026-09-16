import { test, expect } from '@playwright/test';
import { loginAs } from './helpers/auth';
import { mockApi, makePrompt } from './helpers/mockApi';

async function openClassificationEditor(page: import('@playwright/test').Page) {
  await page.getByRole('button', { name: 'Ayarlar' }).click();
  await page.getByRole('button', { name: 'Sistem Promptları' }).click();
  return page.locator('.prompt-editor').filter({ hasText: 'Sınıflandırma Promptu' });
}

test('shows the loaded prompt text and active/inactive badge', async ({ page }) => {
  await loginAs(page);
  const prompts = new Map([['classification', makePrompt('classification', { prompt_text: 'Test prompt text', is_active: true })]]);
  await mockApi(page, { articles: [], prompts });
  await page.goto('/');

  const editor = await openClassificationEditor(page);

  await expect(editor.locator('.prompt-text')).toHaveText('Test prompt text');
  await expect(editor.getByText('Aktif')).toBeVisible();
});

test('edit reveals the textarea, Aktif checkbox and char counter', async ({ page }) => {
  await loginAs(page);
  const prompts = new Map([['classification', makePrompt('classification', { prompt_text: 'Test prompt text', is_active: true })]]);
  await mockApi(page, { articles: [], prompts });
  await page.goto('/');

  const editor = await openClassificationEditor(page);
  await editor.getByRole('button', { name: 'Düzenle' }).click();

  await expect(editor.locator('textarea')).toHaveValue('Test prompt text');
  await expect(editor.getByRole('checkbox', { name: 'Aktif' })).toBeChecked();
  await expect(editor.getByText('16 karakter')).toBeVisible();
});

test('cancel reverts changes without sending a request', async ({ page }) => {
  await loginAs(page);
  const prompts = new Map([['classification', makePrompt('classification', { prompt_text: 'Original text', is_active: true })]]);
  await mockApi(page, { articles: [], prompts });
  let writeCalled = false;
  await page.route(
    (url) => /\/api\/prompts\//.test(url.pathname),
    (route) => {
      if (route.request().method() !== 'GET') writeCalled = true;
      route.fallback();
    }
  );
  await page.goto('/');

  const editor = await openClassificationEditor(page);
  await editor.getByRole('button', { name: 'Düzenle' }).click();
  await editor.locator('textarea').fill('Changed but not saved');
  await editor.getByRole('button', { name: 'İptal' }).click();

  await expect(editor.locator('.prompt-text')).toHaveText('Original text');
  expect(writeCalled).toBe(false);
});

test('saving an existing prompt sends PUT and shows the success message, which clears after ~3s', async ({ page }) => {
  await loginAs(page);
  const prompts = new Map([['classification', makePrompt('classification', { prompt_text: 'Original text', is_active: true })]]);
  await mockApi(page, { articles: [], prompts });
  await page.goto('/');

  const editor = await openClassificationEditor(page);
  await editor.getByRole('button', { name: 'Düzenle' }).click();
  await editor.locator('textarea').fill('Updated text');

  const req = page.waitForRequest(
    (r) => r.url().endsWith('/api/prompts/classification') && r.method() === 'PUT'
  );
  await editor.getByRole('button', { name: 'Kaydet' }).click();
  await req;

  await expect(editor.getByText('Prompt başarıyla kaydedildi!')).toBeVisible();
  await expect(editor.getByText('Prompt başarıyla kaydedildi!')).not.toBeVisible({ timeout: 5000 });
});

test("when the prompt doesn't exist yet (404), no error is shown and saving uses POST instead of PUT", async ({ page }) => {
  await loginAs(page);
  await mockApi(page, { articles: [], prompts: new Map() });
  await page.goto('/');

  const editor = await openClassificationEditor(page);

  await expect(editor.locator('.error-message')).toHaveCount(0);
  await expect(editor.getByText('Prompt belirlenmemiş')).toBeVisible();

  await editor.getByRole('button', { name: 'Düzenle' }).click();
  await editor.locator('textarea').fill('Brand new prompt text');

  const req = page.waitForRequest((r) => r.url().endsWith('/api/prompts/') && r.method() === 'POST');
  await editor.getByRole('button', { name: 'Kaydet' }).click();
  await req;

  await expect(editor.getByText('Prompt başarıyla kaydedildi!')).toBeVisible();
});

test('save is disabled when the textarea is emptied', async ({ page }) => {
  await loginAs(page);
  const prompts = new Map([['classification', makePrompt('classification', { prompt_text: 'Original text', is_active: true })]]);
  await mockApi(page, { articles: [], prompts });
  await page.goto('/');

  const editor = await openClassificationEditor(page);
  await editor.getByRole('button', { name: 'Düzenle' }).click();
  await editor.locator('textarea').fill('');

  await expect(editor.getByRole('button', { name: 'Kaydet' })).toBeDisabled();
});
