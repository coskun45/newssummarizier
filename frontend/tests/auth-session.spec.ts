import { test, expect } from '@playwright/test';
import { loginAs } from './helpers/auth';
import { mockApi } from './helpers/mockApi';

test('a successful login stores the session, opens the dashboard and survives a reload', async ({ page }) => {
  await mockApi(page);
  await page.route('**/api/auth/dev-login', (route) => route.fulfill({ status: 404, json: { detail: 'Not Found' } }));
  await page.route('**/api/auth/login', (route) =>
    route.fulfill({
      json: {
        access_token: 'real-login-token',
        token_type: 'bearer',
        user: { id: 7, email: 'editor@example.com', role: 'user', is_active: true, created_at: new Date().toISOString() },
      },
    })
  );
  await page.goto('/');

  const dashboardAuthHeaders: (string | undefined)[] = [];
  page.on('request', (r) => {
    if (r.url().includes('/api/') && !r.url().includes('/api/auth/')) dashboardAuthHeaders.push(r.headers()['authorization']);
  });
  const loginReq = page.waitForRequest((r) => r.url().includes('/api/auth/login'));
  await page.getByLabel('E-Posta').fill('editor@example.com');
  await page.getByLabel('Şifre').fill('s3cret');
  await page.getByRole('button', { name: 'Giriş Yap' }).click();
  expect((await loginReq).postDataJSON()).toEqual({ email: 'editor@example.com', password: 's3cret' });

  await expect(page.getByRole('button', { name: 'Kullanıcı menüsü: editor@example.com' })).toBeVisible();
  expect(await page.evaluate(() => localStorage.getItem('auth_token'))).toBe('real-login-token');

  // Every dashboard API call made after login carries the JWT
  await expect.poll(() => dashboardAuthHeaders.length).toBeGreaterThan(0);
  expect(new Set(dashboardAuthHeaders)).toEqual(new Set(['Bearer real-login-token']));

  // Reload: no login flash, still logged in
  await page.reload();
  await expect(page.getByRole('button', { name: 'Kullanıcı menüsü: editor@example.com' })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Giriş Yap' })).toHaveCount(0);
});

test('shows the generic Turkish error when the login request fails without a detail', async ({ page }) => {
  await page.route('**/api/auth/dev-login', (route) => route.fulfill({ status: 404, json: { detail: 'Not Found' } }));
  await page.route('**/api/auth/login', (route) => route.fulfill({ status: 500, body: '' }));
  await page.goto('/');

  await page.getByLabel('E-Posta').fill('editor@example.com');
  await page.getByLabel('Şifre').fill('whatever');
  await page.getByRole('button', { name: 'Giriş Yap' }).click();

  await expect(page.getByText('Giriş başarısız. Lütfen tekrar deneyin.')).toBeVisible();
});

test('an expired token (401 from any API call) logs the user out to the login page', async ({ page }) => {
  await loginAs(page);
  await mockApi(page);
  await page.route('**/api/auth/dev-login', (route) => route.fulfill({ status: 404, json: { detail: 'Not Found' } }));
  await page.goto('/');
  await page.getByRole('button', { name: 'Haberler', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Arşiv', exact: true })).toBeVisible();

  // The token expires: from now on the article list answers 401. Opening Arşiv needs a
  // fresh (uncached) list query, so it hits the expired token.
  await page.route((url) => url.pathname === '/api/articles/', (route) =>
    route.fulfill({ status: 401, json: { detail: 'Could not validate credentials' } })
  );
  await page.getByRole('button', { name: 'Arşiv', exact: true }).click();

  await expect(page.getByRole('button', { name: 'Giriş Yap' })).toBeVisible();
  expect(await page.evaluate(() => localStorage.getItem('auth_token'))).toBeNull();
  expect(await page.evaluate(() => localStorage.getItem('auth_user'))).toBeNull();
});
