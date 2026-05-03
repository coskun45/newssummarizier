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
  priorityCounts: Record<string, number>;
  unimportantCount?: number;
}

const PRIORITIES = [
  { value: 'high', label: 'Yüksek' },
  { value: 'med',  label: 'Orta' },
  { value: 'low',  label: 'Düşük' },
];

function TopicFilter({ topics, selectedTopics, onTopicToggle, importanceMode, onImportanceModeChange, selectedPriority, onPriorityChange, priorityCounts, unimportantCount }: TopicFilterProps) {
  const [openCategories, setOpenCategories] = useState(true);
  const [openPriority, setOpenPriority] = useState(true);

  const handleUnimportantClick = () => {
    const next = importanceMode === 'unimportant' ? null : 'unimportant';
    onImportanceModeChange(next);
  };

  const handleCategoriesClick = () => {
    const next = !openCategories;
    setOpenCategories(next);
    if (!next) onImportanceModeChange(null);
  };

  const isCategoriesActive = importanceMode === 'important' || selectedTopics.length > 0;
  const isPriorityActive = !!selectedPriority;

  return (
    <div className="topic-filter">
      {/* Önem Seviyesi — accordion */}
      <button
        className={`importance-header ${isPriorityActive ? 'active' : ''}`}
        onClick={() => setOpenPriority(v => !v)}
      >
        <span className="importance-label">Önem Seviyesi</span>
        <span className="importance-chevron">{openPriority ? '▲' : '▼'}</span>
      </button>

      {openPriority && (
        <div className="importance-topics">
          {PRIORITIES.map((p) => (
            <label key={p.value} className="topic-item">
              <input
                type="checkbox"
                checked={selectedPriority === p.value}
                onChange={() => onPriorityChange(selectedPriority === p.value ? null : p.value)}
              />
              <span className="topic-name">{p.label}</span>
              {priorityCounts[p.value] !== undefined && (
                <span className="topic-count">{priorityCounts[p.value]}</span>
              )}
            </label>
          ))}
        </div>
      )}

      {/* Kategoriler — accordion */}
      <button
        className={`importance-header ${isCategoriesActive ? 'active' : ''}`}
        onClick={handleCategoriesClick}
      >
        <span className="importance-label">Kategoriler</span>
        <span className="importance-chevron">{openCategories ? '▲' : '▼'}</span>
      </button>

      {openCategories && (
        <div className="importance-topics">
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

          {/* Önemsiz */}
          <label className="topic-item">
            <input
              type="checkbox"
              checked={importanceMode === 'unimportant'}
              onChange={handleUnimportantClick}
            />
            <span className="topic-name">Önemsiz</span>
            {unimportantCount !== undefined && (
              <span className="topic-count">{unimportantCount}</span>
            )}
          </label>
        </div>
      )}
    </div>
  );
}

export default TopicFilter;
