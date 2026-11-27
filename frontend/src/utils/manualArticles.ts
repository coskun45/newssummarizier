/**
 * Client-side checks for manually added articles (Haber Ekle form + JSON upload). They mirror the
 * backend's ManualArticleIn validation (POST /articles/manual), so problems show up per row before
 * anything is sent; the backend still validates everything itself.
 */
import type { Feed, ManualArticleInput } from '../types';

export const MANUAL_MAX_ARTICLES = 50;
export const MANUAL_MAX_FILE_BYTES = 2 * 1024 * 1024;
/** A manual article added without a link gets a `manual://<uuid>` url, which can't be opened. */
export const MANUAL_URL_PREFIX = 'manual://';

/** False for a manual article added without a link: its `manual://` url is a placeholder, not a
 * page — never render it as a link or share it. */
export function hasArticleLink(article: { url: string }): boolean {
    return !article.url.startsWith(MANUAL_URL_PREFIX);
}

export const SAMPLE_MANUAL_JSON = {
    articles: [
        {
            title: "Almanya'da yeni göç yasası kabul edildi",
            feed: 'DW - Deutsche Welle',
            content: 'Federal Meclis bugün ... (haberin tam metni)',
            url: 'https://example.com/haber/123',
            author: 'Ayşe Yılmaz',
            published_at: '2026-11-27T09:30:00Z',
            image_url: 'https://example.com/gorsel.jpg',
        },
        {
            title: 'Sadece URL ile eklenen haber',
            feed_id: 1,
            url: 'https://example.com/haber/456',
        },
    ],
};

export interface ManualRow {
    input: ManualArticleInput;
    /** Feed title the row resolves to, if any. */
    feedLabel: string | null;
    problems: string[];
}

export type ParseResult = { ok: true; rows: ManualRow[] } | { ok: false; error: string };

function isHttpUrl(value: string): boolean {
    try {
        const url = new URL(value);
        return url.protocol === 'http:' || url.protocol === 'https:';
    } catch {
        return false;
    }
}

function text(value: unknown): string | null {
    if (typeof value !== 'string') return null;
    const trimmed = value.trim();
    return trimmed || null;
}

/** Mirrors `crud.feed_title_key` (backend): trimmed, lowercased, Turkish İ/I/ı folded to "i". */
export function feedTitleKey(title: string | null | undefined): string {
    return (title ?? '').trim().toLowerCase().replace(/̇/g, '').replace(/ı/g, 'i');
}

function findFeed(feeds: Feed[], feedId: number | null, feedTitle: string | null): Feed | undefined {
    if (feedId !== null) return feeds.find((f) => f.id === feedId);
    if (feedTitle) {
        const wanted = feedTitleKey(feedTitle);
        return feeds.find((f) => feedTitleKey(f.title) === wanted);
    }
    return undefined;
}

// What the backend's datetime field accepts from a string: an ISO 8601 date, optionally with a
// time (T or space) and a Z / ±HH:MM offset. Date.parse is looser ("27 Nov 2026", "2026/11/27"),
// and one such row would fail the whole upload with 422.
const ISO_DATE = /^\d{4}-\d{2}-\d{2}([T ]\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}:?\d{2})?)?$/i;

const HAS_OFFSET = /(Z|[+-]\d{2}:?\d{2})$/i;

/** A valid ISO date as an absolute timestamp. Without an offset it is local time, like the form's
 * date field (the backend would store it as UTC); a date alone is local midnight. */
function absoluteDate(value: string): string {
    if (HAS_OFFSET.test(value)) return value;
    const local = value.replace(' ', 'T');
    return new Date(local.includes('T') ? local : `${local}T00:00`).toISOString();
}

