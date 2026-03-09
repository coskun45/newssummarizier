import { useState } from 'react';
import { RssIcon } from '@heroicons/react/24/outline';
import type { Feed } from '../../types';
import './FeedSidebar.css';

interface FeedSidebarProps {
  feeds: Feed[];
  selectedFeedIds: number[];
  feedCounts: Record<string, number>;
  onFeedToggle: (id: number) => void;
  onClearFeeds: () => void;
}

function FeedSidebar({ feeds, selectedFeedIds, feedCounts, onFeedToggle, onClearFeeds }: FeedSidebarProps) {
  const [open, setOpen] = useState(true);

  const getFeedLabel = (feed: Feed) => {
    if (feed.title) return feed.title;
    try {
      return new URL(feed.url).hostname.replace('www.', '');
    } catch {
      return feed.url;
    }
  };

  const allSelected = selectedFeedIds.length === 0;

  return (
    <div className="feed-sidebar">
      <button
        className={`feed-accordion-header ${selectedFeedIds.length > 0 ? 'feed-accordion-active' : ''}`}
        onClick={() => setOpen(v => !v)}
      >
        <span className="feed-accordion-label">
          RSS Beslemeleri</span>
        <span className="importance-chevron">{open ? '▲' : '▼'}</span>
      </button>

      {open && (
        <div className="feed-accordion-content">
          <label className="topic-item feed-item-all">
            <input
              type="checkbox"
              checked={allSelected}
              onChange={onClearFeeds}
            />
            <span className="topic-name">Tüm Beslemeler</span>
            <span className="topic-count">{feeds.length}</span>
          </label>

          {feeds.map(feed => (
            <label key={feed.id} className="topic-item">
              <input
                type="checkbox"
                checked={selectedFeedIds.includes(feed.id)}
                onChange={() => onFeedToggle(feed.id)}
              />
              <span className="topic-name" title={feed.url}>
                {getFeedLabel(feed)}
              </span>
              {feedCounts[String(feed.id)] !== undefined && (
                <span className="topic-count">{feedCounts[String(feed.id)]}</span>
              )}
            </label>
          ))}
        </div>
      )}
    </div>
  );
}

export default FeedSidebar;
