import { useState } from 'react';
import type { Article } from '../../types';
import { useSummaries, useArticle, useDeleteArticle, useSetArticleStarred, useReprocessArticles } from '../../hooks/useApi';
import ContentModal from '../ContentModal/ContentModal';
import { copyToClipboard } from '../../utils/exportArticles';
import { withAlpha } from '../../utils/color';
import { formatPublishedAt } from '../../utils/formatDate';
import {
  TrashIcon,
  StarIcon as StarIconOutline,
  NoSymbolIcon,
  ArrowPathIcon,
  CheckIcon,
  ClipboardDocumentIcon,
  ExclamationTriangleIcon,
} from '@heroicons/react/24/outline';
import { StarIcon as StarIconSolid } from '@heroicons/react/24/solid';
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
  const reprocessMutation = useReprocessArticles();

  // "Error": no severity label (not even Önemsiz) and not currently being processed
  const isError = !article.priority && article.importance !== 'unimportant'
    && article.status !== 'pending' && article.status !== 'scraped';

  const handleToggleExpand = () => {
    setExpanded(!expanded);
  };

  const handleCopySummary = async (text: string) => {
    const ok = await copyToClipboard(text);
    if (ok) {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
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

  const timeAgo = article.published_at ? formatPublishedAt(article.published_at) : null;

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
        <TrashIcon />
      </button>

      <button
        className={`favorite-icon-btn${article.is_starred ? ' favorite-icon-btn--active' : ''}`}
        onClick={() => setStarredMutation.mutate({ articleId: article.id, starred: !article.is_starred })}
        disabled={setStarredMutation.isPending}
        title={article.is_starred ? 'Favorilerden çıkar' : 'Favorilere ekle'}
        aria-label={article.is_starred ? 'Favorilerden çıkar' : 'Favorilere ekle'}
      >
        {article.is_starred ? <StarIconSolid /> : <StarIconOutline />}
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
          <span className="badge unimportant-badge"><NoSymbolIcon /> Önemsiz</span>
        )}
        {isError && (
          <span className="badge error-badge"><ExclamationTriangleIcon /> Hata</span>
        )}
        {article.priority && (
          <span className={`badge priority-badge priority-${article.priority}`}>
            <span className="priority-dot" />
            {article.priority === 'high' ? 'Yüksek' : article.priority === 'med' ? 'Orta' : 'Düşük'}
          </span>
        )}
        {article.topics.map((topic) => {
          const tint = withAlpha(topic.color, '1a');
          const border = withAlpha(topic.color, '40');
          return (
            <span
              key={topic.id}
              className="badge topic-badge"
              style={tint && border ? { backgroundColor: tint, borderColor: border } : undefined}
            >
              {topic.color && <span className="topic-dot" style={{ backgroundColor: topic.color }} />}
              {topic.name}
            </span>
          );
        })}
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
          {contentLoading ? <><ArrowPathIcon className="spin-icon" /> Yükleniyor...</> : 'Orijinal İçerik'}
        </button>
        <a
          href={article.url}
          target="_blank"
          rel="noopener noreferrer"
          className="btn btn-outline"
        >
          Kaynağı aç →
        </a>
        {isError && (
          <button
            className="btn btn-outline"
            onClick={() => reprocessMutation.mutate({ article_ids: [article.id] })}
            disabled={reprocessMutation.isPending}
          >
            <ArrowPathIcon className={reprocessMutation.isPending ? 'spin-icon' : undefined} /> Tekrar dene
          </button>
        )}
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
                className={`copy-summary-btn${copied ? ' copy-summary-btn--copied' : ''}`}
                onClick={() => handleCopySummary(summary.summary_text)}
                title={copied ? 'Kopyalandı' : 'Özeti kopyala'}
                aria-label={copied ? 'Kopyalandı' : 'Özeti kopyala'}
              >
                {copied ? <CheckIcon className="copy-summary-icon" /> : <ClipboardDocumentIcon className="copy-summary-icon" />}
              </button>
            )}
          </div>

          {summaryLoading ? (
            <p className="text-muted"><ArrowPathIcon className="spin-icon" /> Özet yükleniyor...</p>
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
