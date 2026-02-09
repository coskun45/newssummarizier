import type { Topic } from '../../types';
import './TopicFilter.css';

interface TopicFilterProps {
  topics: Topic[];
  selectedTopics: number[];
  onTopicToggle: (topicId: number) => void;
}

function TopicFilter({ topics, selectedTopics, onTopicToggle }: TopicFilterProps) {
  return (
    <div className="topic-filter">
      <h3 className="filter-title">Themen</h3>
      <div className="topic-list">
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
    </div>
  );
}

export default TopicFilter;
