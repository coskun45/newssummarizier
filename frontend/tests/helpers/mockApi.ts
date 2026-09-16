import type { Page, Route, Request } from '@playwright/test';
import type {
  Feed,
  Topic,
  Article,
  Summary,
  UserSettings,
  SystemPrompt,
  AppUser,
  BulletinCategory,
  GeneratedBulletin,
} from '../../src/types';

let idSeq = 1000;
function nextId(): number {
  idSeq += 1;
  return idSeq;
}

/** Article fixture with an extra internal field used only by the mock's own
 * filtering logic — harmless extra JSON since the frontend doesn't runtime-validate. */
export interface MockArticle extends Article {
  feedId: number;
  raw_content: string | null;
  cleaned_content: string | null;
}

export function makeFeed(overrides: Partial<Feed> = {}): Feed {
  const id = overrides.id ?? nextId();
  return {
    id,
    url: `https://example.com/feed-${id}`,
    title: `Feed ${id}`,
    description: null,
    last_fetched: null,
    is_active: true,
    created_at: new Date().toISOString(),
    ...overrides,
  };
}

export function makeTopic(overrides: Partial<Topic> = {}): Topic {
  const id = overrides.id ?? nextId();
  return {
    id,
    name: `Topic ${id}`,
    description: null,
    color: '#3b82f6',
    ...overrides,
  };
}

export function makeArticle(overrides: Partial<MockArticle> = {}): MockArticle {
  const id = overrides.id ?? nextId();
  const now = new Date().toISOString();
  return {
    id,
    url: `https://example.com/article-${id}`,
    title: `Article ${id}`,
    author: null,
    published_at: now,
    fetched_at: now,
    status: 'summarized',
    importance: null,
    priority: null,
    image_url: null,
    topics: [],
    has_summaries: false,
    is_read: false,
    is_starred: false,
    feedId: 1,
    raw_content: null,
    cleaned_content: null,
    ...overrides,
  };
}

export function makeSummary(articleId: number, overrides: Partial<Summary> = {}): Summary {
  const id = overrides.id ?? nextId();
  return {
    id,
    article_id: articleId,
    summary_text: 'Mock summary text.',
    summary_type: 'brief',
    model_used: 'gpt-4o-mini',
    tokens_used: 42,
    cost: 0.001,
    created_at: new Date().toISOString(),
    ...overrides,
  };
}

export function makePrompt(promptType: string, overrides: Partial<SystemPrompt> = {}): SystemPrompt {
  const id = overrides.id ?? nextId();
  const now = new Date().toISOString();
  return {
    id,
    prompt_type: promptType,
    prompt_text: `Default ${promptType} prompt text.`,
    is_active: true,
    created_at: now,
    updated_at: now,
    ...overrides,
  };
}

export function makeBulletinCategory(overrides: Partial<BulletinCategory> = {}): BulletinCategory {
  const id = overrides.id ?? nextId();
  return {
    id,
    name: `Category ${id}`,
    display_order: 0,
    ...overrides,
  };
}

export function makeGeneratedBulletin(overrides: Partial<GeneratedBulletin> = {}): GeneratedBulletin {
  const id = overrides.id ?? nextId();
  return {
    id,
    filename: `bulten-${id}.docx`,
    published_from: null,
    published_to: null,
    priorities: null,
    include_favorites: false,
    article_count: 0,
    generated_at: new Date().toISOString(),
    ...overrides,
  };
}

export function makeUser(overrides: Partial<AppUser> = {}): AppUser {
  const id = overrides.id ?? nextId();
  return {
    id,
    email: `user${id}@example.com`,
    role: 'user',
    is_active: true,
    created_at: new Date().toISOString(),
    ...overrides,
  };
}

export interface MockState {
  feeds: Feed[];
  topics: Topic[];
  articles: MockArticle[];
  summaries: Map<number, Summary[]>;
  settings: UserSettings;
  prompts: Map<string, SystemPrompt>;
  users: AppUser[];
  bulletinCategories: BulletinCategory[];
  generatedBulletins: GeneratedBulletin[];
}

