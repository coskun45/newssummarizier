import { test, expect } from '@playwright/test';
import { ADMIN_USER, loginAs } from './helpers/auth';
import { mockApi, makeTopic } from './helpers/mockApi';

async function openSummaryTypesCategory(page: import('@playwright/test').Page) {
  await page.getByRole('button', { name: 'Ayarlar' }).click();
  await page.getByRole('button', { name: 'Özet Türleri' }).click();
  return page.locator('.settings-category');
}

test('opens settings and shows current values', async ({ page }) => {
  await loginAs(page);
  await mockApi(page, {
    articles: [],
    settings: { enabled_summary_types: 'brief,standard' },
  });
  await page.goto('/');

  const content = await openSummaryTypesCategory(page);

  await expect(content.getByRole('heading', { name: 'Özet Türleri' })).toBeVisible();
  await expect(content.getByRole('checkbox', { name: /Kısa/ })).toBeChecked();
  await expect(content.getByRole('checkbox', { name: /Detaylı/ })).not.toBeChecked();
});

test('navigating away without saving does not send a PUT', async ({ page }) => {
  await loginAs(page);
  await mockApi(page, { articles: [] });
  let putCalled = false;
  await page.route(
    (url) => url.pathname === '/api/settings/',
    (route) => {
      if (route.request().method() === 'PUT') putCalled = true;
      route.fallback();
    }
  );
  await page.goto('/');

  await openSummaryTypesCategory(page);
  await page.getByRole('button', { name: 'Haberler', exact: true }).click();

  await expect(page.locator('.settings-category')).not.toBeVisible();
  expect(putCalled).toBe(false);
});

test('saving toggled summary types sends PUT', async ({ page }) => {
  await loginAs(page, ADMIN_USER);
  await mockApi(page, {
    articles: [],
    settings: { enabled_summary_types: 'brief,standard,detailed' },
  });
  await page.goto('/');

  const content = await openSummaryTypesCategory(page);
  await content.getByRole('checkbox', { name: /Detaylı/ }).uncheck();

  const req = page.waitForRequest(
    (r) => r.url().endsWith('/api/settings/') && r.method() === 'PUT' && !r.postDataJSON().enabled_summary_types.includes('detailed')
  );
  await content.getByRole('button', { name: 'Ayarları kaydet' }).click();
  await req;
});

test('save button disabled when all summary types are unchecked', async ({ page }) => {
  await loginAs(page, ADMIN_USER);
  await mockApi(page, { articles: [] });
  await page.goto('/');

  const content = await openSummaryTypesCategory(page);
  await content.getByRole('checkbox', { name: /Kısa/ }).uncheck();
  await content.getByRole('checkbox', { name: /Standart/ }).uncheck();
  await content.getByRole('checkbox', { name: /Detaylı/ }).uncheck();

  await expect(content.getByRole('button', { name: 'Ayarları kaydet' })).toBeDisabled();
});


test('the last checked category cannot be unchecked', async ({ page }) => {
  // #27: unchecking the last topic emptied the list, and empty means "all topics"
  await loginAs(page, ADMIN_USER);
  const topics = [makeTopic({ id: 1, name: 'NATO' }), makeTopic({ id: 2, name: 'Spor' })];
  await mockApi(page, { articles: [], topics, settings: { enabled_topics: '1' } });
  await page.goto('/');
  await page.getByRole('button', { name: 'Ayarlar' }).click();
  await page.getByRole('button', { name: 'Kategoriler' }).click();

  const content = page.locator('.settings-category');
  const nato = content.getByRole('checkbox', { name: /NATO/ });
  await expect(nato).toBeChecked();
  await expect(nato).toBeDisabled();
  await expect(content.getByRole('checkbox', { name: /Spor/ })).not.toBeChecked();

  await content.getByRole('checkbox', { name: /Spor/ }).check();
  await expect(nato).toBeEnabled();
});

test('the automatic refresh interval is saved from RSS Beslemeleri', async ({ page }) => {
  // #27: the interval was stored but never used and could not be changed in the UI
  await loginAs(page, ADMIN_USER);
  await mockApi(page, { articles: [], settings: { feed_refresh_interval: 3600 } });
  await page.goto('/');
  await page.getByRole('button', { name: 'Ayarlar' }).click();
  await page.getByRole('button', { name: 'RSS Beslemeleri' }).click();

  const select = page.getByLabel('Otomatik yenileme aralığı');
  await expect(select).toHaveValue('3600');
  await select.selectOption({ label: '2 saat' });

  const req = page.waitForRequest(
    (r) => r.url().endsWith('/api/settings/') && r.method() === 'PUT' && r.postDataJSON().feed_refresh_interval === 7200
  );
  await page.getByRole('button', { name: 'Aralığı kaydet' }).click();
  await req;
  await expect(page.getByRole('button', { name: 'Aralığı kaydet' })).toBeDisabled();
});

