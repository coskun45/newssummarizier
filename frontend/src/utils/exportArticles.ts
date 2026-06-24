/**
 * Export helpers for the favorites group: build a Word document (HTML→.doc,
 * dependency-free) and a WhatsApp-ready message from selected articles,
 * including their summaries.
 */
import { format } from 'date-fns';
import { tr } from 'date-fns/locale';
import type { Article, Summary } from '../types';

/** An article paired with its fetched summaries, ready to export. */
export interface ExportItem {
  article: Article;
  summaries: Summary[];
}

const PRIORITY_LABELS: Record<string, string> = {
  high: 'Yüksek',
  med: 'Orta',
  low: 'Düşük',
};

const SUMMARY_ORDER: Array<Summary['summary_type']> = ['brief', 'standard', 'detailed'];
const SUMMARY_LABELS: Record<Summary['summary_type'], string> = {
  brief: 'Kısa',
  standard: 'Standart',
  detailed: 'Detaylı',
};

function formatDate(iso: string | null): string {
  if (!iso) return '—';
  try {
    return format(new Date(iso), 'dd MMMM yyyy HH:mm', { locale: tr });
  } catch {
    return iso;
  }
}

function sourceOf(article: Article): string {
  try {
    return new URL(article.url).hostname.replace('www.', '');
  } catch {
    return '';
  }
}

function priorityLabel(p: string | null): string {
  return p ? (PRIORITY_LABELS[p] ?? p) : '';
}

function topicsOf(article: Article): string {
  return article.topics.map((t) => t.name).join(', ');
}

/** Summaries ordered brief→standard→detailed (only the ones that exist). */
function orderedSummaries(summaries: Summary[]): Summary[] {
  return SUMMARY_ORDER
    .map((t) => summaries.find((s) => s.summary_type === t))
    .filter((s): s is Summary => Boolean(s));
}

function escapeHtml(s: string): string {
  return s
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

/** Plain-text message for WhatsApp (uses *bold* markup). */
export function buildWhatsAppMessage(items: ExportItem[]): string {
  const today = format(new Date(), 'dd MMMM yyyy', { locale: tr });
  const header = `*📰 Favori Haberler — ${today}*\n`;

  const blocks = items.map(({ article: a, summaries }, i) => {
    const lines = [`*${i + 1}. ${a.title}*`];
    const source = sourceOf(a);
    const meta: string[] = [];
    if (source) meta.push(source);
    const prio = priorityLabel(a.priority);
    if (prio) meta.push(`Öncelik: ${prio}`);
    if (meta.length) lines.push(`🏷️ ${meta.join(' · ')}`);
    lines.push(`🗓️ ${formatDate(a.published_at)}`);
    if (a.author) lines.push(`✍️ ${a.author}`);
    const topics = topicsOf(a);
    if (topics) lines.push(`📂 ${topics}`);
    lines.push(`🔗 ${a.url}`);

    const ordered = orderedSummaries(summaries);
    for (const s of ordered) {
      const label = SUMMARY_LABELS[s.summary_type] ?? s.summary_type;
      lines.push(`📝 ${label} özet:\n${s.summary_text}`);
    }
    return lines.join('\n');
  });

  return [header, ...blocks].join('\n\n');
}

/** Build an HTML document that Word opens cleanly. */
function buildWordHtml(items: ExportItem[]): string {
  const today = format(new Date(), 'dd MMMM yyyy', { locale: tr });
  const body = items
    .map(({ article: a, summaries }, i) => {
      const source = sourceOf(a);
      const prio = priorityLabel(a.priority);
      const topics = topicsOf(a);
      const metaRows = [
        source ? `<tr><td><b>Kaynak</b></td><td>${escapeHtml(source)}</td></tr>` : '',
        `<tr><td><b>Tarih</b></td><td>${escapeHtml(formatDate(a.published_at))}</td></tr>`,
        a.author ? `<tr><td><b>Yazar</b></td><td>${escapeHtml(a.author)}</td></tr>` : '',
        topics ? `<tr><td><b>Konular</b></td><td>${escapeHtml(topics)}</td></tr>` : '',
        prio ? `<tr><td><b>Öncelik</b></td><td>${escapeHtml(prio)}</td></tr>` : '',
        `<tr><td><b>Link</b></td><td><a href="${escapeHtml(a.url)}">${escapeHtml(a.url)}</a></td></tr>`,
      ]
        .filter(Boolean)
        .join('');

      const summaryHtml = orderedSummaries(summaries)
        .map((s) => {
          const label = SUMMARY_LABELS[s.summary_type] ?? s.summary_type;
          const text = escapeHtml(s.summary_text).replace(/\n/g, '<br/>');
          return `<p><b>📝 ${label} özet:</b><br/>${text}</p>`;
        })
        .join('');

      return `
        <h3>${i + 1}. ${escapeHtml(a.title)}</h3>
        <table border="0" cellspacing="0" cellpadding="4" style="margin-bottom:8px;">
          ${metaRows}
        </table>
        ${summaryHtml}
        <hr/>`;
    })
    .join('\n');

  return `<!DOCTYPE html>
<html xmlns:o="urn:schemas-microsoft-com:office:office" xmlns:w="urn:schemas-microsoft-com:office:word" xmlns="http://www.w3.org/TR/REC-html40">
<head><meta charset="utf-8"><title>Favori Haberler</title></head>
<body style="font-family:Calibri,Arial,sans-serif;">
  <h1>📰 Favori Haberler</h1>
  <p>${today} — ${items.length} makale</p>
  <hr/>
  ${body}
</body>
</html>`;
}

/** Trigger a browser download of the selected articles as a Word (.doc) file. */
export function downloadArticlesAsWord(items: ExportItem[]): void {
  const html = buildWordHtml(items);
  const blob = new Blob(['﻿', html], { type: 'application/msword' });
  const url = URL.createObjectURL(blob);
  const stamp = format(new Date(), 'yyyy-MM-dd', { locale: tr });
  const link = document.createElement('a');
  link.href = url;
  link.download = `favori-haberler-${stamp}.doc`;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  URL.revokeObjectURL(url);
}

/** Copy text to the clipboard, with a legacy fallback. Returns success. */
export async function copyToClipboard(text: string): Promise<boolean> {
  try {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(text);
      return true;
    }
  } catch {
    // fall through to legacy path
  }
  try {
    const ta = document.createElement('textarea');
    ta.value = text;
    ta.style.position = 'fixed';
    ta.style.opacity = '0';
    document.body.appendChild(ta);
    ta.select();
    const ok = document.execCommand('copy');
    document.body.removeChild(ta);
    return ok;
  } catch {
    return false;
  }
}
