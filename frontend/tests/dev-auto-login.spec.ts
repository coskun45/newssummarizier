import { test, expect } from '@playwright/test';
import { ADMIN_USER } from './helpers/auth';
import { mockApi } from './helpers/mockApi';

// No loginAs(): the app starts without a stored session and asks POST /api/auth/dev-login.

test('opens the dashboard directly when dev auto-login is enabled', async ({ page }) => {
  await mockApi(page);
  await page.route('**/api/auth/dev-login', (route) =>
    route.fulfill({
      json: {
        access_token: 'dev-token',
        token_type: 'bearer',
        user: { ...ADMIN_USER, is_active: true, created_at: new Date().toISOString() },
      },
    })
  );

  await page.goto('/');

  await expect(page.getByRole('img', { name: 'Bülten' })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Giriş Yap' })).toHaveCount(0);
  expect(await page.evaluate(() => localStorage.getItem('auth_token'))).toBe('dev-token');
});

test('shows the login page when dev auto-login is disabled (404)', async ({ page }) => {
  await page.route('**/api/auth/dev-login', (route) =>
    route.fulfill({ status: 404, json: { detail: 'Not Found' } })
  );

  await page.goto('/');

  await expect(page.getByRole('button', { name: 'Giriş Yap' })).toBeVisible();
});
