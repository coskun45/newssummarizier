import { test, expect } from '@playwright/test';
import { loginAs } from './helpers/auth';
import { mockApi } from './helpers/mockApi';

test('the deployed version is shown in the profile menu, only after opening it', async ({ page }) => {
  await loginAs(page);
  await mockApi(page, { articles: [], appVersion: '2.4.0' });
  await page.goto('/');

  const avatar = page.getByRole('button', { name: /Kullanıcı menüsü/ });
  await expect(avatar).toBeVisible();
  await expect(page.getByText('v2.4.0', { exact: true })).toHaveCount(0);

  await avatar.click();
  const menu = page.getByRole('menu');
  await expect(menu.getByText('Sürüm', { exact: true })).toBeVisible();
  await expect(menu.getByText('v2.4.0', { exact: true })).toBeVisible();
  await expect(menu.getByRole('button', { name: 'Çıkış Yap' })).toBeVisible();
});

test('Ayarlar › Features shows the current version', async ({ page }) => {
  await loginAs(page);
  await mockApi(page, { articles: [], appVersion: '3.1.0' });
  await page.goto('/');
  await page.getByRole('button', { name: 'Ayarlar' }).click();
  await page.getByRole('button', { name: 'Features' }).click();

  await expect(page.getByText(/Güncel sürüm:\s*v3\.1\.0/)).toBeVisible();
});
