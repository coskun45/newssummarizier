import { test, expect } from '@playwright/test';
import { ADMIN_USER, loginAs } from './helpers/auth';
import { mockApi, makePrompt, makeTopic } from './helpers/mockApi';

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

test('an emptied prompt can be saved and falls back to the default prompt', async ({ page }) => {
  await loginAs(page);
  const prompts = new Map([['classification', makePrompt('classification', { prompt_text: 'Original text', is_active: true })]]);
  await mockApi(page, { articles: [], prompts });
  await page.goto('/');

  const editor = await openClassificationEditor(page);
  await editor.getByRole('button', { name: 'Düzenle' }).click();
  await editor.locator('textarea').fill('');

  await expect(editor.getByText('Boş bırakılırsa varsayılan prompt kullanılır.')).toBeVisible();
  await expect(editor.getByRole('button', { name: 'Kaydet' })).toBeEnabled();

  const req = page.waitForRequest(
    (r) => r.url().endsWith('/api/prompts/classification') && r.method() === 'PUT'
  );
  await editor.getByRole('button', { name: 'Kaydet' }).click();
  expect((await req).postDataJSON().prompt_text).toBe('');

  await expect(editor.getByText('Prompt başarıyla kaydedildi!')).toBeVisible();
  await expect(editor.getByText('varsayılan prompt kullanılır')).toBeVisible();
});

test('classification prompt shows the locked system part read-only, in view and edit mode', async ({ page }) => {
  await loginAs(page);
  const prompts = new Map([['classification', makePrompt('classification', { prompt_text: 'Kriterlerim', is_active: true })]]);
  await mockApi(page, { articles: [], prompts });
  await page.goto('/');

  const editor = await openClassificationEditor(page);
  const locked = editor.getByRole('region', { name: 'Kilitli sistem bölümü' });
  await expect(editor.locator('.prompt-text')).toHaveText('Kriterlerim');
  await expect(locked).toContainText('- NATO: Bündnis');
  await expect(locked).toContainText('JSON');

  await editor.getByRole('button', { name: 'Düzenle' }).click();
  await expect(editor.locator('textarea')).toHaveValue('Kriterlerim'); // editable part only
  await expect(locked).toContainText('- NATO: Bündnis');
  await expect(locked.locator('textarea, input')).toHaveCount(0);

  // Saving sends only the editable text; the locked part is never part of the request.
  await editor.locator('textarea').fill('Yeni kriterler');
  const req = page.waitForRequest((r) => r.url().endsWith('/api/prompts/classification') && r.method() === 'PUT');
  await editor.getByRole('button', { name: 'Kaydet' }).click();
  const body = (await req).postDataJSON();
  expect(body.prompt_text).toBe('Yeni kriterler');
  expect(JSON.stringify(body)).not.toContain('NATO');
});

test('summarization prompt shows the summary-type instructions read-only, in view and edit mode', async ({ page }) => {
  await loginAs(page);
  const prompts = new Map([['summarization', makePrompt('summarization', { prompt_text: 'Özet promptu', is_active: true })]]);
  await mockApi(page, { articles: [], prompts });
  await page.goto('/');

  await page.getByRole('button', { name: 'Ayarlar' }).click();
  await page.getByRole('button', { name: 'Sistem Promptları' }).click();
  const editor = page.locator('.prompt-editor').filter({ hasText: 'Özetleme Promptu' });
  const locked = editor.getByRole('region', { name: 'Kilitli sistem bölümü' });

  await expect(editor.locator('.prompt-text')).toHaveText('Özet promptu');
  await expect(locked).toContainText('brief: Provide a very brief summary');
  await expect(locked).toContainText('standard:');
  await expect(locked).toContainText('detailed:');

  await editor.getByRole('button', { name: 'Düzenle' }).click();
  await expect(editor.locator('textarea')).toHaveValue('Özet promptu');
  await expect(locked).toContainText('brief:');
  await expect(locked.locator('textarea, input')).toHaveCount(0);

  // The classification editor shows its own locked part, not the summary one.
  const classification = page.locator('.prompt-editor').filter({ hasText: 'Sınıflandırma Promptu' });
  await expect(classification.getByRole('region', { name: 'Kilitli sistem bölümü' })).not.toContainText('brief:');
});

