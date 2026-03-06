import { useState } from 'react';
import { formatDistanceToNow } from 'date-fns';
import { tr } from 'date-fns/locale';
import type { Article } from '../../types';
import { useSummary, useArticle, useDeleteArticle } from '../../hooks/useApi';
import ContentModal from '../ContentModal/ContentModal';
import './ArticleCard.css';

interface ArticleCardProps {
  article: Article;
}


function ArticleCard({ article }: ArticleCardProps) {
  const [expanded, setExpanded] = useState(false);
  const [showContent, setShowContent] = useState(false);
  const [summaryType, setSummaryType] = useState<'brief' | 'standard' | 'detailed'>('standard');
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);

  const deleteArticleMutation = useDeleteArticle();

  const { data: summary, isLoading: summaryLoading } = useSummary(
    expanded ? article.id : null,
    summaryType
  );

  const { data: articleDetail, isLoading: contentLoading } = useArticle(
    showContent ? article.id : null
  );

  const timeAgo = article.published_at
    ? formatDistanceToNow(new Date(article.published_at), { addSuffix: true, locale: tr })
    : null;

  return (
    <div className="article-card">
      <button
        className="delete-icon-btn"
        title="Sil"
        onClick={() => setShowDeleteConfirm(true)}
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

      {showDeleteConfirm && (
        <div className="delete-confirm-popup" style={{ position: 'fixed', top: 0, left: 0, width: '100vw', height: '100vh', background: 'rgba(0,0,0,0.3)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1000 }}>
          <div style={{ background: '#fff', padding: 24, borderRadius: 8, boxShadow: '0 2px 8px rgba(0,0,0,0.2)', minWidth: 280, textAlign: 'center' }}>
            <p>Bu makaleyi silmek istediğinize emin misiniz?</p>
            <button
              onClick={() => {
                deleteArticleMutation.mutate(article.id);
                setShowDeleteConfirm(false);
              }}
              style={{ marginRight: 12, background: '#e53935', color: '#fff', border: 'none', padding: '8px 16px', borderRadius: 4, cursor: 'pointer' }}
              disabled={deleteArticleMutation.isPending}
            >
              Sil
            </button>
            <button
              onClick={() => setShowDeleteConfirm(false)}
              style={{ background: '#ccc', color: '#333', border: 'none', padding: '8px 16px', borderRadius: 4, cursor: 'pointer' }}
            >
              Vazgeç
            </button>
          </div>
        </div>
      )}
      <div className="article-header">
        <h2 className="article-title">{article.title}</h2>
        {article.author && <p className="article-author">Yazar: {article.author}</p>}
        <div className="article-meta">
          {timeAgo && <span className="article-time">{timeAgo}</span>}
          <span className="article-status">{article.status}</span>
        </div>
      </div>

      <div className="article-badges">
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
        <button
          className="btn btn-primary"
          onClick={() => setExpanded(!expanded)}
        >
          {expanded ? 'Daha az göster' : 'Özeti göster'}
        </button>
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
        {/* Delete button moved to top right as icon */}
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
              Kısa
            </button>
            <button
              className={`summary-type-btn ${summaryType === 'standard' ? 'active' : ''}`}
              onClick={() => setSummaryType('standard')}
            >
              Standart
            </button>
            <button
              className={`summary-type-btn ${summaryType === 'detailed' ? 'active' : ''}`}
              onClick={() => setSummaryType('detailed')}
            >
              Detaylı
            </button>
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
