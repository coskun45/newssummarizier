import { useState } from 'react';
import { ChevronUpIcon, ChevronDownIcon } from '@heroicons/react/24/outline';
import type { ArticleOrigin } from '../../types';
import './OriginFilter.css';

// Sidebar "Kaynak Türü" groups — a filter on top of the others, the articles stay in every list.
const ORIGINS: { value: ArticleOrigin; label: string }[] = [
  { value: 'free_match', label: 'Ücretsiz kaynaktan' },
  { value: 'unavailable', label: 'İçerik alınamadı' },
  { value: 'manual', label: 'Manuel eklenen' },
];

interface OriginFilterProps {
  selectedOrigin: ArticleOrigin | null;
  onOriginChange: (origin: ArticleOrigin | null) => void;
  /** Unread counts per group; omitted while the counts are loading. */
  originCounts?: Record<ArticleOrigin, number>;
}

/** The first sidebar section. Single-select, like the priorities: picking one unpicks the other.
 *  Reuses the sidebar accordion classes (`importance-header`, `topic-item`) from TopicFilter.css. */
function OriginFilter({ selectedOrigin, onOriginChange, originCounts }: OriginFilterProps) {
  const [open, setOpen] = useState(true);

  return (
    <div className="origin-filter">
      <button
        className={`importance-header ${selectedOrigin ? 'active' : ''}`}
        onClick={() => setOpen(!open)}
      >
        <span className="importance-label">Kaynak Türü</span>
        <span className="importance-chevron">{open ? <ChevronUpIcon /> : <ChevronDownIcon />}</span>
      </button>

      {open && (
        <div className="importance-topics">
          {ORIGINS.map((o) => (
            <label key={o.value} className="topic-item">
              <input
                type="checkbox"
                checked={selectedOrigin === o.value}
                onChange={() => onOriginChange(selectedOrigin === o.value ? null : o.value)}
              />
              <span className="topic-name">{o.label}</span>
              {originCounts && <span className="topic-count">{originCounts[o.value]}</span>}
            </label>
          ))}
        </div>
      )}
    </div>
  );
}

export default OriginFilter;