test('the max article age is saved from RSS Beslemeleri', async ({ page }) => {
  // DW's feed also lists months-old background pieces; the cutoff that skips them is set here
  await loginAs(page, ADMIN_USER);
  await mockApi(page, { articles: [] });
  await page.goto('/');
  await page.getByRole('button', { name: 'Ayarlar' }).click();
  await page.getByRole('button', { name: 'RSS Beslemeleri' }).click();

  const select = page.getByLabel('En fazla haber yaşı');
  await expect(select).toHaveValue('72');
  await select.selectOption({ label: 'Sınır yok' });

  const req = page.waitForRequest(
    (r) => r.url().endsWith('/api/settings/') && r.method() === 'PUT' && r.postDataJSON().max_article_age_hours === 0
  );
  await page.getByRole('button', { name: 'Yaş sınırını kaydet' }).click();
  expect(Object.keys((await req).postDataJSON())).toEqual(['max_article_age_hours']);
  await expect(page.getByRole('button', { name: 'Yaş sınırını kaydet' })).toBeDisabled();
});

async function openModelsCategory(page: import('@playwright/test').Page) {
  await page.getByRole('button', { name: 'Ayarlar' }).click();
  await page.getByRole('button', { name: 'Yapay Zekâ Modelleri' }).click();
  return page.locator('.settings-category');
}

test('model cards show the saved choice, and the price only on hover', async ({ page }) => {
  await loginAs(page);
  await mockApi(page, { articles: [], settings: { classification_model: 'gpt-6-luna', summary_model: 'gpt-4o' } });
  await page.goto('/');

  const content = await openModelsCategory(page);
  const classification = content.getByRole('group', { name: 'Sınıflandırma modeli' });
  const summary = content.getByRole('group', { name: 'Özet modeli' });

  await expect(classification.getByRole('radio', { name: 'gpt-6-luna' })).toBeChecked();
  await expect(summary.getByRole('radio', { name: 'gpt-4o', exact: true })).toBeChecked();

  // The price is not on the card itself — it appears when hovering the model.
  const lunaCard = classification.locator('label', { has: page.getByRole('radio', { name: 'gpt-6-luna' }) });
  const price = lunaCard.getByRole('tooltip');
  await expect(price).toBeHidden();
  await lunaCard.hover();
  await expect(price).toBeVisible();
  await expect(price).toContainText('Giriş$0.10');
  await expect(price).toContainText('Çıkış$0.50');

  // Non-admins see the choice but can't change it.
  await expect(classification.getByRole('radio', { name: 'gpt-4o-mini' })).toBeDisabled();
  await expect(content.getByText('Bu ayarları yalnızca yöneticiler değiştirebilir.')).toBeVisible();
});

test('without a saved choice "Sunucu varsayılanı" is selected and names the models in use', async ({ page }) => {
  await loginAs(page, ADMIN_USER);
  await mockApi(page, {
    articles: [],
    settings: { default_models: { classification: 'gpt-6-luna', summary: 'gpt-4o-mini', detailed_summary: 'gpt-4o' } },
  });
  await page.goto('/');

  const content = await openModelsCategory(page);
  const summary = content.getByRole('group', { name: 'Özet modeli' });
  const serverDefault = summary.getByRole('radio', { name: /Sunucu varsayılanı/ });

  await expect(serverDefault).toBeChecked();
  await expect(summary.getByText('gpt-4o-mini / gpt-4o')).toBeVisible();
  await expect(content.getByRole('group', { name: 'Sınıflandırma modeli' }).getByRole('radio', { name: /Sunucu varsayılanı/ }))
    .toBeChecked();
  await expect(content.getByRole('button', { name: 'Modelleri kaydet' })).toBeDisabled();

  // Hovering the default shows the price of each model it stands for.
  const card = summary.locator('label', { has: page.getByRole('radio', { name: /Sunucu varsayılanı/ }) });
  await card.hover();
  await expect(card.getByRole('tooltip')).toContainText('gpt-4o-mini');
  await expect(card.getByRole('tooltip')).toContainText('Çıkış$10.00');
});

