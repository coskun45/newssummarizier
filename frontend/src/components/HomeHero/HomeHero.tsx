import { useEffect, useRef, useState } from 'react';
import { ChevronLeftIcon, ChevronRightIcon, ArrowPathIcon, XMarkIcon } from '@heroicons/react/24/outline';
import { useArticles, useArticle, useSummaries } from '../../hooks/useApi';
import { formatPublishedAt } from '../../utils/formatDate';
import './HomeHero.css';

const HERO_LIMIT = 10;
const AUTO_ROTATE_MS = 6000;

interface HomeHeroProps {
    /** Jump to the full "Haberler" list — wired to the pager's "T" (Tümü) button. */
    onViewAll: () => void;
}

function HomeHero({ onViewAll }: HomeHeroProps) {
    const { data, isLoading } = useArticles({ priority: 'high', limit: HERO_LIMIT });
    const articles = data?.articles.slice(0, HERO_LIMIT) ?? [];

    const [index, setIndex] = useState(0);
    const [detailOpen, setDetailOpen] = useState(false);
    const [paused, setPaused] = useState(false);
    const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

    // Keep the index in range if the article count shrinks (e.g. after a refetch).
    useEffect(() => {
        if (index >= articles.length && articles.length > 0) {
            setIndex(0);
        }
    }, [articles.length, index]);

    // Auto-rotate on a fixed interval; paused while hovered or while the detail
    // panel is open, so the slide doesn't change out from under someone reading.
    useEffect(() => {
        if (paused || detailOpen || articles.length <= 1) return;
        timerRef.current = setInterval(() => {
            setIndex((i) => (i + 1) % articles.length);
        }, AUTO_ROTATE_MS);
        return () => {
            if (timerRef.current) clearInterval(timerRef.current);
        };
    }, [paused, detailOpen, articles.length]);

    const goTo = (next: number) => {
        setIndex(next);
        setDetailOpen(false);
    };
    const goPrev = () => goTo((index - 1 + articles.length) % articles.length);
    const goNext = () => goTo((index + 1) % articles.length);

    // Render with a clamped index rather than trusting `index` directly: if a
    // background refetch shrinks `articles` between renders, `index` can briefly
    // point past the end before the effect above resets it, and `articles[index]`
    // would be undefined.
    const safeIndex = index < articles.length ? index : 0;
    const current = articles[safeIndex];
    const { data: detail, isLoading: detailLoading } = useArticle(detailOpen && current ? current.id : null);
    const { data: summaries, isLoading: summaryLoading } = useSummaries(current ? current.id : null);
    const briefSummary = summaries?.find((s) => s.summary_type === 'brief');

    if (isLoading) {
        return (
            <section className="home-hero" aria-label="Öne çıkan haberler yükleniyor">
                <h2 className="section-heading">Top News</h2>
                <div className="home-hero-slide home-hero-slide--skeleton skeleton" />
            </section>
        );
    }

    if (articles.length === 0) {
        return null;
    }

    const timeAgo = current.published_at ? formatPublishedAt(current.published_at) : null;

    return (
        <section
            className="home-hero"
            aria-label="Öne çıkan haberler"
            onMouseEnter={() => setPaused(true)}
            onMouseLeave={() => setPaused(false)}
        >
            <h2 className="section-heading">Top News</h2>
            <div
                className="home-hero-slide"
                role="button"
                tabIndex={0}
                aria-label={current.title}
                onClick={() => setDetailOpen((open) => !open)}
                onKeyDown={(e) => {
                    if (e.key === 'Enter' || e.key === ' ') {
                        e.preventDefault();
                        setDetailOpen((open) => !open);
                    }
                }}
            >
                {articles.length > 1 && (
                    <>
                        <button
                            type="button"
                            className="home-hero-arrow home-hero-arrow--prev"
                            aria-label="Önceki haber"
                            onClick={(e) => { e.stopPropagation(); goPrev(); }}
                        >
                            <ChevronLeftIcon />
                        </button>
                        <button
                            type="button"
                            className="home-hero-arrow home-hero-arrow--next"
                            aria-label="Sonraki haber"
                            onClick={(e) => { e.stopPropagation(); goNext(); }}
                        >
                            <ChevronRightIcon />
                        </button>
                    </>
                )}

                <div className="home-hero-slide-content">
                    {current.priority && (
                        <span className={`badge priority-badge priority-${current.priority}`}>
                            <span className="priority-dot" />
                            {current.priority === 'high' ? 'Yüksek' : current.priority === 'med' ? 'Orta' : 'Düşük'}
                        </span>
                    )}
                    <h1 className="home-hero-title">{current.title}</h1>
                    {timeAgo && <span className="home-hero-time">{timeAgo}</span>}
                    <p className="home-hero-summary">
                        {summaryLoading ? 'Özet yükleniyor...' : briefSummary ? briefSummary.summary_text : 'Özet mevcut değil'}
                    </p>
                </div>
            </div>

            <div className="home-hero-pager">
                {articles.map((article, i) => (
                    <button
                        key={article.id}
                        type="button"
                        className={`home-hero-pager-item${i === safeIndex ? ' home-hero-pager-item--active' : ''}`}
                        aria-label={`${i + 1}. haber`}
                        aria-current={i === safeIndex}
                        onClick={() => goTo(i)}
                    >
                        {i + 1}
                    </button>
                ))}
                <button
                    type="button"
                    className="home-hero-pager-item home-hero-pager-item--all"
                    aria-label="Tüm haberler"
                    title="Tüm haberler"
                    onClick={onViewAll}
                >
                    T
                </button>
            </div>

            {detailOpen && (
                <div className="home-hero-detail">
                    <div className="home-hero-detail-header">
                        <h2>{current.title}</h2>
                        <button
                            type="button"
                            className="modal-close-btn"
                            onClick={() => setDetailOpen(false)}
                            aria-label="Kapat"
                        >
                            <XMarkIcon />
                        </button>
                    </div>
                    {detailLoading ? (
                        <p className="text-muted"><ArrowPathIcon className="spin-icon" /> Yükleniyor...</p>
                    ) : detail?.cleaned_content || detail?.raw_content ? (
                        <div className="home-hero-detail-body">
                            {(detail.cleaned_content || detail.raw_content || '').split('\n').map((paragraph, idx) => (
                                paragraph.trim() && <p key={idx}>{paragraph}</p>
                            ))}
                        </div>
                    ) : (
                        <p className="text-muted">İçerik mevcut değil</p>
                    )}
                    {current.published_at && (
                        <p className="home-hero-detail-meta text-small text-muted">
                            {formatPublishedAt(current.published_at)}
                        </p>
                    )}
                </div>
            )}
        </section>
    );
}

export default HomeHero;
