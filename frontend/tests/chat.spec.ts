import { test, expect, type Page } from '@playwright/test';
import { loginAs } from './helpers/auth';
import { makeArticle, mockApi } from './helpers/mockApi';
import { mockChat, reportRun, step, type ScriptedTurn } from './helpers/mockChat';

const ARTICLE = makeArticle({
  id: 7,
  title: 'Haben sich Storm-Shadow-Raketen bewährt?',
  cleaned_content: 'Als die Ukraine erstmals Storm-Shadow-Marschflugkörper erhielt…',
});

async function openAssistant(page: Page) {
  await page.goto('/');
  await page.getByRole('button', { name: 'Asistan', exact: true }).click();
}

async function ask(page: Page, question: string) {
  await page.getByRole('textbox', { name: 'Mesaj' }).fill(question);
  await page.getByRole('button', { name: 'Gönder' }).click();
}

test('a question runs through plan, tools and chart to a report that links its sources', async ({ page }) => {
  await loginAs(page);
  await mockApi(page, { articles: [ARTICLE] });
  const chat = await mockChat(page, [reportRun('## Sonuç\nSon 7 günde **6 yüksek** önemli haber var [#7].\n- Orta: 10\n- Düşük: 4')]);
  await openAssistant(page);

  await expect(page.getByLabel('Açık araçlar').getByText('Vektör arama')).toBeVisible();
  await expect(page.getByLabel('Açık araçlar').getByText('Code interpreter')).toHaveCount(0);

  await ask(page, 'Son 7 günün önem dağılımı nedir?');

  await expect(page.getByText('Son 7 günün önem dağılımı', { exact: false }).first()).toBeVisible();
  const plan = page.getByRole('region', { name: 'Analiz planı' });
  await expect(plan.getByText('Önem dağılımını say')).toBeVisible();
  await expect(plan.getByText('6 yüksek, 10 orta, 4 düşük.')).toBeVisible();
  await expect(plan.getByText('Tamamlandı')).toHaveCount(2);

  await plan.getByText('Araç çağrıları (1)').first().click();
  await expect(plan.getByText('SELECT priority, count(*) FROM chat_articles GROUP BY 1 LIMIT 200')).toBeVisible();

  await expect(page.getByRole('img', { name: 'Önem dağılımı' })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Sonuç' })).toBeVisible();
  await expect(page.getByText('6 yüksek', { exact: true })).toBeVisible();

  // The conversation is listed under the question it started with.
  await expect(page.getByRole('button', { name: /^Son 7 günün önem dağılımı nedir\?/ })).toBeVisible();
  expect(chat.sent).toEqual([{ content: 'Son 7 günün önem dağılımı nedir?', action: 'message' }]);

  // A cited article opens in the reader.
  await page.getByRole('button', { name: '#7' }).click();
  await expect(page.getByRole('heading', { name: ARTICLE.title })).toBeVisible();
  await expect(page.getByText('Als die Ukraine erstmals')).toBeVisible();
});

test('the chart can be read as a table', async ({ page }) => {
  await loginAs(page);
  await mockApi(page, { articles: [] });
  await mockChat(page, [reportRun('Bitti.')]);
  await openAssistant(page);
  await ask(page, 'Dağılım?');

  await page.getByRole('button', { name: 'Tablo' }).click();
  const table = page.getByRole('table');
  await expect(table.getByRole('row', { name: 'Orta 10' })).toBeVisible();
  await expect(page.getByRole('img', { name: 'Önem dağılımı' })).toHaveCount(0);
});

test('a clarifying question is answered with the offered options and the run continues', async ({ page }) => {
  const clarify: ScriptedTurn = {
    status: 'awaiting_clarification',
    events: [
      { type: 'phase', phase: 'understanding', label: 'Soruyu anlıyorum' },
      { type: 'intent', restatement: 'Genel durum', time_range: null, assumptions: [] },
      { type: 'clarification', restatement: 'Genel durumu soruyorsunuz.', questions: [{ question: 'Hangi dönem?', options: ['Son 7 gün', 'Son 30 gün'] }] },
    ],
  };
  await loginAs(page);
  await mockApi(page, { articles: [] });
  const chat = await mockChat(page, [clarify, reportRun('Son 7 günde sakin bir hafta.')]);
  await openAssistant(page);

  await ask(page, 'Durum nasıl?');

  const card = page.getByRole('region', { name: 'Netleştirme soruları' });
  await expect(card.getByText('Hangi dönem?')).toBeVisible();
  await expect(page.getByRole('button', { name: /^Durum nasıl\?.*Cevabınızı bekliyor/ })).toBeVisible();
  await expect(card.getByRole('button', { name: 'Cevapla' })).toBeDisabled();

  await card.getByRole('button', { name: 'Son 7 gün' }).click();
  await card.getByRole('button', { name: 'Cevapla' }).click();

  await expect(page.getByText('Son 7 günde sakin bir hafta.')).toBeVisible();
  expect(chat.sent[1]).toEqual({ content: 'Son 7 gün', action: 'message' });
  // Answered: the old card is no longer interactive.
  await expect(page.getByRole('button', { name: 'Cevapla' })).toHaveCount(0);
});

test('a plan waiting for approval starts on "Planı başlat" and can be revised with a note', async ({ page }) => {
  const waiting: ScriptedTurn = {
    status: 'awaiting_plan_approval',
    events: [
      { type: 'phase', phase: 'planning', label: 'Plan çıkarıyorum' },
      { type: 'plan', steps: [step(1, 'Konuları say', 'sql')], requires_approval: true },
      { type: 'plan_approval', steps: [step(1, 'Konuları say', 'sql')] },
    ],
  };
  const revised: ScriptedTurn = {
    status: 'awaiting_plan_approval',
    events: [
      { type: 'plan', steps: [step(1, 'Yalnızca yüksek önemli konuları say', 'sql')], requires_approval: true },
      { type: 'plan_approval', steps: [step(1, 'Yalnızca yüksek önemli konuları say', 'sql')] },
    ],
  };
  const started: ScriptedTurn = {
    status: 'idle',
    events: [
      { type: 'step_started', step_id: 1, goal: 'Yalnızca yüksek önemli konuları say', tool: 'sql' },
      { type: 'step_result', step_id: 1, status: 'done', finding: '3 konu.' },
      { type: 'token', text: 'Üç konu öne çıkıyor.' },
    ],
  };
  await loginAs(page);
  await mockApi(page, { articles: [] });
  const chat = await mockChat(page, [waiting, revised, started]);
  await openAssistant(page);

  await ask(page, 'Konulara göre dağılım?');
  const plan = page.getByRole('region', { name: 'Analiz planı' });
  await expect(plan.getByText('Konuları say')).toBeVisible();

  await plan.getByLabel('Plan değişiklik notu').fill('Sadece yüksek önemli');
  await plan.getByRole('button', { name: 'Planı değiştir' }).click();
  await expect(page.getByText('Yalnızca yüksek önemli konuları say').last()).toBeVisible();
  expect(chat.sent[1]).toEqual({ content: 'Sadece yüksek önemli', action: 'approve_plan' });

  await page.getByRole('button', { name: 'Planı başlat' }).click();
  await expect(page.getByText('Üç konu öne çıkıyor.')).toBeVisible();
  expect(chat.sent[2]).toEqual({ content: '', action: 'approve_plan' });
  await expect(page.getByRole('button', { name: 'Planı başlat' })).toHaveCount(0);
});

test('a refused request shows the server message', async ({ page }) => {
  await loginAs(page);
  await mockApi(page, { articles: [] });
  await mockChat(page, [{ events: [], error: { status: 429, detail: 'Çok fazla analiz isteği; biraz sonra tekrar deneyin' } }]);
  await openAssistant(page);

  await ask(page, 'Soru');

  await expect(page.getByRole('alert')).toContainText('Çok fazla analiz isteği');
});

test('a stored conversation reopens with its plan and report, and can be deleted', async ({ page }) => {
  const run = reportRun('Kayıtlı rapor metni.');
  await loginAs(page);
  await mockApi(page, { articles: [] });
  const chat = await mockChat(page, [], {
    conversations: [{
      id: 5, title: 'Eski analiz', status: 'idle', created_at: null, updated_at: null, pending: null,
      messages: [
        { id: 1, role: 'user', content: 'Eski soru', events: [], cost: 0, created_at: null },
        { id: 2, role: 'assistant', content: 'Kayıtlı rapor metni.', events: run.events.filter((e) => e.type !== 'token'), cost: 0.0042, created_at: null },
      ],
    }],
  });
  await openAssistant(page);

  await page.getByRole('button', { name: /^Eski analiz/ }).click();
  await expect(page.getByText('Eski soru')).toBeVisible();
  await expect(page.getByText('Kayıtlı rapor metni.')).toBeVisible();
  await expect(page.getByRole('region', { name: 'Analiz planı' }).getByText('Önem dağılımını say')).toBeVisible();
  await expect(page.getByText('Maliyet: $0.0042')).toBeVisible();

  await page.getByRole('button', { name: '“Eski analiz” sohbetini sil' }).click();
  await page.getByRole('dialog').getByRole('button', { name: 'Sil' }).click();
  await expect(page.getByText('Henüz sohbet yok.')).toBeVisible();
  expect(chat.conversations).toHaveLength(0);
});

test('an example question fills and focuses the composer; Enter sends it', async ({ page }) => {
  await loginAs(page);
  await mockApi(page, { articles: [] });
  const chat = await mockChat(page, [reportRun('Hafta özeti.')]);
  await openAssistant(page);

  await expect(page.getByText('Enter ile gönderin · Shift+Enter yeni satır')).toBeVisible();
  const example = 'Bu hafta öne çıkan yüksek önemli gelişmeleri özetle';
  await page.getByRole('group', { name: 'Örnek sorular' }).getByRole('button', { name: example }).click();
  const input = page.getByRole('textbox', { name: 'Mesaj' });
  await expect(input).toHaveValue(example);
  await expect(input).toBeFocused();

  // Before the first message the composer sits on the welcome screen with the examples.
  await expect(page.getByRole('heading', { name: /^(Günaydın|İyi günler|İyi akşamlar)$/ })).toBeVisible();

  await input.press('Enter');
  await expect(page.getByText('Hafta özeti.')).toBeVisible();
  expect(chat.sent).toEqual([{ content: example, action: 'message' }]);
  // Once the chat starts the welcome screen is gone and the composer is docked under the thread.
  await expect(page.getByRole('group', { name: 'Örnek sorular' })).toHaveCount(0);
  const docked = page.getByRole('textbox', { name: 'Mesaj' });
  await expect(docked).toHaveValue('');
  await expect(docked).toBeFocused();
  const thread = await page.getByText('Hafta özeti.').boundingBox();
  const box = await docked.boundingBox();
  expect(box!.y).toBeGreaterThan(thread!.y);

  // "Yeni sohbet" brings the welcome screen back.
  await page.getByRole('button', { name: 'Yeni sohbet' }).click();
  await expect(page.getByRole('group', { name: 'Örnek sorular' })).toBeVisible();
});

test('a failed request can be retried with the same message', async ({ page }) => {
  await loginAs(page);
  await mockApi(page, { articles: [] });
  const chat = await mockChat(page, [
    { events: [], error: { status: 503, detail: 'Asistan şu an yanıt veremiyor' } },
    reportRun('İkinci denemede rapor.'),
  ]);
  await openAssistant(page);

  await ask(page, 'Önem dağılımı?');
  await expect(page.getByRole('alert')).toContainText('Asistan şu an yanıt veremiyor');

  await page.getByRole('button', { name: 'Tekrar dene' }).click();
  await expect(page.getByText('İkinci denemede rapor.')).toBeVisible();
  await expect(page.getByRole('alert')).toHaveCount(0);
  expect(chat.sent).toEqual([
    { content: 'Önem dağılımı?', action: 'message' },
    { content: 'Önem dağılımı?', action: 'message' },
  ]);
});

test('a finished run shows plan progress and its report can be copied', async ({ page, context }) => {
  await context.grantPermissions(['clipboard-read', 'clipboard-write']);
  await loginAs(page);
  await mockApi(page, { articles: [] });
  await mockChat(page, [reportRun('Kopyalanacak rapor.')]);
  await openAssistant(page);

  await ask(page, 'Dağılım?');
  await expect(page.getByText('Kopyalanacak rapor.')).toBeVisible();
  await expect(page.getByRole('region', { name: 'Analiz planı' }).getByText('2/2 adım')).toBeVisible();

  await page.getByRole('button', { name: 'Raporu kopyala' }).click();
  await expect(page.getByRole('button', { name: 'Kopyalandı' })).toBeVisible();
  expect(await page.evaluate(() => navigator.clipboard.readText())).toBe('Kopyalanacak rapor.');
});

test('a running analysis keeps going while another tab is open', async ({ page }) => {
  await loginAs(page);
  await mockApi(page, { articles: [] });
  await mockChat(page, [reportRun('Sekme değişse de bitti.')]);
  // Hold the stream open long enough to leave and come back while it runs.
  await page.route('**/api/chat/conversations/*/messages', async (route) => {
    await new Promise((resolve) => setTimeout(resolve, 1500));
    try { await route.fallback(); } catch { /* aborted by the page */ }
  });
  const aborted: string[] = [];
  page.on('requestfailed', (request) => {
    if (request.url().includes('/messages')) aborted.push(request.failure()?.errorText ?? 'failed');
  });
  await openAssistant(page);

  await ask(page, 'Uzun analiz');
  await page.getByRole('button', { name: 'Haberler', exact: true }).click();
  await page.getByRole('button', { name: 'Asistan', exact: true }).click();

  await expect(page.getByText('Sekme değişse de bitti.')).toBeVisible();
  await expect(page.getByText('Analiz durduruldu.')).toHaveCount(0);
  expect(aborted).toEqual([]);
});
