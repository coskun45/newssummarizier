import { useState } from 'react';
import { formatDistanceToNow } from 'date-fns';
import { de } from 'date-fns/locale';
import type { Article } from '../../types';
import { useSummary, useArticle } from '../../hooks/useApi';
import ContentModal from '../ContentModal/ContentModal';
import './ArticleCard.css';

interface ArticleCardProps {
  article: Article;
}

function ArticleCard({ article }: ArticleCardProps) {
  const [expanded, setExpanded] = useState(false);
  const [showContent, setShowContent] = useState(false);
  const [summaryType, setSummaryType] = useState<'brief' | 'standard' | 'detailed'>('standard');

  const { data: summary, isLoading: summaryLoading } = useSummary(
    expanded ? article.id : null,
    summaryType
  );

  const { data: articleDetail, isLoading: contentLoading } = useArticle(
    showContent ? article.id : null
  );

  const timeAgo = article.published_at
    ? formatDistanceToNow(new Date(article.published_at), { addSuffix: true, locale: de })
    : null;

  return (
    <div className="article-card">
      <div className="article-header">
        <h2 className="article-title">{article.title}</h2>
        {article.author && <p className="article-author">von {article.author}</p>}
        <div className="article-meta">
          {timeAgo && <span className="article-time">{timeAgo}</span>}
          <span className="article-status">{article.status}</span>
        </div>
      </div>

      {article.topics.length > 0 && (
        <div className="article-topics">
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
      )}

      <div className="article-actions">
        <button
          className="btn btn-primary"
          onClick={() => setExpanded(!expanded)}
        >
          {expanded ? 'Weniger anzeigen' : 'Zusammenfassung anzeigen'}
        </button>
        <button
          className="btn btn-secondary"
          onClick={() => setShowContent(true)}
          disabled={contentLoading}
        >
          {contentLoading ? '⏳ Lade...' : 'Original Inhalt'}
        </button>
        <a
          href={article.url}
          target="_blank"
          rel="noopener noreferrer"
          className="btn btn-outline"
        >
          Quelle öffnen →
        </a>
      </div>

      <ContentModal
        isOpen={showContent}
        onClose={() => setShowContent(false)}
        title={article.title}
        content={articleDetail?.cleaned_content || articleDetail?.raw_content || null}
      />

      {expanded && (
        <div className="article-summary">
          <div className="summary-controls">
            <button
              className={`summary-type-btn ${summaryType === 'brief' ? 'active' : ''}`}
              onClick={() => setSummaryType('brief')}
            >
              Kurz
            </button>
            <button
              className={`summary-type-btn ${summaryType === 'standard' ? 'active' : ''}`}
              onClick={() => setSummaryType('standard')}
            >
              Standard
            </button>
            <button
              className={`summary-type-btn ${summaryType === 'detailed' ? 'active' : ''}`}
              onClick={() => setSummaryType('detailed')}
            >
              Detailliert
            </button>
          </div>

          {summaryLoading ? (
            <p className="text-muted">⏳ Lade Zusammenfassung...</p>
          ) : summary ? (
            <div className="summary-content">
              <p>{summary.summary_text}</p>
              <div className="summary-meta">
                <span className="text-small text-muted">
                  Modell: {summary.model_used} | Kosten: ${summary.cost.toFixed(4)}
                </span>
              </div>
            </div>
          ) : (
            <p className="text-error">Zusammenfassung nicht verfügbar</p>
          )}
        </div>
      )}
    </div>
  );
}

export default ArticleCard;
