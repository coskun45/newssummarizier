import { format, parseISO } from 'date-fns';
import { tr } from 'date-fns/locale';
import type { AnalysisTrendDay } from '../../types';
import { PRIORITIES } from '../../constants/priorities';

interface PriorityTrendChartProps {
  trend: AnalysisTrendDay[];
}

const priorityKeys = ['high', 'med', 'low'] as const;

function PriorityTrendChart({ trend }: PriorityTrendChartProps) {
  const max = Math.max(1, ...trend.map((d) => d.total));
  // Keep roughly 7 date labels regardless of range length.
  const labelEvery = Math.max(1, Math.ceil(trend.length / 7));

  return (
    <div className="analysis-trend">
      <div className="analysis-legend">
        {PRIORITIES.map((p) => (
          <span key={p.value} className="analysis-legend-item">
            <span className={`analysis-swatch analysis-swatch--${p.value}`} />
            {p.label}
          </span>
        ))}
      </div>
      <div
        className="analysis-trend-bars"
        role="img"
        aria-label={`Son ${trend.length} gün önem seviyesine göre haber sayıları`}
      >
        {trend.map((day, i) => {
          // parseISO reads the date-only string as local midnight, so the label is the API's
          // (UTC) day everywhere; `new Date('…T00:00:00Z')` shows the day before west of UTC.
          const date = format(parseISO(day.date), 'd MMM', { locale: tr });
          return (
            <div
              key={day.date}
              className="analysis-trend-day"
              title={`${date}: ${day.high} yüksek, ${day.med} orta, ${day.low} düşük`}
            >
              <div className="analysis-trend-plot">
                <div className="analysis-trend-stack" style={{ height: `${(day.total / max) * 100}%` }}>
                  {priorityKeys.map((key) =>
                    day[key] > 0 ? (
                      <div
                        key={key}
                        className={`analysis-trend-seg analysis-swatch--${key}`}
                        style={{ flexGrow: day[key] }}
                      />
                    ) : null,
                  )}
                </div>
              </div>
              <span className="analysis-trend-label">
                {(trend.length - 1 - i) % labelEvery === 0 ? date : ''}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

export default PriorityTrendChart;
