import { useState } from 'react';
import type { ChatChartSpec } from '../../types';

interface ChatChartProps {
  chart: ChatChartSpec;
}

const WIDTH = 640;
const HEIGHT = 260;
const MARGIN = { top: 12, right: 12, bottom: 40, left: 44 };
const PLOT_W = WIDTH - MARGIN.left - MARGIN.right;
const PLOT_H = HEIGHT - MARGIN.top - MARGIN.bottom;
const MAX_X_LABELS = 8;
const GAP = 2; // surface gap between adjacent bars / stacked segments

// A series named after a severity keeps the app's priority color (as on the Analiz tab);
// anything else takes the categorical slots in fixed order.
const PRIORITY_COLORS: Record<string, string> = {
  high: 'var(--color-priority-high)', 'yüksek': 'var(--color-priority-high)',
  med: 'var(--color-priority-med)', orta: 'var(--color-priority-med)',
  low: 'var(--color-priority-low)', 'düşük': 'var(--color-priority-low)',
};

function seriesColors(names: string[]): string[] {
  let slot = 0;
  return names.map((name) => PRIORITY_COLORS[name.trim().toLocaleLowerCase('tr')]
    ?? `var(--color-chart-${(slot++ % 6) + 1})`);
}

function niceMax(value: number): number {
  if (value <= 0) return 1;
  const magnitude = 10 ** Math.floor(Math.log10(value));
  const step = [1, 2, 2.5, 5, 10].find((m) => m * magnitude >= value / 4) ?? 10;
  return Math.ceil(value / (step * magnitude)) * step * magnitude;
}

function formatNumber(value: number): string {
  return Number.isInteger(value) ? value.toLocaleString('tr-TR') : value.toLocaleString('tr-TR', { maximumFractionDigits: 2 });
}

/** A rectangle with only its top corners rounded, standing on the baseline. */
function barPath(x: number, y: number, w: number, h: number, r = 4): string {
  if (h <= 0 || w <= 0) return '';
  const radius = Math.min(r, w / 2, h);
  return `M${x},${y + h} V${y + radius} Q${x},${y} ${x + radius},${y} H${x + w - radius} Q${x + w},${y} ${x + w},${y + radius} V${y + h} Z`;
}

