import { useState } from 'react';
import { formatDistanceToNow } from 'date-fns';
import { tr } from 'date-fns/locale';
import type { Article } from '../../types';
import { useSummaries, useArticle, useDeleteArticle, useSetArticleStarred } from '../../hooks/useApi';
import ContentModal from '../ContentModal/ContentModal';
import './ArticleCard.css';

const SUMMARY_ORDER = ['brief', 'standard', 'detailed'] as const;
const SUMMARY_LABELS: Record<(typeof SUMMARY_ORDER)[number], string> = {
  brief: 'Kısa',
  standard: 'Standart',
  detailed: 'Detaylı',
};

interface ArticleCardProps {
  article: Article;
  isSelected?: boolean;
  onToggleSelect?: (id: number) => void;
  onDeleted?: (id: number) => void;
  isArchiveView?: boolean;
  selectable?: boolean;
}


function ArticleCard({ article, isSelected = false, onToggleSelect, onDeleted, isArchiveView = false, selectable = false }: ArticleCardProps) {
  const [expanded, setExpanded] = useState(false);
  const [showContent, setShowContent] = useState(false);
  const [summaryType, setSummaryType] = useState<'brief' | 'standard' | 'detailed'>('standard');
  const [copied, setCopied] = useState(false);

  const deleteArticleMutation = useDeleteArticle();
  const setStarredMutation = useSetArticleStarred();

  const handleToggleExpand = () => {
    setExpanded(!expanded);
  };

  const handleCopySummary = async (text: string) => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // clipboard unavailable — ignore
    }
  };

  const { data: summaries, isLoading: summaryLoading } = useSummaries(
    expanded ? article.id : null
  );

  // Only the summary types that were actually generated for this article
  const availableTypes = SUMMARY_ORDER.filter(
    (t) => summaries?.some((s) => s.summary_type === t)
  );
  // Fall back to the first available type if the selected one wasn't generated
  const effectiveType = availableTypes.includes(summaryType) ? summaryType : availableTypes[0];
  const summary = summaries?.find((s) => s.summary_type === effectiveType);

  const { data: articleDetail, isLoading: contentLoading } = useArticle(
    showContent ? article.id : null
  );

  const timeAgo = article.published_at
    ? formatDistanceToNow(new Date(article.published_at), { addSuffix: true, locale: tr })
    : null;

  return (
    <div className={`article-card${!article.is_read ? ' article-card--unread' : ''}${isSelected ? ' article-card--selected' : ''}${(!isArchiveView && onToggleSelect) ? ' article-card--selectable' : ''}`}>
      {selectable && onToggleSelect && (
        <input
          type="checkbox"
          className="article-card-checkbox"
          checked={isSelected}
          onChange={() => onToggleSelect(article.id)}
          title="Seç"
        />
      )}
      <button
        className="delete-icon-btn"
        title="Sil"
        onClick={() => {
          deleteArticleMutation.mutate(article.id, { onSuccess: () => onDeleted?.(article.id) });
        }}
        disabled={deleteArticleMutation.isPending}
      >
        <svg
          xmlns="http://www.w3.org/2000/svg"
          width="22"
          height="22"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
          className="feather feather-trash"
        >
          <polyline points="3 6 5 6 21 6" />
          <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h2a2 2 0 0 1 2 2v2" />
          <line x1="10" y1="11" x2="10" y2="17" />
          <line x1="14" y1="11" x2="14" y2="17" />
        </svg>
      </button>

      <button
        className={`favorite-icon-btn${article.is_starred ? ' favorite-icon-btn--active' : ''}`}
        onClick={() => setStarredMutation.mutate({ articleId: article.id, starred: !article.is_starred })}
        disabled={setStarredMutation.isPending}
        title={article.is_starred ? 'Favorilerden çıkar' : 'Favorilere ekle'}
        aria-label={article.is_starred ? 'Favorilerden çıkar' : 'Favorilere ekle'}
      >
        {article.is_starred ? '★' : '☆'}
      </button>

      <div className="article-header">
        <h2 className="article-title">
          {!article.is_read && <span className="unread-dot" title="Okunmadı" />}
          {article.title}
        </h2>
        {article.author && <p className="article-author">Yazar: {article.author}</p>}
        <div className="article-meta">
          {timeAgo && <span className="article-time">{timeAgo}</span>}
          <span className="article-status">{article.status}</span>
        </div>
      </div>

      <div className="article-badges">
        {article.importance === 'unimportant' && (
          <span className="unimportant-badge">⊘ Önemsiz</span>
        )}
        {article.priority && (
          <span className={`priority-badge priority-${article.priority}`}>
            {article.priority === 'high' ? '▲ Yüksek' : article.priority === 'med' ? '● Orta' : '▼ Düşük'}
          </span>
        )}
        {article.topics.map((topic) => (
          <span
            key={topic.id}
            className="topic-badge"
            style={{ backgroundColor: topic.color || '#ccc' }}
          >
            {topic.name}
          </span>
        ))}
      </div>

      <div className="article-actions">
        {article.has_summaries && (
          <button
            className="btn btn-primary"
            onClick={handleToggleExpand}
          >
            {expanded ? 'Daha az göster' : 'Özeti göster'}
          </button>
        )}
        <button
          className="btn btn-secondary"
          onClick={() => setShowContent(true)}
          disabled={contentLoading}
        >
          {contentLoading ? '⏳ Yükleniyor...' : 'Orijinal İçerik'}
        </button>
        <a
          href={article.url}
          target="_blank"
          rel="noopener noreferrer"
          className="btn btn-outline"
        >
          Kaynağı aç →
        </a>
        {/* Delete button moved to top right as icon; favorite toggle to bottom-right */}
      </div>

      <ContentModal
        isOpen={showContent}
        onClose={() => setShowContent(false)}
        title={article.title}
        content={articleDetail?.cleaned_content || articleDetail?.raw_content || null}
      />

      {expanded && (
        <div className="article-summary">
          <div className="summary-header">
            {availableTypes.length > 1 && (
              <div className="summary-controls">
                {availableTypes.map((t) => (
                  <button
                    key={t}
                    className={`summary-type-btn ${effectiveType === t ? 'active' : ''}`}
                    onClick={() => setSummaryType(t)}
                  >
                    {SUMMARY_LABELS[t]}
                  </button>
                ))}
              </div>
            )}
            {summary && (
              <button
                className={`btn btn-outline btn-sm copy-summary-btn${copied ? ' copy-summary-btn--copied' : ''}`}
                onClick={() => handleCopySummary(summary.summary_text)}
                title={copied ? 'Kopyalandı' : 'Özeti kopyala'}
              >
                {copied ? '✅ Kopyalandı' : '📋 Kopyala'}
              </button>
            )}
          </div>

          {summaryLoading ? (
            <p className="text-muted">⏳ Özet yükleniyor...</p>
          ) : summary ? (
            <div className="summary-content">
              <p>{summary.summary_text}</p>
              <div className="summary-meta">
                <span className="text-small text-muted">
                  Model: {summary.model_used} | Maliyet: ${summary.cost.toFixed(4)}
                </span>
              </div>
            </div>
          ) : (
            <p className="text-error">Özet mevcut değil</p>
          )}
        </div>
      )}
    </div>
  );
}

export default ArticleCard;
