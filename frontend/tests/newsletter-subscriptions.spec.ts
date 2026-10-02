import { test, expect } from '@playwright/test';
import type { Page } from '@playwright/test';
import { ADMIN_USER, loginAs } from './helpers/auth';
import {
  mockApi,
  makeBulletinCategory,
  makeNewsletterDelivery,
  makeNewsletterSubscription,
} from './helpers/mockApi';

async function openSubscriptions(page: Page) {
  await page.getByRole('button', { name: 'Bülten', exact: true }).click();
  await page.getByRole('tab', { name: 'Abonelikler' }).click();
  return page.locator('.newsletter-panel');
}

test('Bülten tab has a Bülten Oluştur / Abonelikler switch', async ({ page }) => {
  await loginAs(page);
  await mockApi(page);
  await page.goto('/');

  await page.getByRole('button', { name: 'Bülten', exact: true }).click();
  await expect(page.getByRole('tab', { name: 'Bülten Oluştur' })).toHaveAttribute('aria-selected', 'true');
  await expect(page.getByRole('button', { name: 'Oluştur ve İndir' })).toBeVisible();

  await page.getByRole('tab', { name: 'Abonelikler' }).click();
  await expect(page.getByRole('heading', { name: 'Bülten Aboneliği' })).toBeVisible();
  await expect(page.getByText('Henüz aboneliğiniz yok.')).toBeVisible();
  await expect(page.getByRole('button', { name: 'Oluştur ve İndir' })).not.toBeVisible();
});

test('creating a weekly subscription sends the chosen settings', async ({ page }) => {
  await loginAs(page);
  const asya = makeBulletinCategory({ id: 7, name: 'ASYA' });
  const state = await mockApi(page, { bulletinCategories: [makeBulletinCategory({ id: 6, name: 'AVRUPA' }), asya] });
  await page.goto('/');
  const panel = await openSubscriptions(page);

  await panel.getByRole('button', { name: 'Yeni Abonelik' }).click();
  const form = panel.getByRole('form', { name: 'Abonelik formu' });
  await expect(form.getByLabel('E-posta adresi')).toHaveValue('tester@example.com');

  // The weekday picker only exists for weekly subscriptions.
  await expect(form.getByLabel('Gün', { exact: true })).toHaveCount(0);
  await form.getByLabel('Haftalık').check();
  await expect(form.getByText('son 7 günün haberleri')).toBeVisible();
  await form.getByLabel('Gün', { exact: true }).selectOption({ label: 'Cuma' });
  await form.getByLabel('Saat').selectOption({ label: '07:00' });
  await form.getByLabel('En fazla haber').fill('15');
  await form.getByLabel('Yüksek').check();
  await form.getByLabel('ASYA').check();
  await form.getByLabel('Sadece Word dosyası').check();
  await form.getByRole('button', { name: 'Abone Ol' }).click();

  await expect(page.getByText('Abonelik oluşturuldu.')).toBeVisible();
  expect(state.newsletterRequests).toEqual([{
    email: 'tester@example.com',
    frequency: 'weekly',
    send_hour: 7,
    send_weekday: 4,
    max_articles: 15,
    priorities: ['high'],
    include_favorites: false,
    category_ids: [7],
    delivery_format: 'docx',
  }]);

  const card = panel.getByRole('listitem', { name: 'Abonelik tester@example.com' });
  await expect(card.getByText('Aktif')).toBeVisible();
  await expect(card.getByText('Haftalık · her Cuma 07:00')).toBeVisible();
  await expect(card.getByText('en fazla 15 haber · Yüksek · ASYA · Sadece Word dosyası')).toBeVisible();
});