function ChatChart({ chart }: ChatChartProps) {
  const [hover, setHover] = useState<number | null>(null);
  const [showTable, setShowTable] = useState(false);
  const colors = seriesColors(chart.series.map((s) => s.name));
  const count = chart.x.length;
  const stacked = chart.type === 'stacked_bar';
  const totals = chart.x.map((_, i) => chart.series.reduce((sum, s) => sum + Math.max(0, s.values[i] ?? 0), 0));
  const rawMax = stacked ? Math.max(...totals) : Math.max(...chart.series.flatMap((s) => s.values));
  const max = niceMax(rawMax);
  const y = (value: number) => MARGIN.top + PLOT_H - (Math.max(0, value) / max) * PLOT_H;
  const band = PLOT_W / count;
  const center = (i: number) => MARGIN.left + band * i + band / 2;
  const labelEvery = Math.max(1, Math.ceil(count / MAX_X_LABELS));
  const ticks = [0, 0.25, 0.5, 0.75, 1].map((f) => f * max);
  const barGroupWidth = Math.min(band * 0.7, 56);
  const singleBarWidth = chart.type === 'bar' ? (barGroupWidth - GAP * (chart.series.length - 1)) / chart.series.length : barGroupWidth;

  const tooltipLeft = hover !== null ? `${(center(hover) / WIDTH) * 100}%` : '0';

  return (
    <figure className="chat-chart">
      <figcaption className="chat-chart-header">
        <span className="chat-chart-title">{chart.title}</span>
        <button type="button" className="btn btn-outline btn-sm" onClick={() => setShowTable((v) => !v)}>
          {showTable ? 'Grafik' : 'Tablo'}
        </button>
      </figcaption>

      {chart.series.length > 1 && (
        <div className="chat-chart-legend">
          {chart.series.map((s, i) => (
            <span key={s.name} className="chat-chart-legend-item">
              <span className="chat-chart-swatch" style={{ background: colors[i] }} />
              {s.name}
            </span>
          ))}
        </div>
      )}

      {showTable ? (
        <div className="chat-chart-table-wrap">
          <table className="chat-table">
            <thead>
              <tr>
                <th>{chart.x_label || ''}</th>
                {chart.series.map((s) => <th key={s.name}>{s.name || 'Değer'}</th>)}
              </tr>
            </thead>
            <tbody>
              {chart.x.map((label, i) => (
                <tr key={`${label}-${i}`}>
                  <td>{label}</td>
                  {chart.series.map((s) => <td key={s.name}>{formatNumber(s.values[i] ?? 0)}</td>)}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="chat-chart-plot">
          <svg viewBox={`0 0 ${WIDTH} ${HEIGHT}`} role="img" aria-label={chart.title} onMouseLeave={() => setHover(null)}>
            {ticks.map((t) => (
              <g key={t}>
                <line className="chat-chart-grid" x1={MARGIN.left} x2={WIDTH - MARGIN.right} y1={y(t)} y2={y(t)} />
                <text className="chat-chart-axis" x={MARGIN.left - 6} y={y(t)} textAnchor="end" dominantBaseline="middle">
                  {formatNumber(t)}
                </text>
              </g>
            ))}
            {chart.x.map((label, i) =>
              (count - 1 - i) % labelEvery === 0 ? (
                <text key={`${label}-${i}`} className="chat-chart-axis" x={center(i)} y={HEIGHT - MARGIN.bottom + 16} textAnchor="middle">
                  {label.length > 12 ? `${label.slice(0, 11)}…` : label}
                </text>
              ) : null,
            )}
            {chart.y_label && (
              <text className="chat-chart-axis" x={MARGIN.left} y={HEIGHT - 6} textAnchor="start">{chart.y_label}</text>
            )}

            {chart.type === 'line' && hover !== null && (
              <line className="chat-chart-crosshair" x1={center(hover)} x2={center(hover)} y1={MARGIN.top} y2={MARGIN.top + PLOT_H} />
            )}

            {chart.type === 'line' && chart.series.map((s, si) => (
              <g key={s.name}>
                <polyline
                  fill="none"
                  stroke={colors[si]}
                  strokeWidth={2}
                  strokeLinejoin="round"
                  points={s.values.map((v, i) => `${center(i)},${y(v)}`).join(' ')}
                />
                {s.values.map((v, i) => (
                  <circle key={i} cx={center(i)} cy={y(v)} r={hover === i ? 5 : 4} fill={colors[si]}
                    stroke="var(--color-surface)" strokeWidth={2} />
                ))}
              </g>
            ))}

            {chart.type === 'bar' && chart.x.map((_, i) =>
              chart.series.map((s, si) => {
                const value = s.values[i] ?? 0;
                const x = center(i) - barGroupWidth / 2 + si * (singleBarWidth + GAP);
                return <path key={`${i}-${si}`} d={barPath(x, y(value), singleBarWidth, MARGIN.top + PLOT_H - y(value))} fill={colors[si]} />;
              }),
            )}

            {stacked && chart.x.map((_, i) => {
              let base = 0;
              const top = chart.series.reduce((last, s, si) => ((s.values[i] ?? 0) > 0 ? si : last), -1);
              return chart.series.map((s, si) => {
                const value = Math.max(0, s.values[i] ?? 0);
                const y0 = y(base);
                base += value;
                const y1 = y(base);
                const h = Math.max(0, y0 - y1 - (si === top ? 0 : GAP));
                const x = center(i) - barGroupWidth / 2;
                if (value <= 0) return null;
                return si === top
                  ? <path key={`${i}-${si}`} d={barPath(x, y1, barGroupWidth, h)} fill={colors[si]} />
                  : <rect key={`${i}-${si}`} x={x} y={y1 + GAP} width={barGroupWidth} height={h} fill={colors[si]} />;
              });
            })}

            {/* Hit areas wider than the marks: one per x position. */}
            {chart.x.map((label, i) => (
              <rect
                key={`hit-${label}-${i}`}
                x={MARGIN.left + band * i}
                y={MARGIN.top}
                width={band}
                height={PLOT_H}
                fill="transparent"
                onMouseEnter={() => setHover(i)}
              />
            ))}
          </svg>
          {hover !== null && (
            <div className="chat-chart-tooltip" style={{ left: tooltipLeft }} role="status">
              <div className="chat-chart-tooltip-title">{chart.x[hover]}</div>
              {chart.series.map((s, si) => (
                <div key={s.name} className="chat-chart-tooltip-row">
                  <span className="chat-chart-swatch" style={{ background: colors[si] }} />
                  <span>{s.name || 'Değer'}</span>
                  <strong>{formatNumber(s.values[hover] ?? 0)}</strong>
                </div>
              ))}
              {stacked && chart.series.length > 1 && (
                <div className="chat-chart-tooltip-row chat-chart-tooltip-total">
                  <span>Toplam</span>
                  <strong>{formatNumber(totals[hover])}</strong>
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </figure>
  );
}

export default ChatChart;
