import { test, expect } from '@playwright/test';
import { loginAs, DEFAULT_USER, ADMIN_USER } from './helpers/auth';
import { mockApi, makeUser } from './helpers/mockApi';

async function openUsersSection(page: import('@playwright/test').Page) {
  await page.getByRole('button', { name: 'Ayarlar' }).click();
  await page.getByRole('button', { name: 'Kullanıcı Yönetimi' }).click();
  return page.locator('.settings-category');
}

test('section is not visible for a non-admin user', async ({ page }) => {
  await loginAs(page, DEFAULT_USER);
  await mockApi(page, { articles: [] });
  await page.goto('/');

  await page.getByRole('button', { name: 'Ayarlar' }).click();
  await expect(page.getByRole('button', { name: 'Kullanıcı Yönetimi' })).not.toBeVisible();
});

test('section is visible for an admin user', async ({ page }) => {
  await loginAs(page, ADMIN_USER);
  await mockApi(page, { articles: [], users: [makeUser({ id: ADMIN_USER.id, email: ADMIN_USER.email, role: 'admin' })] });
  await page.goto('/');

  const modal = await openUsersSection(page);
  await expect(modal.getByText(ADMIN_USER.email)).toBeVisible();
});

test('creating a user sends POST and clears the form', async ({ page }) => {
  await loginAs(page, ADMIN_USER);
  await mockApi(page, { articles: [], users: [makeUser({ id: ADMIN_USER.id, email: ADMIN_USER.email, role: 'admin' })] });
  await page.goto('/');

  const modal = await openUsersSection(page);
  const form = modal.locator('.add-user-form');
  await form.getByPlaceholder('E-Posta Adresi').fill('new.user@example.com');
  await form.getByPlaceholder('Şifre').fill('supersecret123');

  const req = page.waitForRequest((r) => r.url().endsWith('/api/auth/users') && r.method() === 'POST');
  await form.getByRole('button', { name: 'Kullanıcı oluştur' }).click();
  await req;

  await expect(form.getByPlaceholder('E-Posta Adresi')).toHaveValue('');
});

test('duplicate-email error from the backend is shown inline', async ({ page }) => {
  await loginAs(page, ADMIN_USER);
  const existing = makeUser({ id: ADMIN_USER.id, email: ADMIN_USER.email, role: 'admin' });
  const dup = makeUser({ email: 'dup@example.com' });
  await mockApi(page, { articles: [], users: [existing, dup] });
  await page.goto('/');

  const modal = await openUsersSection(page);
  const form = modal.locator('.add-user-form');
  await form.getByPlaceholder('E-Posta Adresi').fill('dup@example.com');
  await form.getByPlaceholder('Şifre').fill('supersecret123');
  await form.getByRole('button', { name: 'Kullanıcı oluştur' }).click();

  await expect(modal.getByText('Bu e-posta adresi zaten kayıtlı')).toBeVisible();
});

test('the current admin cannot delete themselves', async ({ page }) => {
  await loginAs(page, ADMIN_USER);
  const self = makeUser({ id: ADMIN_USER.id, email: ADMIN_USER.email, role: 'admin' });
  const other = makeUser({ email: 'other@example.com' });
  await mockApi(page, { articles: [], users: [self, other] });
  await page.goto('/');

  const modal = await openUsersSection(page);
  const selfRow = modal.locator('.user-list-item').filter({ hasText: ADMIN_USER.email });
  const otherRow = modal.locator('.user-list-item').filter({ hasText: 'other@example.com' });

  await expect(selfRow.getByTitle('Kullanıcıyı sil')).toHaveCount(0);
  await expect(otherRow.getByTitle('Kullanıcıyı sil')).toBeVisible();
});

test('deleting another user shows a native confirm dialog; confirming sends DELETE', async ({ page }) => {
  await loginAs(page, ADMIN_USER);
  const self = makeUser({ id: ADMIN_USER.id, email: ADMIN_USER.email, role: 'admin' });
  const other = makeUser({ email: 'other@example.com' });
  await mockApi(page, { articles: [], users: [self, other] });
  await page.goto('/');

  const modal = await openUsersSection(page);
  page.once('dialog', (dialog) => dialog.accept());
  const req = page.waitForRequest(
    (r) => /\/api\/auth\/users\/\d+$/.test(new URL(r.url()).pathname) && r.method() === 'DELETE'
  );
  await modal.locator('.user-list-item').filter({ hasText: 'other@example.com' }).getByTitle('Kullanıcıyı sil').click();
  await req;

  await expect(modal.getByText('other@example.com')).not.toBeVisible();
});