test('choosing "Sunucu varsayılanı" again clears a saved model', async ({ page }) => {
  // Review: once a model was saved there was no way back to the server default.
  await loginAs(page, ADMIN_USER);
  await mockApi(page, { articles: [], settings: { classification_model: 'gpt-4o', summary_model: 'gpt-4o' } });
  await page.goto('/');

  const content = await openModelsCategory(page);
  await content.getByRole('group', { name: 'Özet modeli' }).getByText('Sunucu varsayılanı').click();

  const req = page.waitForRequest((r) => r.url().endsWith('/api/settings/') && r.method() === 'PUT');
  await content.getByRole('button', { name: 'Modelleri kaydet' }).click();
  expect((await req).postDataJSON()).toEqual({ summary_model: '' });
});

test('admin saving models sends only the model fields', async ({ page }) => {
  await loginAs(page, ADMIN_USER);
  await mockApi(page, { articles: [] });
  await page.goto('/');

  const content = await openModelsCategory(page);
  const save = content.getByRole('button', { name: 'Modelleri kaydet' });
  await expect(save).toBeDisabled(); // nothing changed yet

  await content.getByRole('group', { name: 'Sınıflandırma modeli' }).getByText('gpt-4o-mini').click();
  await content.getByRole('group', { name: 'Özet modeli' }).getByText('gpt-6.1-sol').click();

  const req = page.waitForRequest((r) => r.url().endsWith('/api/settings/') && r.method() === 'PUT');
  await save.click();
  expect((await req).postDataJSON()).toEqual({ classification_model: 'gpt-4o-mini', summary_model: 'gpt-6.1-sol' });
  await expect(save).toBeDisabled(); // saved values are now the current ones
});

test('saving another tab does not put an unsaved model choice live', async ({ page }) => {
  // Review: one shared save sent every tab's state — an expensive model picked but not saved
  // went live when the admin saved Özet Türleri.
  await loginAs(page, ADMIN_USER);
  await mockApi(page, { articles: [] });
  await page.goto('/');

  const content = await openModelsCategory(page);
  await content.getByRole('group', { name: 'Özet modeli' }).getByText('gpt-6.1-sol').click();
  await page.getByRole('button', { name: 'Özet Türleri' }).click();
  await content.getByRole('checkbox', { name: /Detaylı/ }).uncheck();

  const req = page.waitForRequest((r) => r.url().endsWith('/api/settings/') && r.method() === 'PUT');
  await content.getByRole('button', { name: 'Ayarları kaydet' }).click();
  expect((await req).postDataJSON()).toEqual({ enabled_summary_types: 'brief,standard' });
});

test('saving models keeps unsaved edits in other tabs', async ({ page }) => {
  // Review: the refetch after one tab's save reset every tab's form, silently dropping edits.
  await loginAs(page, ADMIN_USER);
  await mockApi(page, { articles: [], settings: { enabled_summary_types: 'brief,standard,detailed' } });
  await page.goto('/');

  const content = await openSummaryTypesCategory(page);
  await content.getByRole('checkbox', { name: /Detaylı/ }).uncheck(); // not saved

  await page.getByRole('button', { name: 'Yapay Zekâ Modelleri' }).click();
  await content.getByRole('group', { name: 'Özet modeli' }).getByText('gpt-6.1-sol').click();
  const saved = page.waitForResponse((r) => r.url().endsWith('/api/settings/') && r.request().method() === 'PUT');
  await content.getByRole('button', { name: 'Modelleri kaydet' }).click();
  await saved;
  await page.waitForResponse((r) => r.url().endsWith('/api/settings/') && r.request().method() === 'GET');

  await page.getByRole('button', { name: 'Özet Türleri' }).click();
  await expect(content.getByRole('checkbox', { name: /Detaylı/ })).not.toBeChecked();
});

test('the Kategoriler save is not blocked by an invalid Özet Türleri edit', async ({ page }) => {
  // Review: the topics button still checked the summary-type selection it no longer saves.
  await loginAs(page, ADMIN_USER);
  await mockApi(page, { articles: [] });
  await page.goto('/');

  const content = await openSummaryTypesCategory(page);
  for (const name of [/Kısa/, /Standart/, /Detaylı/]) await content.getByRole('checkbox', { name }).uncheck();

  await page.getByRole('button', { name: 'Kategoriler' }).click();
  await expect(content.getByRole('button', { name: 'Ayarları kaydet' })).toBeEnabled();
});
