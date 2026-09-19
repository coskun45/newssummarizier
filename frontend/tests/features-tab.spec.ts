import { readFileSync } from 'node:fs';
import { test, expect, type Page } from '@playwright/test';
import { loginAs, ADMIN_USER } from './helpers/auth';
import { mockApi } from './helpers/mockApi';

interface FeatureEntry { id: string; title: string; description: string }
interface VersionEntry { version: string; title: string; features: FeatureEntry[] }

// The Features tab renders src/data/features.json, so the spec reads the same file.
const { versions } = JSON.parse(
  readFileSync(new URL('../src/data/features.json', import.meta.url), 'utf-8'),
) as { versions: VersionEntry[] };
const allFeatures = versions.flatMap((v) => v.features);

async function openFeatures(page: Page) {
  await mockApi(page, { articles: [] });
  await page.goto('/');
  await page.getByRole('button', { name: 'Ayarlar' }).click();
  await page.getByRole('button', { name: 'Features' }).click();
}

test('features.json has unique versions and ids, and complete entries', () => {
  expect(versions.length).toBeGreaterThan(0);
  expect(new Set(versions.map((v) => v.version)).size).toBe(versions.length);
  expect(new Set(allFeatures.map((f) => f.id)).size).toBe(allFeatures.length);
  for (const v of versions) {
    expect(v.version).toMatch(/^v\d+$/);
    expect(v.title.trim()).not.toBe('');
    expect(v.features.length).toBeGreaterThan(0);
    for (const f of v.features) {
      for (const value of [f.id, f.title, f.description]) {
        expect(value.trim()).not.toBe('');
      }
      expect(f.id).toMatch(/^[a-z0-9]+(-[a-z0-9]+)*$/);
      expect(Object.keys(f).sort()).toEqual(['description', 'id', 'title']);
    }
  }
});

test('Ayarlar › Features lists every feature from features.json grouped by version', async ({ page }) => {
  await loginAs(page);
  await openFeatures(page);

  await expect(page.getByRole('heading', { name: 'Features', level: 2 })).toBeVisible();

  for (const v of versions) {
    await expect(page.getByRole('heading', { name: `${v.version} · ${v.title}`, exact: true, level: 3 })).toBeVisible();
    for (const feature of v.features) {
      await expect(page.getByRole('heading', { name: feature.title, exact: true, level: 4 })).toBeVisible();
      await expect(page.getByText(feature.description, { exact: true })).toBeVisible();
    }
  }
});

test('Ayarlar › Features shows the newest version first', async ({ page }) => {
  await loginAs(page);
  await openFeatures(page);

  const expected = [...versions]
    .sort((a, b) => Number(b.version.slice(1)) - Number(a.version.slice(1)))
    .map((v) => `${v.version} · ${v.title}`);
  await expect(page.getByRole('heading', { level: 3 })).toHaveText(expected);
});

test('Features tab is available to non-admin users and other Ayarlar categories still work', async ({ page }) => {
  await loginAs(page);
  await openFeatures(page);
  await expect(page.getByRole('button', { name: 'Kullanıcı Yönetimi' })).not.toBeVisible();

  await page.getByRole('button', { name: 'Kategoriler' }).click();
  await expect(page.getByRole('heading', { name: allFeatures[0].title, exact: true, level: 4 })).not.toBeVisible();
});

test('Features tab is also shown to admins next to Kullanıcı Yönetimi', async ({ page }) => {
  await loginAs(page, ADMIN_USER);
  await openFeatures(page);
  await expect(page.getByRole('button', { name: 'Kullanıcı Yönetimi' })).toBeVisible();
  await expect(page.getByRole('heading', { name: allFeatures[0].title, exact: true, level: 4 })).toBeVisible();
});
