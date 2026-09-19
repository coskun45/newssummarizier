import { useEffect, useState } from 'react';
import { useArticles, useFeeds } from '../../hooks/useApi';
import { formatPublishedAt } from '../../utils/formatDate';
import Pagination from '../Pagination/Pagination';
import './PlaygroundArticlePicker.css';

const PAGE_SIZE = 12;

interface PlaygroundArticlePickerProps {
  selectedId: number | null;
  onSelect: (articleId: number) => void;
}

function PlaygroundArticlePicker({ selectedId, onSelect }: PlaygroundArticlePickerProps) {
  const [feedId, setFeedId] = useState<number | undefined>(undefined);
  const [searchInput, setSearchInput] = useState('');
  const [search, setSearch] = useState('');
  const [page, setPage] = useState(1);

  const { data: feeds } = useFeeds();
  const { data, isLoading, isError } = useArticles({
    feed_id: feedId,
    search: search || undefined,
    skip: (page - 1) * PAGE_SIZE,
    limit: PAGE_SIZE,
  });

  // Debounce the search box so every keystroke doesn't hit the API.
  useEffect(() => {
    const timer = setTimeout(() => {
      setSearch(searchInput.trim());
      setPage(1);
    }, 300);
    return () => clearTimeout(timer);
  }, [searchInput]);

  const totalPages = data ? Math.max(1, Math.ceil(data.total / PAGE_SIZE)) : 1;

  return (
    <section className="playground-picker">
      <h2 className="playground-picker-title">Haber seç</h2>

      <label className="playground-picker-label" htmlFor="playground-feed">RSS kaynağı</label>
      <select
        id="playground-feed"
        className="select"
        value={feedId ?? ''}
        onChange={(e) => {
          setFeedId(e.target.value ? Number(e.target.value) : undefined);
          setPage(1);
        }}
      >
        <option value="">Tüm kaynaklar</option>
        {feeds?.map((feed) => (
          <option key={feed.id} value={feed.id}>{feed.title || feed.url}</option>
        ))}
      </select>

      <label className="playground-picker-label" htmlFor="playground-search">Ara</label>
      <input
        id="playground-search"
        className="input"
        type="search"
        placeholder="Başlık veya içerikte ara…"
        value={searchInput}
        onChange={(e) => setSearchInput(e.target.value)}
      />

      {isLoading && <p className="playground-picker-empty">Yükleniyor…</p>}
      {isError && <p className="playground-picker-empty">Haberler yüklenemedi.</p>}
      {data && data.articles.length === 0 && <p className="playground-picker-empty">Haber bulunamadı.</p>}

      <ul className="playground-picker-list">
        {data?.articles.map((article) => (
          <li key={article.id}>
            <button
              type="button"
              className={`playground-picker-item${article.id === selectedId ? ' playground-picker-item--selected' : ''}`}
              aria-pressed={article.id === selectedId}
              onClick={() => onSelect(article.id)}
            >
              <span className="playground-picker-item-title">{article.title}</span>
              <span className="playground-picker-item-meta">
                {article.published_at && <span>{formatPublishedAt(article.published_at)}</span>}
                <span className="badge playground-picker-status">{article.status}</span>
                {article.priority && <span className="badge playground-picker-status">{article.priority}</span>}
              </span>
            </button>
          </li>
        ))}
      </ul>

      {data && data.total > PAGE_SIZE && (
        <Pagination currentPage={page} totalPages={totalPages} onPageChange={setPage} />
      )}
    </section>
  );
}

export default PlaygroundArticlePicker;
