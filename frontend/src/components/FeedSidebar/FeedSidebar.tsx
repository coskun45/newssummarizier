import { useState } from 'react';
import { PlusIcon, TrashIcon, RssIcon } from '@heroicons/react/24/outline';
import type { Feed } from '../../types';
import './FeedSidebar.css';

interface FeedSidebarProps {
  feeds: Feed[];
  selectedFeedId: number | null;
  onSelectFeed: (id: number | null) => void;
  onCreateFeed: (url: string, title?: string) => void;
  onDeleteFeed: (id: number) => void;
  isCreating: boolean;
}

function FeedSidebar({ feeds, selectedFeedId, onSelectFeed, onCreateFeed, onDeleteFeed, isCreating }: FeedSidebarProps) {
  const [showAddForm, setShowAddForm] = useState(false);
  const [newUrl, setNewUrl] = useState('');
  const [newTitle, setNewTitle] = useState('');
  const [deleteConfirmId, setDeleteConfirmId] = useState<number | null>(null);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!newUrl.trim()) return;
    onCreateFeed(newUrl.trim(), newTitle.trim() || undefined);
    setNewUrl('');
    setNewTitle('');
    setShowAddForm(false);
  };

  const getFeedLabel = (feed: Feed) => {
    if (feed.title) return feed.title;
    try {
      return new URL(feed.url).hostname.replace('www.', '');
    } catch {
      return feed.url;
    }
  };

  return (
    <div className="feed-sidebar">
      <div className="feed-sidebar-header">
        <h2 className="feed-sidebar-title">
          <RssIcon className="feed-sidebar-icon" />
          RSS Beslemeleri
        </h2>
        <button
          className="feed-add-btn"
          onClick={() => setShowAddForm((v) => !v)}
          title="Besleme ekle"
        >
          <PlusIcon />
        </button>
      </div>

      {showAddForm && (
        <form className="feed-add-form" onSubmit={handleSubmit}>
          <input
            className="feed-input"
            type="url"
            placeholder="RSS URL..."
            value={newUrl}
            onChange={(e) => setNewUrl(e.target.value)}
            required
            autoFocus
          />
          <input
            className="feed-input"
            type="text"
            placeholder="Ad (isteğe bağlı)"
            value={newTitle}
            onChange={(e) => setNewTitle(e.target.value)}
          />
          <div className="feed-add-actions">
            <button type="submit" className="feed-submit-btn" disabled={isCreating}>
              {isCreating ? 'Ekleniyor...' : 'Ekle'}
            </button>
            <button type="button" className="feed-cancel-btn" onClick={() => setShowAddForm(false)}>
              İptal
            </button>
          </div>
        </form>
      )}

      <ul className="feed-list">
        <li
          className={`feed-item ${selectedFeedId === null ? 'feed-item--active' : ''}`}
          onClick={() => onSelectFeed(null)}
        >
          <span className="feed-item-label">Tüm Beslemeler</span>
          <span className="feed-item-count">{feeds.length}</span>
        </li>

        {feeds.map((feed) => (
          <li
            key={feed.id}
            className={`feed-item ${selectedFeedId === feed.id ? 'feed-item--active' : ''}`}
            onClick={() => onSelectFeed(feed.id)}
          >
            <span className="feed-item-label" title={feed.url}>
              {getFeedLabel(feed)}
            </span>
            {deleteConfirmId === feed.id ? (
              <span className="feed-delete-confirm">
                <button
                  className="feed-delete-yes"
                  onClick={(e) => { e.stopPropagation(); onDeleteFeed(feed.id); setDeleteConfirmId(null); }}
                >
                  Sil
                </button>
                <button
                  className="feed-delete-no"
                  onClick={(e) => { e.stopPropagation(); setDeleteConfirmId(null); }}
                >
                  Hayır
                </button>
              </span>
            ) : (
              <button
                className="feed-delete-btn"
                onClick={(e) => { e.stopPropagation(); setDeleteConfirmId(feed.id); }}
                title="Beslemeyi sil"
              >
                <TrashIcon />
              </button>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}

export default FeedSidebar;
