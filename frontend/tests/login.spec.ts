import { test, expect } from '@playwright/test';

test.beforeEach(async ({ page }) => {
  // Unauthenticated: no auth_user in localStorage, so App renders <Login/>.
  await page.goto('/');
});

test('renders the login form when logged out', async ({ page }) => {
  await expect(page.getByRole('heading', { name: 'News Summarizer' })).toBeVisible();
  await expect(page.getByLabel('E-Posta')).toBeVisible();
  await expect(page.getByLabel('Şifre')).toBeVisible();
  await expect(page.getByRole('button', { name: 'Giriş Yap' })).toBeVisible();
});

test('shows an error message when login fails', async ({ page }) => {
  await page.getByLabel('E-Posta').fill('nobody@example.com');
  await page.getByLabel('Şifre').fill('wrong-password');
  await page.getByRole('button', { name: 'Giriş Yap' }).click();

  await expect(page.locator('.login-error')).toBeVisible();
});
