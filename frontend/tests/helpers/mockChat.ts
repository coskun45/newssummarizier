import type { Page, Route } from '@playwright/test';
import type {
  ChatConversation,
  ChatConversationStatus,
  ChatEvent,
  ChatPlanStep,
  ChatSendRequest,
  ChatToolInfo,
  EmbeddingStatus,
} from '../../src/types';
import type { MockState } from './mockApi';

/** What the mocked server streams for one POST .../messages, and how the turn is stored. */
export interface ScriptedTurn {
  events: ChatEvent[];
  /** Conversation status after the turn (the `done` event's status). */
  status?: ChatConversationStatus;
  /** HTTP error instead of a stream (e.g. 409 with a Turkish `detail`). */
  error?: { status: number; detail: string };
}

export interface MockChatState {
  conversations: ChatConversation[];
  /** Every message body sent, in order. */
  sent: ChatSendRequest[];
  tools: ChatToolInfo[];
  embedding: EmbeddingStatus;
  backfillStarted: number;
}

export function makeTools(overrides: Partial<Record<string, Partial<ChatToolInfo>>> = {}): ChatToolInfo[] {
  const base: ChatToolInfo[] = [
    { name: 'time', label: 'Zaman tespiti', description: 'Zaman ifadelerini tarih aralığına çevirir.', data_tool: false, available: true, unavailable_reason: null, enabled: true, active: true },
    { name: 'sql', label: 'Veritabanı (SQL)', description: 'Salt-okunur SQL.', data_tool: true, available: true, unavailable_reason: null, enabled: true, active: true },
    { name: 'semantic_search', label: 'Vektör arama', description: 'Tam metinde anlamca arar.', data_tool: true, available: true, unavailable_reason: null, enabled: true, active: true },
    { name: 'python', label: 'Code interpreter', description: 'Python analizi.', data_tool: false, available: false, unavailable_reason: 'Henüz kurulmadı — Python sandbox\'ı sonraki aşamada gelecek.', enabled: false, active: false },
    { name: 'web_search', label: 'Web arama', description: 'İnternette arar.', data_tool: false, available: false, unavailable_reason: 'Henüz kurulmadı — sonraki aşamada gelecek.', enabled: false, active: false },
    { name: 'chart', label: 'Grafik', description: 'Grafik çizer.', data_tool: false, available: true, unavailable_reason: null, enabled: true, active: true },
  ];
  return base.map((tool) => ({ ...tool, ...overrides[tool.name] }));
}

export function makeEmbeddingStatus(overrides: Partial<EmbeddingStatus> = {}): EmbeddingStatus {
  return {
    available: true,
    unavailable_reason: null,
    model: 'text-embedding-3-large',
    dimensions: 1536,
    summarized: 44,
    embedded: 40,
    chunks: 200,
    job: { status: 'idle', total: 0, done: 0, failed: 0, cost: 0, error: null },
    ...overrides,
  };
}

export function step(id: number, goal: string, tool: string, status: ChatPlanStep['status'] = 'pending', finding = ''): ChatPlanStep {
  return { id, goal, tool, status, finding };
}

/** A complete successful run: understand → plan → SQL + chart → report. */
export function reportRun(report: string): ScriptedTurn {
  const plan = [step(1, 'Önem dağılımını say', 'sql'), step(2, 'Grafik çiz', 'chart')];
  return {
    status: 'idle',
    events: [
      { type: 'phase', phase: 'understanding', label: 'Soruyu anlıyorum' },
      { type: 'intent', restatement: 'Son 7 günün önem dağılımı', time_range: { from: '2026-10-22T00:00:00+02:00', to: '2026-10-28T15:00:00+01:00', label: 'Son 7 gün' }, assumptions: [] },
      { type: 'phase', phase: 'planning', label: 'Plan çıkarıyorum' },
      { type: 'plan', steps: plan, requires_approval: false },
      { type: 'phase', phase: 'executing', label: 'Analiz ediyorum', step: 1, total: 2 },
      { type: 'step_started', step_id: 1, goal: plan[0].goal, tool: 'sql' },
      { type: 'tool_call', step_id: 1, call_id: 'c1', name: 'run_sql', arguments: JSON.stringify({ query: 'SELECT priority, count(*) FROM chat_articles GROUP BY 1' }) },
      { type: 'tool_result', step_id: 1, call_id: 'c1', tool: 'sql', ok: true, summary: '3 satır', sql: 'SELECT priority, count(*) FROM chat_articles GROUP BY 1 LIMIT 200', artifact_id: 'a1' },
      { type: 'step_result', step_id: 1, status: 'done', finding: '6 yüksek, 10 orta, 4 düşük.' },
      { type: 'step_started', step_id: 2, goal: plan[1].goal, tool: 'chart' },
      { type: 'tool_call', step_id: 2, call_id: 'c2', name: 'render_chart', arguments: JSON.stringify({ title: 'Önem dağılımı' }) },
      { type: 'chart', step_id: 2, chart: { id: 'a2', kind: 'chart', type: 'bar', title: 'Önem dağılımı', x: ['Yüksek', 'Orta', 'Düşük'], series: [{ name: 'Haber', values: [6, 10, 4] }] } },
      { type: 'tool_result', step_id: 2, call_id: 'c2', tool: 'chart', ok: true, summary: 'Grafik: Önem dağılımı', sql: null, artifact_id: 'a2' },
      { type: 'step_result', step_id: 2, status: 'done', finding: 'Grafik çizildi.' },
      { type: 'phase', phase: 'reporting', label: 'Raporu yazıyorum' },
      ...report.match(/.{1,12}/gs)!.map((text): ChatEvent => ({ type: 'token', text })),
    ],
  };
}