test('a foreign address waits for confirmation', async ({ page }) => {
  await loginAs(page);
  await mockApi(page);
  await page.goto('/');
  const panel = await openSubscriptions(page);

  await panel.getByRole('button', { name: 'Yeni Abonelik' }).click();
  const form = panel.getByRole('form', { name: 'Abonelik formu' });
  await form.getByLabel('E-posta adresi').fill('colleague@example.com');
  await expect(form.getByText('önce bir onay maili gider')).toBeVisible();
  await form.getByRole('button', { name: 'Abone Ol' }).click();

  await expect(page.getByText('colleague@example.com adresine onay maili gönderildi.')).toBeVisible();
  const card = panel.getByRole('listitem', { name: 'Abonelik colleague@example.com' });
  await expect(card.getByText('Onay bekliyor')).toBeVisible();
  await expect(card.getByRole('button', { name: 'Onay mailini tekrar gönder' })).toBeVisible();
  await expect(card.getByRole('button', { name: 'Şimdi gönder' })).toHaveCount(0);
});

test('pause, resume, send now, history and delete', async ({ page }) => {
  await loginAs(page);
  const sub = makeNewsletterSubscription({ id: 42 });
  await mockApi(page, {
    newsletterSubscriptions: [sub],
    newsletterDeliveries: new Map([[42, [makeNewsletterDelivery({ status: 'skipped_no_articles', article_count: 0 })]]]),
  });
  await page.goto('/');
  const panel = await openSubscriptions(page);
  const card = panel.getByRole('listitem', { name: 'Abonelik tester@example.com' });

  await card.getByRole('button', { name: 'Durdur' }).click();
  await expect(card.getByText('Durduruldu')).toBeVisible();
  await card.getByRole('button', { name: 'Sürdür' }).click();
  await expect(card.getByText('Aktif')).toBeVisible();

  await card.getByRole('button', { name: 'Geçmiş' }).click();
  await expect(card.getByText('Haber yok (bilgi maili)')).toBeVisible();

  await card.getByRole('button', { name: 'Şimdi gönder' }).click();
  // Building takes minutes, so the request only queues it; the result appears in Geçmiş.
  await expect(page.getByText('Bülten hazırlanıyor', { exact: false })).toBeVisible();
  await expect(card.getByRole('list', { name: 'Gönderim geçmişi' }).getByText('Gönderildi')).toBeVisible();

  page.once('dialog', (dialog) => dialog.accept());
  await card.getByRole('button', { name: 'Sil' }).click();
  await expect(panel.getByText('Henüz aboneliğiniz yok.')).toBeVisible();
});

test('editing keeps the existing settings in the form', async ({ page }) => {
  await loginAs(page);
  const state = await mockApi(page, {
    newsletterSubscriptions: [makeNewsletterSubscription({ id: 5, send_hour: 18, max_articles: 20 })],
  });
  await page.goto('/');
  const panel = await openSubscriptions(page);

  await panel.getByRole('button', { name: 'Düzenle' }).click();
  const form = panel.getByRole('form', { name: 'Abonelik formu' });
  await expect(form.getByLabel('Saat')).toHaveValue('18');
  await expect(form.getByLabel('En fazla haber')).toHaveValue('20');
  await form.getByLabel('Sadece mail').check();
  await form.getByRole('button', { name: 'Kaydet' }).click();

  await expect(page.getByText('Abonelik güncellendi.')).toBeVisible();
  expect(state.newsletterRequests[0].delivery_format).toBe('email');
  expect(state.newsletterRequests[0].send_hour).toBe(18);
});

test('editing a pending subscription without changing the address sends no confirmation mail', async ({ page }) => {
  // Regression: any save of a pending subscription claimed "onay maili gönderildi" (or "gönderilemedi").
  await loginAs(page);
  await mockApi(page, {
    newsletterSubscriptions: [makeNewsletterSubscription({
      id: 9, email: 'colleague@example.com', status: 'pending', confirm_sent_at: new Date().toISOString(),
    })],
  });
  await page.goto('/');
  const panel = await openSubscriptions(page);
  await panel.getByRole('button', { name: 'Düzenle' }).click();
  const form = panel.getByRole('form', { name: 'Abonelik formu' });
  await form.getByLabel('Saat').selectOption({ label: '09:00' });
  await form.getByRole('button', { name: 'Kaydet' }).click();
  await expect(page.getByText('Abonelik güncellendi.')).toBeVisible();
  await expect(page.getByText('adresine onay maili gönderildi', { exact: false })).toHaveCount(0);
  await expect(page.getByText('onay maili gönderilemedi', { exact: false })).toHaveCount(0);
});

