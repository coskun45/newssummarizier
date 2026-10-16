import { useState } from 'react';
import { ChartBarIcon } from '@heroicons/react/24/outline';
import { useAnalysisStats } from '../../hooks/useApi';
import type { AnalysisRange } from '../../types';
import AnalysisKpis from './AnalysisKpis';
import PriorityTrendChart from './PriorityTrendChart';
import TopicPriorityHeatmap from './TopicPriorityHeatmap';
import FeedProfileTable from './FeedProfileTable';
import './Analysis.css';

const RANGES: AnalysisRange[] = [7, 30, 90];

function Analysis() {
  const [days, setDays] = useState<AnalysisRange>(30);
  const { data, isError, isFetching } = useAnalysisStats(days);

  return (
    <section className="analysis" aria-busy={isFetching}>
      <header className="analysis-header">
        <h2 className="analysis-title">
          <ChartBarIcon className="analysis-title-icon" aria-hidden="true" />
          Analiz
        </h2>
        <div className="analysis-range" role="group" aria-label="Zaman aralığı">
          {RANGES.map((range) => (
            <button
              key={range}
              type="button"
              className={`analysis-range-btn${range === days ? ' analysis-range-btn--active' : ''}`}
              aria-pressed={range === days}
              onClick={() => setDays(range)}
            >
              {range} gün
            </button>
          ))}
        </div>
      </header>

      {/* A failed background refetch keeps the last good data (React Query sets isError but
          keeps `data`), so only a range with no data at all gets the full error state. */}
      {data && isError && (
        <p className="analysis-stale" role="status">
          Veriler yenilenemedi; son alınan veriler gösteriliyor.
        </p>
      )}

      {!data ? (
        isError ? (
          <p className="analysis-state analysis-state--error">Analiz verileri yüklenemedi.</p>
        ) : (
          <p className="analysis-state">Yükleniyor...</p>
        )
      ) : data.totals.total === 0 ? (
        <p className="analysis-state">Bu aralıkta analiz edilecek haber yok.</p>
      ) : (
        <>
          <AnalysisKpis totals={data.totals} days={data.days} />
          <div className="analysis-card">
            <h3 className="analysis-card-title">Önem trendi</h3>
            <PriorityTrendChart trend={data.trend} />
          </div>
          <div className="analysis-grid">
            <div className="analysis-card">
              <h3 className="analysis-card-title">Konu × önem</h3>
              <TopicPriorityHeatmap topics={data.topics} />
            </div>
            <div className="analysis-card">
              <h3 className="analysis-card-title">Kaynak profili</h3>
              <FeedProfileTable feeds={data.feeds} />
            </div>
          </div>
        </>
      )}
    </section>
  );
}

export default Analysis;
