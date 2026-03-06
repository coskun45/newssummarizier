import { useState } from 'react';
import type { Topic } from '../../types';
import './TopicFilter.css';

interface TopicFilterProps {
  topics: Topic[];
  selectedTopics: number[];
  onTopicToggle: (topicId: number) => void;
  importanceMode: 'important' | 'unimportant' | null;
  onImportanceModeChange: (mode: 'important' | 'unimportant' | null) => void;
  selectedPriority: string | null;
  onPriorityChange: (priority: string | null) => void;
}

const PRIORITIES = [
  { value: 'high', label: 'Yüksek' },
  { value: 'med',  label: 'Orta' },
  { value: 'low',  label: 'Düşük' },
];

function TopicFilter({ topics, selectedTopics, onTopicToggle, importanceMode, onImportanceModeChange, selectedPriority, onPriorityChange }: TopicFilterProps) {
  const [open, setOpen] = useState(true);

  const handleUnimportantClick = () => {
    const next = importanceMode === 'unimportant' ? null : 'unimportant';
    onImportanceModeChange(next);
    if (next === 'unimportant') setOpen(false);
  };

  const handleImportantClick = () => {
    const next = !open;
    setOpen(next);
    onImportanceModeChange(next ? 'important' : null);
  };

  const isImportantActive = importanceMode === 'important' || selectedTopics.length > 0 || !!selectedPriority;

  return (
    <div className="topic-filter">
      {/* Önemsiz — üstte, basit tıklanabilir satır */}
      <button
        className={`importance-header unimportant-btn ${importanceMode === 'unimportant' ? 'unimportant-active' : ''}`}
        onClick={handleUnimportantClick}
      >
        <span className="importance-label">Önemsiz</span>
      </button>

      <div className="importance-divider" />

      {/* Önemli — accordion */}
      <button
        className={`importance-header ${isImportantActive ? 'active' : ''}`}
        onClick={handleImportantClick}
      >
        <span className="importance-label">Önemli</span>
        <span className="importance-chevron">{open ? '▲' : '▼'}</span>
      </button>

      {open && (
        <div className="importance-topics">
          {/* Öncelik filtresi */}
          <div className="priority-filter-row">
            {PRIORITIES.map((p) => (
              <button
                key={p.value}
                className={`priority-filter-btn priority-filter-${p.value} ${selectedPriority === p.value ? 'priority-filter-active' : ''}`}
                onClick={() => onPriorityChange(selectedPriority === p.value ? null : p.value)}
              >
                {p.label}
              </button>
            ))}
          </div>

          <div className="importance-divider" style={{ margin: '0.4rem 0' }} />

          {/* Konu listesi */}
          {topics.map((topic) => (
            <label key={topic.id} className="topic-item">
              <input
                type="checkbox"
                checked={selectedTopics.includes(topic.id)}
                onChange={() => onTopicToggle(topic.id)}
              />
              <span className="topic-name">{topic.name}</span>
              {topic.article_count !== undefined && (
                <span className="topic-count">{topic.article_count}</span>
              )}
            </label>
          ))}
        </div>
      )}
    </div>
  );
}

export default TopicFilter;