test('typing in the editor is not interrupted when the locked part finishes loading', async ({ page }) => {
  await loginAs(page);
  const prompts = new Map([['classification', makePrompt('classification', { prompt_text: 'Kriter', is_active: true })]]);
  await mockApi(page, { articles: [], prompts });
  // Registered after mockApi, so it runs first: hold the locked response back to simulate a slow network.
  await page.route(/\/api\/prompts\/classification\/locked$/, async (route) => {
    await new Promise((resolve) => setTimeout(resolve, 800));
    await route.fallback();
  });
  await page.goto('/');

  const editor = await openClassificationEditor(page);
  await editor.getByRole('button', { name: 'Düzenle' }).click();
  const textarea = editor.locator('textarea');
  await textarea.click();
  await page.keyboard.type(' ek');
  await expect(editor.getByRole('region', { name: 'Kilitli sistem bölümü' })).toHaveCount(0);

  // Once the locked part arrives the same textarea stays focused and keeps what was typed.
  await expect(editor.getByRole('region', { name: 'Kilitli sistem bölümü' })).toBeVisible();
  await expect(textarea).toBeFocused();
  await page.keyboard.type('le');
  await expect(textarea).toHaveValue('Kriter ekle');
});

test('a topic added in Kategoriler shows up in the classification prompt locked list', async ({ page }) => {
  await loginAs(page);
  const prompts = new Map([['classification', makePrompt('classification', { prompt_text: 'Kriter', is_active: true })]]);
  await mockApi(page, { articles: [], prompts, topics: [makeTopic({ id: 501, name: 'Mevcut Konu' })] });
  await page.goto('/');

  const editor = await openClassificationEditor(page);
  const locked = editor.getByRole('region', { name: 'Kilitli sistem bölümü' });
  await expect(locked).toContainText('- Mevcut Konu');
  await expect(locked).not.toContainText('Yeni Konu');

  await page.getByRole('button', { name: 'Kategoriler' }).click();
  const categories = page.locator('.settings-category');
  await categories.getByRole('button', { name: 'Yeni kategori ekle' }).click();
  const form = categories.locator('.add-topic-form');
  await form.getByPlaceholder(/Kategori adı/).fill('Yeni Konu');
  await form.getByRole('button', { name: 'Oluştur' }).click();
  await expect(categories.getByText('Yeni Konu')).toBeVisible();

  await page.getByRole('button', { name: 'Sistem Promptları' }).click();
  const after = page
    .locator('.prompt-editor')
    .filter({ hasText: 'Sınıflandırma Promptu' })
    .getByRole('region', { name: 'Kilitli sistem bölümü' });
  await expect(after).toContainText('- Yeni Konu');
  await expect(after).toContainText('- Mevcut Konu');
});

test('the summarization locked part follows the summary types enabled in Ayarlar › Özet Türleri', async ({ page }) => {
  await loginAs(page, ADMIN_USER);
  const prompts = new Map([['summarization', makePrompt('summarization', { prompt_text: 'Özet promptu', is_active: true })]]);
  await mockApi(page, { articles: [], prompts, settings: { enabled_summary_types: 'brief,standard,detailed' } });
  await page.goto('/');

  const openPromptLocked = async () => {
    await page.getByRole('button', { name: 'Sistem Promptları' }).click();
    return page
      .locator('.prompt-editor')
      .filter({ hasText: 'Özetleme Promptu' })
      .getByRole('region', { name: 'Kilitli sistem bölümü' });
  };

  await page.getByRole('button', { name: 'Ayarlar' }).click();
  let locked = await openPromptLocked();
  await expect(locked).toContainText('standard:');

  // Turn "Standart" off and save.
  await page.getByRole('button', { name: 'Özet Türleri' }).click();
  const content = page.locator('.settings-category');
  await content.getByRole('checkbox', { name: /Standart/ }).uncheck();
  const saved = page.waitForRequest((r) => r.url().endsWith('/api/settings/') && r.method() === 'PUT');
  await content.getByRole('button', { name: 'Ayarları kaydet' }).click();
  await saved;

  locked = await openPromptLocked();
  await expect(locked).toContainText('brief:');
  await expect(locked).toContainText('detailed:');
  await expect(locked).not.toContainText('standard:');
  await expect(locked).toContainText('Write the summary in Turkish.');
});