/**
 * An in-memory /api/chat backend. Register it AFTER mockApi(): Playwright runs the most recently
 * registered matching route first. Each POST .../messages consumes the next scripted turn.
 */
export async function mockChat(
  page: Page,
  turns: ScriptedTurn[],
  options: {
    conversations?: ChatConversation[];
    tools?: ChatToolInfo[];
    embedding?: EmbeddingStatus;
    /** mockApi's state: GET /tools then follows the saved `chat_enabled_tools`, like the backend. */
    apiState?: MockState;
  } = {},
): Promise<MockChatState> {
  const state: MockChatState = {
    conversations: options.conversations ?? [],
    sent: [],
    tools: options.tools ?? makeTools(),
    embedding: options.embedding ?? makeEmbeddingStatus(),
    backfillStarted: 0,
  };
  let nextId = 100;
  let messageId = 1000;
  const queue = [...turns];
  const summary = (c: ChatConversation) => ({ id: c.id, title: c.title, status: c.status, created_at: c.created_at, updated_at: c.updated_at });

  await page.route('**/api/chat/**', async (route: Route) => {
    const request = route.request();
    const method = request.method();
    const path = new URL(request.url()).pathname.replace(/^.*\/api\/chat/, '');
    const json = (data: unknown, status = 200) => route.fulfill({ status, json: data as object });

    if (method === 'GET' && path === '/tools') {
      const saved = options.apiState?.settings.chat_enabled_tools;
      if (saved === undefined) return json(state.tools);
      const on = new Set(saved.split(','));
      return json(state.tools.map((t) => ({ ...t, enabled: on.has(t.name), active: t.available && on.has(t.name) })));
    }
    if (method === 'GET' && path === '/embeddings/status') return json(state.embedding);
    if (method === 'POST' && path === '/embeddings/backfill') {
      state.backfillStarted += 1;
      const missing = state.embedding.summarized - state.embedding.embedded;
      state.embedding = {
        ...state.embedding,
        embedded: state.embedding.summarized,
        job: { status: 'done', total: missing, done: missing, failed: 0, cost: 0.0012, error: null },
      };
      return json(state.embedding);
    }
    if (method === 'GET' && path === '/conversations') return json(state.conversations.map(summary));
    if (method === 'POST' && path === '/conversations') {
      const now = new Date().toISOString();
      const conversation: ChatConversation = { id: nextId++, title: 'Yeni sohbet', status: 'idle', created_at: now, updated_at: now, messages: [], pending: null };
      state.conversations.unshift(conversation);
      return json(conversation, 201);
    }
    const match = path.match(/^\/conversations\/(\d+)(\/messages)?$/);
    const conversation = match ? state.conversations.find((c) => c.id === Number(match[1])) : undefined;
    if (match && !conversation) return json({ detail: 'Sohbet bulunamadı' }, 404);
    if (conversation && !match![2]) {
      if (method === 'GET') return json(conversation);
      if (method === 'DELETE') {
        state.conversations = state.conversations.filter((c) => c !== conversation);
        return route.fulfill({ status: 204 });
      }
    }
    if (conversation && match![2] && method === 'POST') {
      const body = request.postDataJSON() as ChatSendRequest;
      state.sent.push(body);
      const turn = queue.shift() ?? reportRun('Tamam.');
      if (turn.error) return json({ detail: turn.error.detail }, turn.error.status);

      const userText = body.content || 'Planı başlat';
      if (conversation.messages.length === 0) conversation.title = userText.slice(0, 60);
      conversation.messages.push({ id: messageId++, role: 'user', content: userText, events: [], cost: 0, created_at: null });
      const status = turn.status ?? 'idle';
      const tokens = turn.events.filter((e) => e.type === 'token').map((e) => (e as { text: string }).text).join('');
      const clarification = turn.events.find((e) => e.type === 'clarification');
      const approval = turn.events.find((e) => e.type === 'plan_approval');
      const id = messageId++;
      conversation.messages.push({
        id, role: 'assistant', content: tokens || (clarification ? 'Sorunuzu netleştirmek istiyorum' : 'Analiz planı onayınızı bekliyor.'),
        events: turn.events.filter((e) => e.type !== 'token'), cost: 0.0042, created_at: null,
      });
      conversation.status = status;
      conversation.pending = clarification && clarification.type === 'clarification'
        ? { kind: 'clarification', questions: clarification.questions, restatement: clarification.restatement }
        : approval && approval.type === 'plan_approval' ? { kind: 'plan_approval', steps: approval.steps } : null;
      const events: ChatEvent[] = [...turn.events, { type: 'done', message_id: id, status, cost: 0.0042 }];
      return route.fulfill({
        status: 200,
        headers: { 'content-type': 'text/event-stream' },
        body: events.map((e) => `data: ${JSON.stringify(e)}\n\n`).join(''),
      });
    }
    return json({ detail: `mockChat: unhandled ${method} ${path}` }, 404);
  });

  return state;
}
