import type { AnalysisTopic } from '../../types';
import { PRIORITIES } from '../../constants/priorities';

interface TopicPriorityHeatmapProps {
  topics: AnalysisTopic[];
}

const priorityKeys = ['high', 'med', 'low'] as const;

function TopicPriorityHeatmap({ topics }: TopicPriorityHeatmapProps) {
  if (topics.length === 0) {
    return <p className="analysis-empty">Bu aralıkta konu atanmış haber yok.</p>;
  }

  return (
    <div className="analysis-table-wrap">
      <table className="analysis-table">
        <thead>
          <tr>
            <th scope="col">Konu</th>
            {PRIORITIES.map((p) => (
              <th key={p.value} scope="col" className="analysis-num">{p.label}</th>
            ))}
            <th scope="col" className="analysis-num">Toplam</th>
          </tr>
        </thead>
        <tbody>
          {topics.map((topic) => (
            <tr key={topic.topic_id}>
              <th scope="row" className="analysis-topic-name">
                <span
                  className="analysis-topic-dot"
                  style={{ background: topic.color ?? 'var(--color-text-muted)' }}
                  aria-hidden="true"
                />
                {topic.name}
              </th>
              {priorityKeys.map((key) => (
                <td key={key} className="analysis-num analysis-heat-cell">
                  <span
                    className={`analysis-heat-bg analysis-swatch--${key}`}
                    style={{ opacity: topic.total ? (topic[key] / topic.total) * 0.85 : 0 }}
                    aria-hidden="true"
                  />
                  <span className="analysis-heat-value">{topic[key]}</span>
                </td>
              ))}
              <td className="analysis-num analysis-strong">{topic.total}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default TopicPriorityHeatmap;