test('favourites-only selection is explained', async ({ page }) => {
  await loginAs(page);
  await mockApi(page);
  await page.goto('/');
  const panel = await openSubscriptions(page);
  await panel.getByRole('button', { name: 'Yeni Abonelik' }).click();
  const form = panel.getByRole('form', { name: 'Abonelik formu' });
  await form.getByLabel('Favoriler').check();
  await expect(form.getByText('Yalnızca Favoriler işaretliyse sadece favori haberler', { exact: false })).toBeVisible();
});

test('build errors show up in the history with their own label', async ({ page }) => {
  await loginAs(page);
  await mockApi(page, {
    newsletterSubscriptions: [makeNewsletterSubscription({ id: 11 })],
    newsletterDeliveries: new Map([[11, [makeNewsletterDelivery({
      status: 'skipped_build_error', article_count: 0, error: 'OpenAI unavailable',
    })]]]),
  });
  await page.goto('/');
  const panel = await openSubscriptions(page);
  await panel.getByRole('button', { name: 'Geçmiş' }).click();
  await expect(panel.getByText('Bülten hazırlanamadı')).toBeVisible();
  await expect(panel.getByText('OpenAI unavailable')).toBeVisible();
});

test('warns when mail sending is not configured', async ({ page }) => {
  await loginAs(page);
  await mockApi(page, { newsletterStatus: { email_configured: false } });
  await page.goto('/');
  await openSubscriptions(page);
  await expect(page.getByRole('alert')).toContainText('E-posta gönderimi yapılandırılmamış');
});

test('disabled and unconfirmed subscriptions explain themselves', async ({ page }) => {
  await loginAs(page);
  await mockApi(page, {
    newsletterSubscriptions: [
      makeNewsletterSubscription({ email: 'broken@example.com', status: 'disabled', consecutive_failures: 3 }),
      makeNewsletterSubscription({ email: 'waiting@example.com', status: 'pending', confirm_sent_at: null }),
    ],
  });
  await page.goto('/');
  const panel = await openSubscriptions(page);
  await expect(panel.getByText('Üst üste 3 gönderim başarısız olduğu için durduruldu.', { exact: false })).toBeVisible();
  await expect(panel.getByText('Onay maili gönderilemedi.', { exact: false })).toBeVisible();
});

test('only admins see the Tüm Aboneler table', async ({ page }) => {
  const others = [makeNewsletterSubscription({ email: 'x@example.com', owner_email: 'someone@example.com' })];

  await loginAs(page);
  await mockApi(page, { newsletterSubscriptions: others });
  await page.goto('/');
  await openSubscriptions(page);
  await expect(page.getByRole('heading', { name: 'Tüm Aboneler' })).toHaveCount(0);
});

test('admin sees every subscription with its owner', async ({ page }) => {
  await loginAs(page, ADMIN_USER);
  await mockApi(page, {
    newsletterOwnEmail: ADMIN_USER.email,
    newsletterSubscriptions: [makeNewsletterSubscription({ email: 'x@example.com', owner_email: 'someone@example.com' })],
  });
  await page.goto('/');
  await openSubscriptions(page);
  const table = page.getByRole('region', { name: 'Tüm Aboneler' });
  await expect(table.getByRole('heading', { name: 'Tüm Aboneler' })).toBeVisible();
  await expect(table.getByRole('cell', { name: 'someone@example.com' })).toBeVisible();
  await expect(table.getByRole('cell', { name: 'x@example.com', exact: true })).toBeVisible();
  await expect(table.getByText('$1.25')).toBeVisible();
});
