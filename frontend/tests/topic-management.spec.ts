import { test, expect } from '@playwright/test';
import { loginAs } from './helpers/auth';
import { mockApi, makeTopic } from './helpers/mockApi';

const TOPIC = makeTopic({ id: 401, name: 'Existing Topic' });

async function openSettings(page: import('@playwright/test').Page) {
  await page.getByRole('button', { name: 'Ayarlar' }).click();
  await page.getByRole('button', { name: 'Kategoriler' }).click();
  return page.locator('.settings-category');
}

test('adding a topic sends POST and clears the form', async ({ page }) => {
  await loginAs(page);
  await mockApi(page, { topics: [TOPIC], articles: [] });
  await page.goto('/');

  const modal = await openSettings(page);
  await modal.getByRole('button', { name: 'Yeni kategori ekle' }).click();
  const form = modal.locator('.add-topic-form');
  await form.getByPlaceholder(/Kategori adı/).fill('New Topic');

  const req = page.waitForRequest((r) => r.url().endsWith('/api/topics/') && r.method() === 'POST');
  await form.getByRole('button', { name: 'Oluştur' }).click();
  await req;

  await expect(modal.getByRole('button', { name: 'Yeni kategori ekle' })).toBeVisible();
});

test('editing a topic name via the icon-only save button sends PUT', async ({ page }) => {
  await loginAs(page);
  await mockApi(page, { topics: [TOPIC], articles: [] });
  await page.goto('/');

  const modal = await openSettings(page);
  // Positional, not hasText-scoped: once editing starts, the topic's name only
  // exists as an <input value>, which doesn't count as element textContent,
  // so a hasText("Existing Topic") locator would stop matching mid-test.
  const row = modal.locator('.topic-item').first();
  await row.getByTitle('Düzenle').click();
  await row.locator('input.topic-input').first().fill('Renamed Topic');

  const req = page.waitForRequest(
    (r) => /\/api\/topics\/\d+$/.test(new URL(r.url()).pathname) && r.method() === 'PUT'
  );
  // Icon-only, no accessible name — documented CSS-selector exception.
  await row.locator('.save-edit-button').click();
  await req;

  await expect(modal.getByText('Renamed Topic')).toBeVisible();
});

test('canceling an edit via the icon-only cancel button reverts without a request', async ({ page }) => {
  await loginAs(page);
  await mockApi(page, { topics: [TOPIC], articles: [] });
  let putCalled = false;
  await page.route(
    (url) => /\/api\/topics\/\d+$/.test(url.pathname),
    (route) => {
      if (route.request().method() === 'PUT') putCalled = true;
      route.fallback();
    }
  );
  await page.goto('/');

  const modal = await openSettings(page);
  const row = modal.locator('.topic-item').first();
  await row.getByTitle('Düzenle').click();
  await row.locator('input.topic-input').first().fill('Should Not Save');
  await row.locator('.cancel-edit-button').click();

  await expect(modal.getByText('Existing Topic')).toBeVisible();
  expect(putCalled).toBe(false);
});

test('deleting a topic shows a native confirm dialog with the article-reassignment warning text; dismissing sends nothing', async ({ page }) => {
  await loginAs(page);
  await mockApi(page, { topics: [TOPIC], articles: [] });
  let deleteCalled = false;
  await page.route(
    (url) => /\/api\/topics\/\d+$/.test(url.pathname),
    (route) => {
      if (route.request().method() === 'DELETE') deleteCalled = true;
      route.fallback();
    }
  );
  await page.goto('/');

  const modal = await openSettings(page);
  let dialogMessage = '';
  page.once('dialog', (dialog) => {
    dialogMessage = dialog.message();
    dialog.dismiss();
  });
  const row = modal.locator('.topic-item').filter({ hasText: 'Existing Topic' });
  await row.getByTitle('Sil').click();

  expect(dialogMessage).toBe(
    '"Existing Topic" kategorisini silmek istediğinizden emin misiniz? Tüm makale atamaları kaldırılacak.'
  );
  await expect(modal.getByText('Existing Topic')).toBeVisible();
  expect(deleteCalled).toBe(false);
});

test('confirming delete sends DELETE', async ({ page }) => {
  await loginAs(page);
  await mockApi(page, { topics: [TOPIC], articles: [] });
  await page.goto('/');

  const modal = await openSettings(page);
  page.once('dialog', (dialog) => dialog.accept());
  const row = modal.locator('.topic-item').filter({ hasText: 'Existing Topic' });
  const req = page.waitForRequest(
    (r) => /\/api\/topics\/\d+$/.test(new URL(r.url()).pathname) && r.method() === 'DELETE'
  );
  await row.getByTitle('Sil').click();
  await req;

  await expect(modal.getByText('Existing Topic')).not.toBeVisible();
});
