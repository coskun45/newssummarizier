import { test, expect, type Page } from '@playwright/test';
import { loginAs, ADMIN_USER } from './helpers/auth';
import { mockApi, makeFeed, makeGroup, makeTopic, makeArticle } from './helpers/mockApi';

const EUROPE = makeGroup({ id: 501, kind: 'feed', name: 'Avrupa' });
const ECONOMY = makeGroup({ id: 502, kind: 'topic', name: 'Ekonomi' });
const FEED_DE = makeFeed({ id: 511, title: 'DW Almanca', group_id: EUROPE.id });
const FEED_FR = makeFeed({ id: 512, title: 'France 24', group_id: EUROPE.id });
const FEED_US = makeFeed({ id: 513, title: 'NPR', group_id: null });
const TOPIC_MARKETS = makeTopic({ id: 521, name: 'Piyasalar', group_id: ECONOMY.id });
const TOPIC_BANKS = makeTopic({ id: 522, name: 'Bankacılık', group_id: ECONOMY.id });
const TOPIC_SPORT = makeTopic({ id: 523, name: 'Spor', group_id: null });

async function openNews(page: Page) {
  await page.goto('/');
  await page.getByRole('button', { name: 'Haberler', exact: true }).click();
}

async function openSettingsTab(page: Page, tab: 'RSS Beslemeleri' | 'Kategoriler') {
  await page.getByRole('button', { name: 'Ayarlar' }).click();
  await page.getByRole('button', { name: tab }).click();
  return page.locator('.settings-category');
}

test('sidebar lists feeds under their group, ungrouped ones under "Diğer"', async ({ page }) => {
  await loginAs(page);
  await mockApi(page, { feeds: [FEED_DE, FEED_FR, FEED_US], groups: [EUROPE], articles: [] });
  await openNews(page);

  const europeToggle = page.getByRole('button', { name: /Avrupa/ });
  await expect(europeToggle).toHaveAttribute('aria-expanded', 'true');
  await expect(page.getByRole('button', { name: /Diğer/ }).first()).toBeVisible();
  await expect(page.getByLabel('DW Almanca')).toBeVisible();

  // Collapsing a group hides its feeds but keeps the others
  await europeToggle.click();
  await expect(page.getByLabel('DW Almanca')).not.toBeVisible();
  await expect(page.getByLabel('NPR')).toBeVisible();
});

test('the group checkbox selects all its feeds at once', async ({ page }) => {
  await loginAs(page);
  await mockApi(page, {
    feeds: [FEED_DE, FEED_FR, FEED_US],
    groups: [EUROPE],
    articles: [
      makeArticle({ title: 'Berlin haberi', is_read: false, feedId: FEED_DE.id }),
      makeArticle({ title: 'Washington haberi', is_read: false, feedId: FEED_US.id }),
    ],
  });
  await openNews(page);

  const req = page.waitForRequest((r) => {
    const ids = new URL(r.url()).searchParams.get('feed_ids')?.split(',') ?? [];
    return ids.includes(String(FEED_DE.id)) && ids.includes(String(FEED_FR.id)) && !ids.includes(String(FEED_US.id));
  });
  await page.getByLabel('Avrupa grubunun tümü').check();
  await req;

  await expect(page.getByLabel('DW Almanca')).toBeChecked();
  await expect(page.getByLabel('France 24')).toBeChecked();
  await expect(page.getByText('Berlin haberi')).toBeVisible();
  await expect(page.getByText('Washington haberi')).not.toBeVisible();

  // Unticking one feed leaves the group partially selected; ticking the group again clears it
  await page.getByLabel('France 24').uncheck();
  await expect(page.getByLabel('Avrupa grubunun tümü')).not.toBeChecked();
  await page.getByLabel('Avrupa grubunun tümü').click();
  await expect(page.getByLabel('France 24')).toBeChecked();
  await page.getByLabel('Avrupa grubunun tümü').click();
  await expect(page.getByLabel('Tüm Beslemeler')).toBeChecked();
});

test('categories are grouped too and the group checkbox filters by all its topics', async ({ page }) => {
  await loginAs(page);
  await mockApi(page, {
    topics: [TOPIC_MARKETS, TOPIC_BANKS, TOPIC_SPORT],
    groups: [ECONOMY],
    articles: [makeArticle({ title: 'Borsa haberi', is_read: false, topics: [TOPIC_MARKETS] })],
  });
  await openNews(page);

  await expect(page.getByLabel('Spor')).toBeVisible();
  const req = page.waitForRequest((r) => {
    const ids = new URL(r.url()).searchParams.get('topic_ids')?.split(',') ?? [];
    return ids.includes(String(TOPIC_MARKETS.id)) && ids.includes(String(TOPIC_BANKS.id));
  });
  await page.getByLabel('Ekonomi grubunun tümü').check();
  await req;
  await expect(page.getByLabel('Piyasalar')).toBeChecked();
  await expect(page.getByLabel('Spor')).not.toBeChecked();
});

test('without any groups the sidebar stays a flat list', async ({ page }) => {
  await loginAs(page);
  await mockApi(page, { feeds: [FEED_US], groups: [], articles: [] });
  await openNews(page);

  await expect(page.getByLabel('NPR')).toBeVisible();
  await expect(page.getByRole('button', { name: /Diğer/ })).toHaveCount(0);
});

