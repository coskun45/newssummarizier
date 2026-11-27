import { useState } from 'react';
import { ChevronUpIcon, ChevronDownIcon } from '@heroicons/react/24/outline';
import type { ArticleOrigin, ItemGroup, Topic } from '../../types';
import GroupedChecklist from '../GroupedChecklist/GroupedChecklist';
import { PRIORITIES } from '../../constants/priorities';
import './TopicFilter.css';

// Sidebar "Kaynak Türü" groups — a filter on top of the others, the articles stay in every list.
const ORIGINS: { value: ArticleOrigin; label: string }[] = [
  { value: 'free_match', label: 'Ücretsiz kaynaktan' },
  { value: 'manual', label: 'Manuel eklenen' },
];

interface TopicFilterProps {
  topics: Topic[];
  topicGroups?: ItemGroup[];
  selectedTopics: number[];
  onTopicToggle: (topicId: number) => void;
  onTopicGroupToggle: (topicIds: number[], select: boolean) => void;
  importanceMode: 'important' | 'unimportant' | null;
  onImportanceModeChange: (mode: 'important' | 'unimportant' | null) => void;
  selectedPriority: string | null;
  onPriorityChange: (priority: string | null) => void;
  priorityCounts: Record<string, number>;
  unimportantCount?: number;
  selectedOrigin?: ArticleOrigin | null;
  onOriginChange?: (origin: ArticleOrigin | null) => void;
  originCounts?: Record<ArticleOrigin, number>;
}

function TopicFilter({ topics, topicGroups = [], selectedTopics, onTopicToggle, onTopicGroupToggle, importanceMode, onImportanceModeChange, selectedPriority, onPriorityChange, priorityCounts, unimportantCount, selectedOrigin = null, onOriginChange, originCounts }: TopicFilterProps) {
  const [openCategories, setOpenCategories] = useState(true);
  const [openPriority, setOpenPriority] = useState(true);
  const [openOrigin, setOpenOrigin] = useState(true);

  const handleUnimportantClick = () => {
    const next = importanceMode === 'unimportant' ? null : 'unimportant';
    onImportanceModeChange(next);
  };

  const handlePriorityClick = () => {
    const next = !openPriority;
    setOpenPriority(next);
    if (!next && importanceMode === 'unimportant') onImportanceModeChange(null);
  };

  const handleCategoriesClick = () => {
    const next = !openCategories;
    setOpenCategories(next);
    if (!next && importanceMode === 'important') onImportanceModeChange(null);
  };

  const isCategoriesActive = importanceMode === 'important' || selectedTopics.length > 0;
  const isPriorityActive = !!selectedPriority || importanceMode === 'unimportant';

  return (
    <div className="topic-filter">
      {/* Önem Seviyesi — accordion */}
      <button
        className={`importance-header ${isPriorityActive ? 'active' : ''}`}
        onClick={handlePriorityClick}
      >
        <span className="importance-label">Önem Seviyesi</span>
        <span className="importance-chevron">{openPriority ? <ChevronUpIcon /> : <ChevronDownIcon />}</span>
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

      {/* Kaynak Türü — accordion (only when the parent handles it) */}
      {onOriginChange && (
        <>
          <button
            className={`importance-header ${selectedOrigin ? 'active' : ''}`}
            onClick={() => setOpenOrigin(!openOrigin)}
          >
            <span className="importance-label">Kaynak Türü</span>
            <span className="importance-chevron">{openOrigin ? <ChevronUpIcon /> : <ChevronDownIcon />}</span>
          </button>

          {openOrigin && (
            <div className="importance-topics">
              {ORIGINS.map((o) => (
                <label key={o.value} className="topic-item">
                  <input
                    type="checkbox"
                    checked={selectedOrigin === o.value}
                    onChange={() => onOriginChange(selectedOrigin === o.value ? null : o.value)}
                  />
                  <span className="topic-name">{o.label}</span>
                  {originCounts && (
                    <span className="topic-count">{originCounts[o.value]}</span>
                  )}
                </label>
              ))}
            </div>
          )}
        </>
      )}

      {/* Kategoriler — accordion */}
      <button
        className={`importance-header ${isCategoriesActive ? 'active' : ''}`}
        onClick={handleCategoriesClick}
      >
        <span className="importance-label">Kategoriler</span>
        <span className="importance-chevron">{openCategories ? <ChevronUpIcon /> : <ChevronDownIcon />}</span>
      </button>

      {openCategories && (
        <div className="importance-topics">
          <GroupedChecklist
            items={topics.map((topic) => ({
              id: topic.id,
              label: topic.name,
              count: topic.unread_count,
              group_id: topic.group_id,
            }))}
            groups={topicGroups}
            selectedIds={selectedTopics}
            onToggle={onTopicToggle}
            onGroupToggle={onTopicGroupToggle}
          />
        </div>
      )}
    </div>
  );
}

export default TopicFilter;
