import { test, expect } from '@playwright/test';
import { loginAs } from './helpers/auth';
import { mockApi, makeArticle, makeTopic } from './helpers/mockApi';

const TOPIC_POLITICS = makeTopic({ id: 201, name: 'Politics' });
const TOPIC_SPORTS = makeTopic({ id: 202, name: 'Sports' });

function fixtures() {
  return [
    makeArticle({ title: 'Politics Piece', is_read: false, topics: [TOPIC_POLITICS] }),
    makeArticle({ title: 'Sports Piece', is_read: false, topics: [TOPIC_SPORTS] }),
  ];
}

test('selecting a topic filters the list', async ({ page }) => {
  await loginAs(page);
  await mockApi(page, { topics: [TOPIC_POLITICS, TOPIC_SPORTS], articles: fixtures() });
  await page.goto('/');

  const req = page.waitForRequest((r) => (new URL(r.url()).searchParams.get('topic_ids') ?? '').includes(String(TOPIC_POLITICS.id)));
  await page.getByLabel('Politics').click();
  await req;

  await expect(page.getByText('Politics Piece')).toBeVisible();
  await expect(page.getByText('Sports Piece')).not.toBeVisible();
});

test('selecting multiple topics sends comma-separated topic_ids', async ({ page }) => {
  await loginAs(page);
  await mockApi(page, { topics: [TOPIC_POLITICS, TOPIC_SPORTS], articles: fixtures() });
  await page.goto('/');

  await page.getByLabel('Politics').click();
  const req = page.waitForRequest((r) => {
    const ids = new URL(r.url()).searchParams.get('topic_ids') ?? '';
    return ids.includes(String(TOPIC_POLITICS.id)) && ids.includes(String(TOPIC_SPORTS.id));
  });
  await page.getByLabel('Sports').click();
  await req;

  await expect(page.getByText('Politics Piece')).toBeVisible();
  await expect(page.getByText('Sports Piece')).toBeVisible();
});

test('unread count badge per topic matches fixture', async ({ page }) => {
  await loginAs(page);
  await mockApi(page, {
    topics: [TOPIC_POLITICS, TOPIC_SPORTS],
    articles: [
      makeArticle({ title: 'Politics Piece', is_read: false, topics: [TOPIC_POLITICS] }),
      makeArticle({ title: 'Politics Old', is_read: true, topics: [TOPIC_POLITICS] }),
    ],
  });
  await page.goto('/');

  const politicsRow = page.locator('.topic-item').filter({ hasText: 'Politics' });
  await expect(politicsRow).toContainText('1');
});

test('collapsing the accordion hides the checkboxes', async ({ page }) => {
  await loginAs(page);
  await mockApi(page, { topics: [TOPIC_POLITICS, TOPIC_SPORTS], articles: fixtures() });
  await page.goto('/');

  await expect(page.getByLabel('Politics')).toBeVisible();

  await page.getByRole('button', { name: 'Kategoriler' }).click();
  await expect(page.getByLabel('Politics')).not.toBeVisible();

  await page.getByRole('button', { name: 'Kategoriler' }).click();
  await expect(page.getByLabel('Politics')).toBeVisible();
});