export interface MockApiOverrides {
  feeds?: Feed[];
  topics?: Topic[];
  articles?: MockArticle[];
  summaries?: Map<number, Summary[]>;
  settings?: Partial<UserSettings>;
  prompts?: Map<string, SystemPrompt>;
  users?: AppUser[];
  bulletinCategories?: BulletinCategory[];
  generatedBulletins?: GeneratedBulletin[];
}

function computeCounts(articles: MockArticle[]) {
  const by_priority: Record<string, number> = {};
  const by_feed: Record<string, number> = {};
  let unimportant_count = 0;
  let unread_count = 0;
  let read_count = 0;
  let starred_count = 0;

  for (const a of articles) {
    if (!a.is_read) {
      const feedKey = String(a.feedId);
      by_feed[feedKey] = (by_feed[feedKey] ?? 0) + 1;

      unread_count += 1;
      if (a.priority) by_priority[a.priority] = (by_priority[a.priority] ?? 0) + 1;
      if (a.importance === 'unimportant') unimportant_count += 1;
    } else {
      read_count += 1;
    }
    if (a.is_starred) starred_count += 1;
  }

  return { by_priority, by_feed, unimportant_count, unread_count, read_count, starred_count };
}

function computeTopicsWithCounts(topics: Topic[], articles: MockArticle[], feedId: number | null): Topic[] {
  const scoped = feedId != null ? articles.filter((a) => a.feedId === feedId) : articles;
  const result: Topic[] = [];
  for (const topic of topics) {
    let article_count = 0;
    let unread_count = 0;
    for (const a of scoped) {
      if (a.topics.some((t) => t.id === topic.id)) {
        article_count += 1;
        if (!a.is_read) unread_count += 1;
      }
    }
    if (feedId != null && article_count === 0) continue; // mirrors backend having(count>0) when feed-scoped
    result.push({ ...topic, article_count, unread_count });
  }
  return result;
}

function parseIdList(raw: string | null): number[] | null {
  if (!raw) return null;
  return raw.split(',').map((v) => parseInt(v, 10)).filter((n) => !Number.isNaN(n));
}

function matchesArticleFilters(a: MockArticle, params: URLSearchParams): boolean {
  const priority = params.get('priority');
  if (priority && a.priority !== priority) return false;

  const status = params.get('status');
  if (status && a.status !== status) return false;

  const isRead = params.get('is_read');
  if (isRead !== null && a.is_read !== (isRead === 'true')) return false;

  const isStarred = params.get('is_starred');
  if (isStarred !== null && a.is_starred !== (isStarred === 'true')) return false;

  const topicIds = parseIdList(params.get('topic_ids'));
  if (topicIds && !a.topics.some((t) => topicIds.includes(t.id))) return false;

  const feedIds = parseIdList(params.get('feed_ids'));
  if (feedIds) {
    if (!feedIds.includes(a.feedId)) return false;
  } else {
    const feedId = params.get('feed_id');
    if (feedId && a.feedId !== parseInt(feedId, 10)) return false;
  }

  const search = params.get('search');
  if (search) {
    const needle = search.toLowerCase();
    const haystack = `${a.title} ${a.cleaned_content ?? ''}`.toLowerCase();
    if (!haystack.includes(needle)) return false;
  }

  const publishedFrom = params.get('published_from');
  if (publishedFrom && (!a.published_at || a.published_at < publishedFrom)) return false;
  const publishedTo = params.get('published_to');
  if (publishedTo && (!a.published_at || a.published_at > publishedTo)) return false;
  const fetchedFrom = params.get('fetched_from');
  if (fetchedFrom && a.fetched_at < fetchedFrom) return false;
  const fetchedTo = params.get('fetched_to');
  if (fetchedTo && a.fetched_at > fetchedTo) return false;

  return true;
}