test('admin creates, renames and deletes a feed group in Ayarlar', async ({ page }) => {
  await loginAs(page, ADMIN_USER);
  const state = await mockApi(page, { feeds: [FEED_DE], groups: [EUROPE], articles: [] });
  await page.goto('/');
  const section = (await openSettingsTab(page, 'RSS Beslemeleri')).getByRole('region', { name: 'Gruplar' });

  const createReq = page.waitForRequest((r) => r.url().endsWith('/api/groups/') && r.method() === 'POST');
  await section.getByLabel('Yeni grup adı').fill('Asya');
  await section.getByRole('button', { name: 'Grup ekle' }).click();
  expect((await createReq).postDataJSON()).toEqual({ kind: 'feed', name: 'Asya' });
  await expect(section.getByText('Asya')).toBeVisible();

  const asia = state.groups.find((g) => g.name === 'Asya')!;
  const asiaRow = section.locator('.user-list-item', { hasText: 'Asya' });
  await asiaRow.getByTitle('Grubu yeniden adlandır').click();
  await section.getByLabel('Grup adı', { exact: true }).fill('Uzak Doğu');
  const renameReq = page.waitForRequest((r) => r.url().endsWith(`/api/groups/${asia.id}`) && r.method() === 'PUT');
  await section.getByTitle('Kaydet').click();
  expect((await renameReq).postDataJSON()).toEqual({ name: 'Uzak Doğu' });
  await expect(section.getByText('Uzak Doğu')).toBeVisible();

  page.once('dialog', (d) => d.accept());
  const europeRow = section.locator('.user-list-item', { hasText: 'Avrupa' });
  const deleteReq = page.waitForRequest((r) => r.url().endsWith(`/api/groups/${EUROPE.id}`) && r.method() === 'DELETE');
  await europeRow.getByTitle('Grubu sil').click();
  await deleteReq;
  await expect(section.getByText('Avrupa')).not.toBeVisible();
  expect(state.feeds[0].group_id).toBeNull();
});

test('regular users see the groups but not the group management controls', async ({ page }) => {
  await loginAs(page);
  await mockApi(page, { feeds: [FEED_DE], groups: [EUROPE], articles: [] });
  await page.goto('/');
  const section = (await openSettingsTab(page, 'RSS Beslemeleri')).getByRole('region', { name: 'Gruplar' });

  await expect(section.getByText('Avrupa')).toBeVisible();
  await expect(section.getByRole('button', { name: 'Grup ekle' })).toHaveCount(0);
  await expect(section.getByTitle('Grubu sil')).toHaveCount(0);
});

test('adding a feed with a new group creates the group and sends its group_id', async ({ page }) => {
  await loginAs(page, ADMIN_USER);
  const state = await mockApi(page, { feeds: [], groups: [], articles: [] });
  await page.goto('/');
  const settings = await openSettingsTab(page, 'RSS Beslemeleri');

  await settings.getByRole('button', { name: 'Yeni besleme ekle' }).click();
  const form = settings.locator('.add-topic-form');
  await form.getByPlaceholder(/RSS URL/).fill('https://example.com/asia.xml');
  await form.getByLabel('Besleme adı').fill('Asia Feed');
  await form.getByLabel('Grup', { exact: true }).selectOption('__new__');
  await form.getByLabel('Yeni grup adı').fill('Asya');
  await form.getByRole('button', { name: 'Grubu oluştur' }).click();
  await expect(form.getByLabel('Grup', { exact: true })).toHaveValue(String(state.groups[0]?.id ?? ''));

  await form.getByRole('button', { name: 'Bağlantıyı Test Et' }).click();
  await expect(form.getByText('Bağlantı başarılı')).toBeVisible();
  const req = page.waitForRequest((r) => r.url().endsWith('/api/feeds/') && r.method() === 'POST');
  await form.getByRole('button', { name: 'Ekle' }).click();
  const asia = state.groups.find((g) => g.name === 'Asya')!;
  expect((await req).postDataJSON()).toMatchObject({ title: 'Asia Feed', group_id: asia.id });
});

test('editing a topic moves it into a group via PUT group_id', async ({ page }) => {
  await loginAs(page, ADMIN_USER);
  await mockApi(page, { topics: [TOPIC_SPORT], groups: [ECONOMY], articles: [] });
  await page.goto('/');
  const settings = await openSettingsTab(page, 'Kategoriler');

  await settings.locator('.topic-item').first().getByTitle('Düzenle').click();
  await settings.getByLabel('Grup', { exact: true }).selectOption(String(ECONOMY.id));
  const req = page.waitForRequest((r) => r.url().endsWith(`/api/topics/${TOPIC_SPORT.id}`) && r.method() === 'PUT');
  await settings.locator('.save-edit-button').click();
  expect((await req).postDataJSON()).toMatchObject({ group_id: ECONOMY.id });
  await expect(settings.locator('.topic-item', { hasText: 'Spor' }).getByText('Ekonomi')).toBeVisible();
});

test('an opened but not created new group blocks saving the topic until created or cancelled', async ({ page }) => {
  await loginAs(page, ADMIN_USER);
  await mockApi(page, { topics: [], groups: [], articles: [] });
  await page.goto('/');
  const settings = await openSettingsTab(page, 'Kategoriler');

  await settings.getByRole('button', { name: 'Yeni kategori ekle' }).click();
  const form = settings.locator('.add-topic-form');
  await form.getByPlaceholder(/Kategori adı/).fill('Borsa');
  const createTopic = form.getByRole('button', { name: 'Oluştur', exact: true });
  await expect(createTopic).toBeEnabled();

  await form.getByLabel('Grup', { exact: true }).selectOption('__new__');
  await form.getByLabel('Yeni grup adı').fill('Ekonomi');
  await expect(createTopic).toBeDisabled();

  await form.getByRole('button', { name: 'Vazgeç' }).click();
  await expect(createTopic).toBeEnabled();
  await expect(form.getByLabel('Grup', { exact: true })).toHaveValue('');
});
