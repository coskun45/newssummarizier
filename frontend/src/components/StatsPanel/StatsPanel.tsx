import { GlobeAltIcon, InboxIcon, ArchiveBoxIcon, TagIcon } from '@heroicons/react/24/outline';
import { StarIcon } from '@heroicons/react/24/solid';
import { useFeeds, useArticleCounts, useTopics } from '../../hooks/useApi';
import { PRIORITIES } from '../../constants/priorities';
import { withAlpha } from '../../utils/color';
import './StatsPanel.css';

function StatsPanel() {
    const { data: feeds, isLoading: feedsLoading } = useFeeds();
    const { data: counts, isLoading: countsLoading } = useArticleCounts();
    const { data: topics, isLoading: topicsLoading } = useTopics();

    const isLoading = feedsLoading || countsLoading || topicsLoading;

    if (isLoading) {
        return (
            <section className="stats-panel" aria-label="İstatistikler yükleniyor">
                <h2 className="section-heading">İstatistikler</h2>
                <div className="stats-panel-card">
                    <div className="skeleton-card">
                        <div className="skeleton skeleton-line skeleton-line--title" />
                        <div className="skeleton skeleton-line skeleton-line--body" />
                        <div className="skeleton skeleton-line skeleton-line--body-short" />
                    </div>
                </div>
            </section>
        );
    }

    return (
        <section className="stats-panel" aria-label="İstatistikler">
            <h2 className="section-heading">İstatistikler</h2>

            <div className="stats-panel-card">
                <div className="stats-tiles">
                    <div className="stats-tile">
                        <GlobeAltIcon className="stats-tile-icon" />
                        <span className="stats-tile-value">{feeds?.length ?? 0}</span>
                        <span className="stats-tile-label">RSS Kaynağı</span>
                    </div>
                    <div className="stats-tile">
                        <InboxIcon className="stats-tile-icon" />
                        <span className="stats-tile-value">{counts?.unread_count ?? 0}</span>
                        <span className="stats-tile-label">Okunmamış Haber</span>
                    </div>
                    <div className="stats-tile">
                        <ArchiveBoxIcon className="stats-tile-icon" />
                        <span className="stats-tile-value">{counts?.read_count ?? 0}</span>
                        <span className="stats-tile-label">Arşiv</span>
                    </div>
                    <div className="stats-tile">
                        <StarIcon className="stats-tile-icon" />
                        <span className="stats-tile-value">{counts?.starred_count ?? 0}</span>
                        <span className="stats-tile-label">Favori</span>
                    </div>
                </div>

                <div className="stats-section">
                    <h3 className="stats-section-title">Önem Seviyesine Göre Okunmamış</h3>
                    <div className="stats-priority-grid">
                        {PRIORITIES.map((p) => (
                            <div key={p.value} className={`stats-priority-card priority-${p.value}`}>
                                <span className="stats-priority-card-value">{counts?.by_priority[p.value] ?? 0}</span>
                                <span className="stats-priority-card-label">{p.label}</span>
                            </div>
                        ))}
                    </div>
                </div>

                <div className="stats-section">
                    <h3 className="stats-section-title">
                        <TagIcon className="stats-section-title-icon" /> Kategorilere Göre
                    </h3>
                    {topics && topics.length > 0 ? (
                        <div className="stats-badge-row">
                            {topics.map((topic) => {
                                const tint = withAlpha(topic.color, '1a');
                                const border = withAlpha(topic.color, '40');
                                return (
                                    <span
                                        key={topic.id}
                                        className="badge topic-badge stats-topic-badge"
                                        style={tint && border ? { backgroundColor: tint, borderColor: border } : undefined}
                                    >
                                        {topic.color && <span className="topic-dot" style={{ backgroundColor: topic.color }} />}
                                        {topic.name}
                                        <span className="stats-topic-count">{topic.unread_count ?? 0}</span>
                                    </span>
                                );
                            })}
                        </div>
                    ) : (
                        <p className="text-small text-muted">Henüz kategori yok</p>
                    )}
                </div>
            </div>
        </section>
    );
}

export default StatsPanel;