/** Mirrors the backend's bulletin candidate selection: priority match OR
 * (if include_favorites) starred, defaulting to the last 24h when no date
 * range is given — kept in sync with crud.get/count_bulletin_candidate_articles. */
function computeBulletinPreviewCount(articles: MockArticle[], params: URLSearchParams): number {
  const rawPriorities = params.get('priorities');
  const priorities = rawPriorities ? rawPriorities.split(',').filter(Boolean) : [];
  const includeFavorites = params.get('include_favorites') === 'true';

  const to = params.get('published_to') ?? new Date().toISOString();
  const from = params.get('published_from') ?? new Date(new Date(to).getTime() - 24 * 60 * 60 * 1000).toISOString();

  return articles.filter((a) => {
    if (!a.published_at || a.published_at < from || a.published_at > to) return false;
    if (priorities.length === 0 && !includeFavorites) return true;
    const priorityMatches = priorities.length > 0 && !!a.priority && priorities.includes(a.priority);
    const starredMatches = includeFavorites && a.is_starred;
    return priorityMatches || starredMatches;
  }).length;
}

/**
 * Install a single dispatching route handler for every /api/* request,
 * backed by a mutable in-memory state so write requests (star/delete/bulk
 * actions/settings/prompts/...) are reflected in subsequent GETs — this
 * reproduces the app's real invalidate-then-refetch flow without a backend.
 *
 * Any /api/* request this dispatcher doesn't recognize gets a visible 404
 * instead of hanging, so a spec with a mocking gap fails loudly.
 */
