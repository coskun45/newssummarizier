import { test, expect } from '@playwright/test';

test.beforeEach(async ({ page }) => {
  // Unauthenticated: no auth_user in localStorage, so App renders <Login/>,
  // which is where the theme toggle also lives — no backend needed.
  await page.goto('/');
});

test('cycles theme and persists the choice across reloads', async ({ page }) => {
  const html = page.locator('html');
  const toggle = page.getByRole('button', { name: /Tema:/ });
  await expect(toggle).toBeVisible();

  // Starts on 'system' by default.
  await expect(toggle).toHaveAccessibleName('Tema: Sistem');

  // system -> light
  await toggle.click();
  await expect(toggle).toHaveAccessibleName('Tema: Açık');
  await expect(html).toHaveAttribute('data-theme', 'light');

  // light -> dark
  await toggle.click();
  await expect(toggle).toHaveAccessibleName('Tema: Koyu');
  await expect(html).toHaveAttribute('data-theme', 'dark');

  // Persists across a reload.
  await page.reload();
  await expect(page.getByRole('button', { name: /Tema:/ })).toHaveAccessibleName('Tema: Koyu');
  await expect(html).toHaveAttribute('data-theme', 'dark');
});

test('system mode follows the OS color scheme', async ({ page }) => {
  const html = page.locator('html');
  const toggle = page.getByRole('button', { name: /Tema:/ });

  await page.emulateMedia({ colorScheme: 'dark' });
  // system default should already resolve to dark once emulation is set and the page reloaded.
  await page.reload();
  await expect(html).toHaveAttribute('data-theme', 'dark');

  // Cycle system -> light -> dark -> system to get back to 'system' explicitly.
  await toggle.click();
  await toggle.click();
  await toggle.click();
  await expect(toggle).toHaveAccessibleName('Tema: Sistem');
  await expect(html).toHaveAttribute('data-theme', 'dark');

  await page.emulateMedia({ colorScheme: 'light' });
  await expect(html).toHaveAttribute('data-theme', 'light');
});