/** Normalize one raw entry and list what is wrong with it (empty = it can be sent). */
export function checkManualArticle(raw: unknown, feeds: Feed[]): ManualRow {
    const entry = (raw && typeof raw === 'object' && !Array.isArray(raw) ? raw : {}) as Record<string, unknown>;
    const feedId = typeof entry.feed_id === 'number' && Number.isInteger(entry.feed_id) ? entry.feed_id : null;
    const input: ManualArticleInput = {
        title: text(entry.title) ?? '',
        feed_id: feedId,
        feed: feedId === null ? text(entry.feed) : null,
        content: text(entry.content),
        url: text(entry.url),
        author: text(entry.author),
        published_at: text(entry.published_at),
        image_url: text(entry.image_url),
    };
    const problems: string[] = [];
    if (input.title.length < 3) problems.push('Başlık en az 3 karakter olmalı');
    if (input.title.length > 500) problems.push('Başlık en fazla 500 karakter olabilir');
    const feed = findFeed(feeds, feedId, input.feed ?? null);
    if (feedId === null && !input.feed) problems.push('Kaynak (feed veya feed_id) gerekli');
    else if (!feed) problems.push('Kaynak bulunamadı');
    if (!input.content && !input.url) problems.push('İçerik veya URL gerekli');
    // Same limits as ManualArticleIn (backend), so a row the preview calls "Hazır" is accepted.
    if (input.content && input.content.length > 100_000) problems.push('İçerik en fazla 100.000 karakter olabilir');
    if (input.author && input.author.length > 200) problems.push('Yazar en fazla 200 karakter olabilir');
    if ((input.feed?.length ?? 0) > 500) problems.push('Kaynak adı en fazla 500 karakter olabilir');
    if (input.url && (!isHttpUrl(input.url) || input.url.length > 2000)) problems.push('URL http(s):// ile başlayan geçerli bir adres olmalı');
    if (input.image_url && (!isHttpUrl(input.image_url) || input.image_url.length > 2000)) {
        problems.push('Görsel URL http(s):// ile başlayan geçerli bir adres olmalı');
    }
    if (input.published_at && (!ISO_DATE.test(input.published_at) || Number.isNaN(Date.parse(input.published_at.replace(' ', 'T'))))) {
        problems.push('Yayın tarihi ISO 8601 biçiminde olmalı (ör. 2026-11-27T09:30:00Z)');
    } else if (input.published_at) {
        input.published_at = absoluteDate(input.published_at);
    }
    return { input, feedLabel: feed ? (feed.title ?? feed.url) : null, problems };
}

/** Parse an uploaded / pasted JSON: `{ "articles": [...] }` or a bare `[...]`. */
export function parseManualJson(source: string, feeds: Feed[]): ParseResult {
    let data: unknown;
    try {
        data = JSON.parse(source);
    } catch {
        return { ok: false, error: 'Geçersiz JSON: dosya ayrıştırılamadı.' };
    }
    const list = Array.isArray(data)
        ? data
        : data && typeof data === 'object' && Array.isArray((data as { articles?: unknown }).articles)
            ? (data as { articles: unknown[] }).articles
            : null;
    if (!list) return { ok: false, error: 'JSON bir "articles" listesi içermeli.' };
    if (list.length === 0) return { ok: false, error: 'Listede haber yok.' };
    if (list.length > MANUAL_MAX_ARTICLES) {
        return { ok: false, error: `Tek seferde en fazla ${MANUAL_MAX_ARTICLES} haber yüklenebilir (${list.length} bulundu).` };
    }
    return { ok: true, rows: list.map((entry) => checkManualArticle(entry, feeds)) };
}

/** The JSON text without the entries at `indexes` (positions in its list), or '' when none is
 * left. Used after an upload so the created rows can't be sent (and created) a second time. */
export function removeManualRows(source: string, indexes: number[]): string {
    const data: unknown = JSON.parse(source);
    const list = Array.isArray(data) ? data : (data as { articles: unknown[] }).articles;
    const drop = new Set(indexes);
    const remaining = list.filter((_, i) => !drop.has(i));
    return remaining.length === 0 ? '' : JSON.stringify({ articles: remaining }, null, 2);
}
