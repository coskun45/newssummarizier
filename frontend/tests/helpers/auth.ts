import type { Page } from '@playwright/test';

export interface MockAuthUser {
  id: number;
  email: string;
  role: 'admin' | 'user';
}

export const DEFAULT_USER: MockAuthUser = { id: 1, email: 'tester@example.com', role: 'user' };
export const ADMIN_USER: MockAuthUser = { id: 2, email: 'admin@example.com', role: 'admin' };

/**
 * Seed localStorage with a fake token + user before the app's first script
 * runs, so App.tsx renders <Dashboard/> directly instead of <Login/>.
 * Must be called BEFORE page.goto().
 */
export async function loginAs(page: Page, user: MockAuthUser = DEFAULT_USER): Promise<void> {
  await page.addInitScript(
    ({ token, user }) => {
      window.localStorage.setItem('auth_token', token);
      window.localStorage.setItem('auth_user', JSON.stringify(user));
    },
    { token: 'fake-jwt-token', user }
  );
}
