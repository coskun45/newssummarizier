import { format } from 'date-fns';
import { tr } from 'date-fns/locale';
import type { DailyArticleStats } from '../../types';

interface DailyStatsChartProps {
    stats: DailyArticleStats;
}

function DailyStatsChart({ stats }: DailyStatsChartProps) {
    const max = Math.max(1, ...stats.days.flatMap((d) => [d.incoming, d.processed]));

    return (
        <div className="stats-daily-chart">
            <div className="stats-daily-today">
                <span className="stats-daily-today-label">Bugün</span>
                <div className="stats-daily-today-values">
                    <span className="stats-daily-today-value stats-daily-today-value--incoming">
                        {stats.today.incoming} <span className="stats-daily-today-sub">gelen</span>
                    </span>
                    <span className="stats-daily-today-value stats-daily-today-value--processed">
                        {stats.today.processed} <span className="stats-daily-today-sub">işlenen</span>
                    </span>
                </div>
            </div>

            <div className="stats-daily-legend">
                <span className="stats-daily-legend-item">
                    <span className="stats-daily-legend-swatch stats-daily-legend-swatch--incoming" />
                    Gelen Haberler
                </span>
                <span className="stats-daily-legend-item">
                    <span className="stats-daily-legend-swatch stats-daily-legend-swatch--processed" />
                    İşlenen Haberler
                </span>
            </div>

            <div className="stats-daily-bars" role="img" aria-label="Son 7 gün gelen ve işlenen haber sayıları">
                {stats.days.map((day) => {
                    const date = new Date(`${day.date}T00:00:00Z`);
                    const isToday = day.date === stats.today.date;
                    return (
                        <div key={day.date} className={`stats-daily-day${isToday ? ' stats-daily-day--today' : ''}`}>
                            <div className="stats-daily-day-bars">
                                <div
                                    className="stats-daily-bar stats-daily-bar--incoming"
                                    style={{ height: `${(day.incoming / max) * 100}%` }}
                                    title={`${format(date, 'd MMMM', { locale: tr })}: ${day.incoming} gelen`}
                                />
                                <div
                                    className="stats-daily-bar stats-daily-bar--processed"
                                    style={{ height: `${(day.processed / max) * 100}%` }}
                                    title={`${format(date, 'd MMMM', { locale: tr })}: ${day.processed} işlenen`}
                                />
                            </div>
                            <span className="stats-daily-day-values">
                                {day.incoming}/{day.processed}
                            </span>
                            <span className="stats-daily-day-label">{format(date, 'EEEEEE', { locale: tr })}</span>
                        </div>
                    );
                })}
            </div>
        </div>
    );
}

export default DailyStatsChart;
