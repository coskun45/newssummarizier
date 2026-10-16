import type { AnalysisTotals } from '../../types';

interface AnalysisKpisProps {
  totals: AnalysisTotals;
  days: number;
}

const percent = (ratio: number) => `%${Math.round(ratio * 100)}`;

function AnalysisKpis({ totals, days }: AnalysisKpisProps) {
  const prev = totals.prev_high_ratio;
  const delta = prev === null ? null : Math.round((totals.high_ratio - prev) * 100);

  return (
    <div className="analysis-kpis">
      <div className="analysis-kpi">
        <span className="analysis-kpi-value">{totals.total}</span>
        <span className="analysis-kpi-label">Toplam haber</span>
      </div>
      <div className="analysis-kpi analysis-kpi--high">
        <span className="analysis-kpi-value">{totals.high}</span>
        <span className="analysis-kpi-label">Yüksek</span>
      </div>
      <div className="analysis-kpi analysis-kpi--med">
        <span className="analysis-kpi-value">{totals.med}</span>
        <span className="analysis-kpi-label">Orta</span>
      </div>
      <div className="analysis-kpi analysis-kpi--low">
        <span className="analysis-kpi-value">{totals.low}</span>
        <span className="analysis-kpi-label">Düşük</span>
      </div>
      <div
        className="analysis-kpi analysis-kpi--tension"
        title="Yüksek önemli haberlerin toplam içindeki oranı"
      >
        <span className="analysis-kpi-value">{percent(totals.high_ratio)}</span>
        <span className="analysis-kpi-label">Gündem gerginliği</span>
        <span className="analysis-kpi-delta">
          {delta === null
            ? 'Önceki dönem verisi yok'
            : `${delta > 0 ? '↑' : delta < 0 ? '↓' : '→'} ${Math.abs(delta)} puan (önceki ${days} gün)`}
        </span>
      </div>
    </div>
  );
}

export default AnalysisKpis;