export async function mockApi(page: Page, overrides: MockApiOverrides = {}): Promise<MockState> {
  // Shallow-clone every fixture object: handlers below (PUT /feeds/:id,
  // PUT /topics/:id, ...) mutate the matched record in place via
  // Object.assign. Specs commonly hoist a fixture to a module-level `const`
  // (e.g. `const FEED = makeFeed(...)`) and reuse it across tests for
  // readability — without cloning here, one test's edit permanently mutates
  // that shared object for every later test in the file.
  const state: MockState = {
    feeds: (overrides.feeds ?? [makeFeed({ id: 1, title: 'DW - Deutsche Welle' })]).map((f) => ({ ...f })),
    topics: (overrides.topics ?? []).map((t) => ({ ...t })),
    articles: (overrides.articles ?? []).map((a) => ({ ...a })),
    summaries: overrides.summaries ?? new Map(),
    settings: {
      enabled_topics: '',
      enabled_summary_types: 'brief,standard,detailed',
      feed_refresh_interval: 1800,
      ...overrides.settings,
    },
    prompts: overrides.prompts ?? new Map(),
    users: (overrides.users ?? []).map((u) => ({ ...u })),
    bulletinCategories: (overrides.bulletinCategories ?? []).map((c) => ({ ...c })),
    generatedBulletins: (overrides.generatedBulletins ?? []).map((b) => ({ ...b })),
  };

  await page.route('**/api/**', async (route: Route) => {
    const request: Request = route.request();
    const method = request.method();
    const url = new URL(request.url());
    const path = url.pathname.replace(/^.*\/api/, ''); // path relative to /api
    const params = url.searchParams;
    const json = (data: unknown, status = 200) =>
      route.fulfill({ status, json: data as object });

    // ---- app info ----
    if (method === 'GET' && path === '/info') {
      return json({ app: 'News Summarizer', version: '1.0.0', status: 'running' });
    }

    // ---- feeds ----
    if (method === 'GET' && path === '/feeds/') {
      const activeOnly = params.get('active_only') !== 'false';
      const list = activeOnly ? state.feeds.filter((f) => f.is_active) : state.feeds;
      return json(list);
    }
    if (method === 'POST' && path === '/feeds/') {
      const body = request.postDataJSON() as { url: string; title?: string; description?: string };
      const feed = makeFeed({ url: body.url, title: body.title ?? null, description: body.description ?? null });
      state.feeds.push(feed);
      return json(feed);
    }
    if (method === 'POST' && path === '/feeds/test') {
      return json({ status: 'ok' });
    }
    let m = path.match(/^\/feeds\/(\d+)$/);
    if (m) {
      const feedId = parseInt(m[1], 10);
      if (method === 'GET') {
        const feed = state.feeds.find((f) => f.id === feedId);
        return feed ? json(feed) : json({ detail: 'Feed not found' }, 404);
      }
      if (method === 'PUT') {
        const feed = state.feeds.find((f) => f.id === feedId);
        if (!feed) return json({ detail: 'Feed not found' }, 404);
        const body = request.postDataJSON() as Partial<Feed>;
        Object.assign(feed, body);
        return json(feed);
      }
      if (method === 'DELETE') {
        const idx = state.feeds.findIndex((f) => f.id === feedId);
        if (idx === -1) return json({ detail: 'Feed not found' }, 404);
        state.feeds.splice(idx, 1);
        state.articles = state.articles.filter((a) => a.feedId !== feedId);
        return json({ status: 'deleted', feed_id: feedId });
      }
    }
    m = path.match(/^\/feeds\/(\d+)\/refresh$/);
    if (m && method === 'POST') {
      return json({ status: 'queued', feed_id: parseInt(m[1], 10) });
    }
    m = path.match(/^\/feeds\/(\d+)\/refresh-status$/);
    if (m && method === 'GET') {
      return json({ status: 'idle' });
    }

    // ---- article counts (must be matched before the generic :id route) ----
    if (method === 'GET' && path === '/articles/counts') {
      return json(computeCounts(state.articles));
    }

    // ---- article bulk endpoints ----
    if (method === 'POST' && path === '/articles/mark-read-bulk') {
      const body = request.postDataJSON() as {
        article_ids?: number[];
        mark_all?: boolean;
        [key: string]: unknown;
      };
      let count = 0;
      if (body.mark_all) {
        const qp = new URLSearchParams();
        for (const [k, v] of Object.entries(body)) {
          if (v !== undefined && v !== null && k !== 'mark_all' && k !== 'article_ids') {
            qp.set(k, String(v));
          }
        }
        for (const a of state.articles) {
          if (!a.is_read && matchesArticleFilters(a, qp)) {
            a.is_read = true;
            count += 1;
          }
        }
      } else if (body.article_ids) {
        for (const a of state.articles) {
          if (!a.is_read && body.article_ids.includes(a.id)) {
            a.is_read = true;
            count += 1;
          }
        }
      }
      return json({ marked_count: count });
    }
    if (method === 'POST' && path === '/articles/unstar-all') {
      let count = 0;
      for (const a of state.articles) {
        if (a.is_starred) {
          a.is_starred = false;
          count += 1;
        }
      }
      return json({ unstarred_count: count });
    }
    m = path.match(/^\/articles\/priority\/([^/]+)\/(delete|archive)-all$/);
    if (m && method === 'POST') {
      const [, priority, action] = m;
      const feedIds = parseIdList(params.get('feed_ids'));
      const matches = (a: MockArticle) =>
        !a.is_read && a.priority === priority && (!feedIds || feedIds.includes(a.feedId));
      if (action === 'delete') {
        const before = state.articles.length;
        state.articles = state.articles.filter((a) => !matches(a));
        return json({ deleted_count: before - state.articles.length });
      }
      let count = 0;
      for (const a of state.articles) {
        if (matches(a)) {
          a.is_read = true;
          count += 1;
        }
      }
      return json({ archived_count: count });
    }
    m = path.match(/^\/articles\/unimportant\/(delete|archive)-all$/);
    if (m && method === 'POST') {
      const action = m[1];
      const feedIds = parseIdList(params.get('feed_ids'));
      const matches = (a: MockArticle) =>
        !a.is_read && a.importance === 'unimportant' && (!feedIds || feedIds.includes(a.feedId));
      if (action === 'delete') {
        const before = state.articles.length;
        state.articles = state.articles.filter((a) => !matches(a));
        return json({ deleted_count: before - state.articles.length });
      }
      let count = 0;
      for (const a of state.articles) {
        if (matches(a)) {
          a.is_read = true;
          count += 1;
        }
      }
      return json({ archived_count: count });
    }

    // ---- single-article endpoints ----
    m = path.match(/^\/articles\/(\d+)\/read$/);
    if (m && method === 'PATCH') {
      const article = state.articles.find((a) => a.id === parseInt(m![1], 10));
      if (!article) return json({ detail: 'Article not found' }, 404);
      article.is_read = true;
      return json({ id: article.id, is_read: true });
    }
    m = path.match(/^\/articles\/(\d+)\/star$/);
    if (m && method === 'PATCH') {
      const article = state.articles.find((a) => a.id === parseInt(m![1], 10));
      if (!article) return json({ detail: 'Article not found' }, 404);
      const body = request.postDataJSON() as { starred?: boolean };
      article.is_starred = body.starred ?? true;
      return json({ id: article.id, is_starred: article.is_starred });
    }
    m = path.match(/^\/articles\/(\d+)\/summaries$/);
    if (m && method === 'GET') {
      const articleId = parseInt(m[1], 10);
      const summaryType = params.get('summary_type');
      let list = state.summaries.get(articleId) ?? [];
      if (summaryType) list = list.filter((s) => s.summary_type === summaryType);
      return json(list);
    }
    m = path.match(/^\/articles\/(\d+)$/);
    if (m) {
      const articleId = parseInt(m[1], 10);
      if (method === 'GET') {
        const article = state.articles.find((a) => a.id === articleId);
        return article ? json(article) : json({ detail: 'Article not found' }, 404);
      }
      if (method === 'DELETE') {
        const idx = state.articles.findIndex((a) => a.id === articleId);
        if (idx === -1) return json({ detail: 'Article not found' }, 404);
        state.articles.splice(idx, 1);
        return route.fulfill({ status: 204, body: '' });
      }
    }

    // ---- article list ----
    if (method === 'GET' && path === '/articles/') {
      const skip = parseInt(params.get('skip') ?? '0', 10);
      const limit = parseInt(params.get('limit') ?? '50', 10);
      const filtered = state.articles.filter((a) => matchesArticleFilters(a, params));
      filtered.sort((a, b) => (b.published_at ?? '').localeCompare(a.published_at ?? ''));
      const page = filtered.slice(skip, skip + limit);
      return json({ articles: page, total: filtered.length, skip, limit });
    }

    // ---- topics ----
    if (method === 'GET' && path === '/topics/') {
      const feedIdParam = params.get('feed_id');
      const feedId = feedIdParam ? parseInt(feedIdParam, 10) : null;
      return json(computeTopicsWithCounts(state.topics, state.articles, feedId));
    }
    if (method === 'POST' && path === '/topics/') {
      const body = request.postDataJSON() as { name: string; description?: string; color?: string };
      const topic = makeTopic({ name: body.name, description: body.description ?? null, color: body.color ?? '#3b82f6' });
      state.topics.push(topic);
      return json({ ...topic, article_count: 0, unread_count: 0 });
    }
    m = path.match(/^\/topics\/(\d+)$/);
    if (m) {
      const topicId = parseInt(m[1], 10);
      const topic = state.topics.find((t) => t.id === topicId);
      if (method === 'PUT') {
        if (!topic) return json({ detail: 'Topic not found' }, 404);
        const body = request.postDataJSON() as Partial<Topic>;
        Object.assign(topic, body);
        for (const a of state.articles) {
          const linked = a.topics.find((t) => t.id === topicId);
          if (linked) Object.assign(linked, { name: topic.name, color: topic.color });
        }
        return json(topic);
      }
      if (method === 'DELETE') {
        if (!topic) return json({ detail: 'Topic not found' }, 404);
        state.topics = state.topics.filter((t) => t.id !== topicId);
        for (const a of state.articles) a.topics = a.topics.filter((t) => t.id !== topicId);
        return json({ status: 'success', message: `Topic '${topic.name}' deleted successfully` });
      }
    }

    // ---- settings ----
    if (path === '/settings/' && (method === 'GET' || method === 'PUT')) {
      if (method === 'PUT') {
        const body = request.postDataJSON() as UserSettings;
        state.settings = { ...state.settings, ...body };
      }
      return json(state.settings);
    }

    // ---- prompts ----
    if (method === 'GET' && path === '/prompts/') {
      return json(Array.from(state.prompts.values()));
    }
    if (method === 'POST' && path === '/prompts/') {
      const body = request.postDataJSON() as { prompt_type: string; prompt_text: string; is_active?: boolean };
      const existing = state.prompts.get(body.prompt_type);
      const prompt = makePrompt(body.prompt_type, {
        id: existing?.id,
        prompt_text: body.prompt_text,
        is_active: body.is_active ?? true,
        created_at: existing?.created_at,
      });
      state.prompts.set(body.prompt_type, prompt);
      return json(prompt);
    }
    m = path.match(/^\/prompts\/([^/]+)$/);
    if (m) {
      const promptType = decodeURIComponent(m[1]);
      if (method === 'GET') {
        const prompt = state.prompts.get(promptType);
        return prompt ? json(prompt) : json({ detail: `System prompt '${promptType}' not found` }, 404);
      }
      if (method === 'PUT') {
        const prompt = state.prompts.get(promptType);
        if (!prompt) return json({ detail: `System prompt '${promptType}' not found` }, 404);
        const body = request.postDataJSON() as { prompt_text?: string; is_active?: boolean };
        if (body.prompt_text !== undefined) prompt.prompt_text = body.prompt_text;
        if (body.is_active !== undefined) prompt.is_active = body.is_active;
        prompt.updated_at = new Date().toISOString();
        return json(prompt);
      }
    }

    // ---- users (admin) ----
    if (method === 'GET' && path === '/auth/users') {
      return json(state.users);
    }
    if (method === 'POST' && path === '/auth/users') {
      const body = request.postDataJSON() as { email: string; password: string; role: string };
      if (state.users.some((u) => u.email === body.email)) {
        return json({ detail: 'Bu e-posta adresi zaten kayıtlı' }, 400);
      }
      const user = makeUser({ email: body.email, role: body.role });
      state.users.push(user);
      return json(user);
    }
    m = path.match(/^\/auth\/users\/(\d+)$/);
    if (m && method === 'DELETE') {
      const userId = parseInt(m[1], 10);
      state.users = state.users.filter((u) => u.id !== userId);
      return route.fulfill({ status: 204, body: '' });
    }

    // ---- bulletin categories ----
    if (method === 'GET' && path === '/bulletin/categories') {
      const sorted = [...state.bulletinCategories].sort((a, b) => a.display_order - b.display_order);
      return json(sorted);
    }
    if (method === 'POST' && path === '/bulletin/categories') {
      const body = request.postDataJSON() as { name: string };
      const maxOrder = state.bulletinCategories.reduce((max, c) => Math.max(max, c.display_order), -1);
      const category = makeBulletinCategory({ name: body.name, display_order: maxOrder + 1 });
      state.bulletinCategories.push(category);
      return json(category);
    }
    if (method === 'PUT' && path === '/bulletin/categories/reorder') {
      const body = request.postDataJSON() as { ordered_ids: number[] };
      body.ordered_ids.forEach((id, index) => {
        const category = state.bulletinCategories.find((c) => c.id === id);
        if (category) category.display_order = index;
      });
      const sorted = [...state.bulletinCategories].sort((a, b) => a.display_order - b.display_order);
      return json(sorted);
    }
    m = path.match(/^\/bulletin\/categories\/(\d+)$/);
    if (m) {
      const categoryId = parseInt(m[1], 10);
      const category = state.bulletinCategories.find((c) => c.id === categoryId);
      if (method === 'PUT') {
        if (!category) return json({ detail: 'Category not found' }, 404);
        const body = request.postDataJSON() as { name?: string };
        if (body.name) category.name = body.name;
        return json(category);
      }
      if (method === 'DELETE') {
        if (!category) return json({ detail: 'Category not found' }, 404);
        state.bulletinCategories = state.bulletinCategories.filter((c) => c.id !== categoryId);
        return json({ status: 'success' });
      }
    }

    // ---- bulletin preview count ----
    if (method === 'GET' && path === '/bulletin/preview-count') {
      return json({ count: computeBulletinPreviewCount(state.articles, params) });
    }

    // ---- bulletin generate ----
    if (method === 'POST' && path === '/bulletin/generate') {
      if (state.bulletinCategories.length === 0) {
        return json({ detail: 'En az bir üst düzey kategori tanımlanmalı' }, 400);
      }
      const body = request.postDataJSON() as {
        published_from?: string;
        published_to?: string;
        priorities?: string[];
        include_favorites?: boolean;
      };
      const priorities = body.priorities ?? [];
      const includeFavorites = body.include_favorites ?? false;
      const to = body.published_to ?? new Date().toISOString();
      const from = body.published_from ?? new Date(new Date(to).getTime() - 24 * 60 * 60 * 1000).toISOString();
      const articleCount = state.articles.filter((a) => {
        if (!a.published_at || a.published_at < from || a.published_at > to) return false;
        if (priorities.length === 0 && !includeFavorites) return true;
        const priorityMatches = priorities.length > 0 && !!a.priority && priorities.includes(a.priority);
        const starredMatches = includeFavorites && a.is_starred;
        return priorityMatches || starredMatches;
      }).length;

      // Mirrors the real backend: every successful /generate persists a row
      // the "Daha Önce Oluşturulan Bültenler" list picks up, and the
      // filename is derived from published_to (not "now") — see
      // backend/app/api/routes/bulletin.py's `filename = f"bulten-{published_to.date()...}"`.
      const generated = makeGeneratedBulletin({
        filename: `bulten-${to.slice(0, 10)}.docx`,
        published_from: body.published_from ?? null,
        published_to: body.published_to ?? null,
        priorities: priorities.length > 0 ? priorities : null,
        include_favorites: includeFavorites,
        article_count: articleCount,
      });
      state.generatedBulletins.unshift(generated);

      return route.fulfill({
        status: 200,
        contentType: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        headers: { 'Content-Disposition': `attachment; filename="${generated.filename}"` },
        body: Buffer.from('mock docx content'),
      });
    }

    // ---- generated bulletins (previously generated reports) ----
    if (method === 'GET' && path === '/bulletin/generated') {
      return json(state.generatedBulletins);
    }
    m = path.match(/^\/bulletin\/generated\/(\d+)\/download$/);
    if (m && method === 'GET') {
      const bulletin = state.generatedBulletins.find((b) => b.id === parseInt(m![1], 10));
      if (!bulletin) return json({ detail: 'Bülten bulunamadı' }, 404);
      return route.fulfill({
        status: 200,
        contentType: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        headers: { 'Content-Disposition': `attachment; filename="${bulletin.filename}"` },
        body: Buffer.from('mock docx content'),
      });
    }
    m = path.match(/^\/bulletin\/generated\/(\d+)$/);
    if (m && method === 'DELETE') {
      const bulletinId = parseInt(m[1], 10);
      const idx = state.generatedBulletins.findIndex((b) => b.id === bulletinId);
      if (idx === -1) return json({ detail: 'Bülten bulunamadı' }, 404);
      state.generatedBulletins.splice(idx, 1);
      return json({ status: 'success' });
    }

    // Unrecognized /api/* request — fail loudly instead of hanging.
    return json({ detail: `Unmocked request: ${method} ${path}` }, 404);
  });

  return state;
}
