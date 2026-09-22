import { useState, useEffect, useMemo, useRef } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { useArticles, useArticleCounts, useTopics, useFeeds, useRefreshFeed, useMarkArticlesBulkRead, useUnstarAll, useDeleteAllArticlesByPriority, useArchiveAllArticlesByPriority, useDeleteAllUnimportant, useArchiveAllUnimportant, useReprocessArticles, useReprocessStatus } from '../../hooks/useApi';
import { feedsApi, articlesApi, summariesApi } from '../../services/api';
import { downloadArticlesAsWord, buildWhatsAppMessage, copyToClipboard } from '../../utils/exportArticles';
import ArticleList from '../ArticleList/ArticleList';
import HomeHero from '../HomeHero/HomeHero';
import StatsPanel from '../StatsPanel/StatsPanel';
import TopicFilter from '../TopicFilter/TopicFilter';
import CategoryBulkActions from '../CategoryBulkActions/CategoryBulkActions';
import FeedSidebar from '../FeedSidebar/FeedSidebar';
import DateFilter from '../DateFilter/DateFilter';
import SearchBar from '../SearchBar/SearchBar';
import Pagination from '../Pagination/Pagination';
import Settings, { type SettingsCategory } from '../Settings/Settings';
import SettingsNav from '../Settings/SettingsNav';
import UserMenu from '../UserMenu/UserMenu';
import BulletinPanel from '../Bulletin/Bulletin';
import Playground from '../Playground/Playground';
import Analysis from '../Analysis/Analysis';
import logo from '../../assets/logo.svg';
import {
  Cog6ToothIcon,
  ArrowPathIcon,
  FunnelIcon,
  InboxIcon,
  ArchiveBoxIcon,
  ArchiveBoxArrowDownIcon,
  CheckCircleIcon,
  XMarkIcon,
  DocumentArrowDownIcon,
  ChatBubbleLeftRightIcon,
  TrashIcon,
  ExclamationTriangleIcon,
  InformationCircleIcon,
} from '@heroicons/react/24/outline';
import { StarIcon } from '@heroicons/react/24/solid';
import type { AuthUser, DateFilterState } from '../../types';
import './Dashboard.css';

const PAGE_SIZE = 20;

interface DashboardProps {
  currentUser: AuthUser;
  onLogout: () => void;
}

function Dashboard({ currentUser, onLogout }: DashboardProps) {
  const [page, setPage] = useState(1);
  const [selectedTopics, setSelectedTopics] = useState<number[]>([]);
  const [importanceMode, setImportanceMode] = useState<'important' | 'unimportant' | null>(null);
  const [selectedPriority, setSelectedPriority] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState('');
  const [debouncedSearch, setDebouncedSearch] = useState('');
  const [selectedFeedIds, setSelectedFeedIds] = useState<number[]>([]);
  const emptyDate: DateFilterState = { preset: null, customFrom: '', customTo: '' };
  const [publishedFilter, setPublishedFilter] = useState<DateFilterState>(emptyDate);
  const [fetchedFilter, setFetchedFilter] = useState<DateFilterState>(emptyDate);
  const [activeView, setActiveView] = useState<'home' | 'news' | 'bulletin' | 'playground' | 'analysis' | 'settings'>('home');
  const [settingsCategory, setSettingsCategory] = useState<SettingsCategory>('feeds');
  const [activeSection, setActiveSection] = useState<'unread' | 'archive' | 'important' | 'error'>('unread');
  const [selectedArticleIds, setSelectedArticleIds] = useState<Set<number>>(new Set());
  const [exportNotice, setExportNotice] = useState<string | null>(null);
  const exportNoticeTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const unstarAllMutation = useUnstarAll();
  type RefreshStatus = 'idle' | 'running' | { new_articles: number; processed: number };
  const [refreshStatus, setRefreshStatus] = useState<RefreshStatus>('idle');
  const pollingIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const refreshStatusTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const queryClient = useQueryClient();

  const { data: feedsData } = useFeeds();
  const { data: articleCounts } = useArticleCounts();
  const refreshFeedMutation = useRefreshFeed();
  const markBulkReadMutation = useMarkArticlesBulkRead();
  const deleteAllByPriorityMutation = useDeleteAllArticlesByPriority();
  const archiveAllByPriorityMutation = useArchiveAllArticlesByPriority();
  const deleteAllUnimportantMutation = useDeleteAllUnimportant();
  const archiveAllUnimportantMutation = useArchiveAllUnimportant();
  const reprocessMutation = useReprocessArticles();
  const { data: reprocessStatus } = useReprocessStatus();

  // Stop polling on unmount
  useEffect(() => {
    return () => {
      if (pollingIntervalRef.current) clearInterval(pollingIntervalRef.current);
      if (refreshStatusTimerRef.current) clearTimeout(refreshStatusTimerRef.current);
      if (exportNoticeTimerRef.current) clearTimeout(exportNoticeTimerRef.current);
    };
  }, []);

  // Polls every feed in the batch until each has finished (done/error), then reports
  // aggregated totals. A single feed's slow/failed refresh must not block the others
  // from being reflected once they finish.
  const startPolling = (feedIds: number[]) => {
    if (pollingIntervalRef.current) clearInterval(pollingIntervalRef.current);
    const pending = new Set(feedIds);
    let totalNewArticles = 0;
    let totalProcessed = 0;
    pollingIntervalRef.current = setInterval(async () => {
      try {
        const results = await Promise.all(
          Array.from(pending).map((id) => feedsApi.getRefreshStatus(id).then((r) => ({ id, r })))
        );
        for (const { id, r } of results) {
          if (r.status === 'done' || r.status === 'error') {
            totalNewArticles += r.new_articles ?? 0;
            totalProcessed += r.processed ?? 0;
            pending.delete(id);
          }
        }
        if (pending.size === 0) {
          clearInterval(pollingIntervalRef.current!);
          pollingIntervalRef.current = null;
          queryClient.invalidateQueries({ queryKey: ['articles'] });
          queryClient.invalidateQueries({ queryKey: ['articleCounts'] });
          setRefreshStatus({ new_articles: totalNewArticles, processed: totalProcessed });
          if (refreshStatusTimerRef.current) clearTimeout(refreshStatusTimerRef.current);
          refreshStatusTimerRef.current = setTimeout(() => setRefreshStatus('idle'), 5000);
        }
      } catch {
        // silently ignore transient errors
      }
    }, 2000);
  };

  // For topic counts: use single feed if exactly one selected, else null (all)
  const topicFeedId = selectedFeedIds.length === 1 ? selectedFeedIds[0] : null;
  const { data: topicsData } = useTopics(topicFeedId);

  // Manual refresh targets whichever feeds are selected in the sidebar filter, or every
  // active feed when none are ("Tüm Beslemeler"). It must not silently default to a single
  // feed — with 40+ feeds in production that left every feed but one unrefreshable by hand.
  const refreshTargetFeedIds = selectedFeedIds.length > 0
    ? selectedFeedIds
    : (feedsData ?? []).map((f) => f.id);

  // Debounce search
  useEffect(() => {
    const timer = setTimeout(() => {
      setDebouncedSearch(searchQuery);
    }, 300);
    return () => clearTimeout(timer);
  }, [searchQuery]);

  const filters = useMemo(() => {
    const resolveDateRange = (f: DateFilterState): { from?: string; to?: string } => {
      if (!f.preset) return {};
      const now = new Date();
      const todayStart = new Date(now.getFullYear(), now.getMonth(), now.getDate()).toISOString();
      const todayEnd = new Date(now.getFullYear(), now.getMonth(), now.getDate(), 23, 59, 59, 999).toISOString();
      if (f.preset === 'today') return { from: todayStart, to: todayEnd };
      if (f.preset === 'week') {
        const weekAgo = new Date(now.getFullYear(), now.getMonth(), now.getDate() - 6).toISOString();
        return { from: weekAgo, to: todayEnd };
      }
      if (f.preset === 'custom') {
        return {
          from: f.customFrom ? new Date(f.customFrom).toISOString() : undefined,
          to: f.customTo ? new Date(f.customTo + 'T23:59:59').toISOString() : undefined,
        };
      }
      return {};
    };
    const pubRange = resolveDateRange(publishedFilter);
    const fetchRange = resolveDateRange(fetchedFilter);
    return {
      topic_ids: selectedTopics.length > 0 ? selectedTopics.join(',') : undefined,
      search: debouncedSearch || undefined,
      feed_ids: selectedFeedIds.length > 0 ? selectedFeedIds.join(',') : undefined,
      // The Error tab means "no severity label", so the sidebar importance/priority filters
      // (which need a label) would contradict it and always yield an empty list.
      status: activeSection === 'error' ? undefined
        : importanceMode === 'unimportant' ? 'filtered' : (importanceMode === 'important' ? 'summarized' : undefined),
      priority: activeSection === 'error' ? undefined : (selectedPriority ?? undefined),
      published_from: pubRange.from,
      published_to: pubRange.to,
      fetched_from: fetchRange.from,
      fetched_to: fetchRange.to,
      // "Önemli" (starred) and "Error" show their group regardless of read state
      is_read: (activeSection === 'important' || activeSection === 'error') ? undefined : activeSection === 'unread' ? false : true,
      is_starred: activeSection === 'important' ? true : undefined,
      // "Error" = articles that never received a severity label. They are listed only in the
      // Error tab and kept out of the unread list/counts until a re-run gives them a label.
      is_error: activeSection === 'error' ? true : activeSection === 'unread' ? false : undefined,
    };
  }, [selectedTopics, debouncedSearch, selectedFeedIds, importanceMode, selectedPriority, publishedFilter, fetchedFilter, activeSection]);

  // Reset to the first page whenever the active filters change
  useEffect(() => {
    setPage(1);
  }, [filters]);

  const queryFilters = useMemo(
    () => ({ ...filters, skip: (page - 1) * PAGE_SIZE, limit: PAGE_SIZE }),
    [filters, page]
  );

  const { data: articlesData, isLoading, error } = useArticles(queryFilters);

  const totalPages = articlesData ? Math.max(1, Math.ceil(articlesData.total / PAGE_SIZE)) : 1;

  // Clamp the page if the result set shrank (e.g. after delete / mark-as-read)
  useEffect(() => {
    if (page > totalPages) setPage(totalPages);
  }, [totalPages, page]);

  const goToPage = (p: number) => {
    setPage(p);
    window.scrollTo({ top: 0, behavior: 'smooth' });
  };

  // Reset selected topics and priority when feed selection changes
  useEffect(() => {
    setSelectedTopics([]);
    setSelectedPriority(null);
  }, [selectedFeedIds]);

  // Remove deleted feeds from selection
  useEffect(() => {
    if (feedsData && selectedFeedIds.length > 0) {
      const validIds = feedsData.map((f: { id: number }) => f.id);
      setSelectedFeedIds(prev => prev.filter(id => validIds.includes(id)));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [feedsData]);

  const handleSectionChange = (section: 'unread' | 'archive' | 'important' | 'error') => {
    setActiveSection(section);
    setSelectedArticleIds(new Set());
  };

  const showExportNotice = (msg: string) => {
    setExportNotice(msg);
    if (exportNoticeTimerRef.current) clearTimeout(exportNoticeTimerRef.current);
    exportNoticeTimerRef.current = setTimeout(() => setExportNotice(null), 4000);
  };

  // Resolve the selected articles together with their summaries (fetched per
  // article, since the list payload doesn't include summary texts). Only the
  // current selection is exported.
  const resolveExportItems = async () => {
    if (selectedArticleIds.size === 0) return [];
    const ids = Array.from(selectedArticleIds);
    return Promise.all(
      ids.map(async (id) => {
        const [article, summaries] = await Promise.all([
          articlesApi.get(id),
          summariesApi.getByArticle(id),
        ]);
        return { article, summaries };
      })
    );
  };

  const handleExportWord = async () => {
    const items = await resolveExportItems();
    if (items.length === 0) {
      showExportNotice('Lütfen dışa aktarmak için makale seçin.');
      return;
    }
    downloadArticlesAsWord(items);
    showExportNotice(`${items.length} makale Word olarak indirildi.`);
  };

  const handleExportWhatsApp = async () => {
    const items = await resolveExportItems();
    if (items.length === 0) {
      showExportNotice('Lütfen dışa aktarmak için makale seçin.');
      return;
    }
    const ok = await copyToClipboard(buildWhatsAppMessage(items));
    showExportNotice(
      ok
        ? `${items.length} makale panoya kopyalandı — WhatsApp'a yapıştırabilirsiniz.`
        : 'Panoya kopyalanamadı.'
    );
  };

  const handleClearImportant = () => {
    if (confirm('Tüm favorileri kaldırmak istediğinizden emin misiniz?')) {
      unstarAllMutation.mutate(undefined, { onSuccess: () => setSelectedArticleIds(new Set()) });
    }
  };

  const handleReprocessSelected = () => {
    const ids = Array.from(selectedArticleIds);
    reprocessMutation.mutate({ article_ids: ids }, { onSuccess: () => setSelectedArticleIds(new Set()) });
  };

  const handleReprocessAll = () => {
    if (!confirm('Tüm hatalı haberler yeniden işlenecek (OpenAI maliyeti oluşabilir). Devam edilsin mi?')) return;
    reprocessMutation.mutate(
      { all_errors: true, feed_ids: selectedFeedIds.length > 0 ? selectedFeedIds : undefined },
      { onSuccess: () => setSelectedArticleIds(new Set()) }
    );
  };

  const handleToggleSelect = (id: number) => {
    setSelectedArticleIds(prev => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  };

  const handleSelectAll = (ids: number[]) => {
    setSelectedArticleIds(prev => {
      const allSelected = ids.every(id => prev.has(id));
      if (allSelected) return new Set();
      return new Set(ids);
    });
  };

  const handleMarkSelected = () => {
    const ids = Array.from(selectedArticleIds);
    markBulkReadMutation.mutate({ articleIds: ids }, { onSuccess: () => setSelectedArticleIds(new Set()) });
  };

  const handleMarkAll = () => {
    markBulkReadMutation.mutate({ filters }, { onSuccess: () => setSelectedArticleIds(new Set()) });
  };

  const handleArticleDeleted = (id: number) => {
    setSelectedArticleIds(prev => {
      if (!prev.has(id)) return prev;
      const next = new Set(prev);
      next.delete(id);
      return next;
    });
  };

  const handleArchiveAllByPriority = (priority: string) => {
    archiveAllByPriorityMutation.mutate(
      { priority, feedIds: selectedFeedIds },
      { onSuccess: () => setSelectedArticleIds(new Set()) }
    );
  };

  const handleDeleteAllByPriority = (priority: string) => {
    deleteAllByPriorityMutation.mutate(
      { priority, feedIds: selectedFeedIds },
      { onSuccess: () => setSelectedArticleIds(new Set()) }
    );
  };

  const handleArchiveAllUnimportant = () => {
    archiveAllUnimportantMutation.mutate(
      { feedIds: selectedFeedIds },
      { onSuccess: () => setSelectedArticleIds(new Set()) }
    );
  };

  const handleDeleteAllUnimportant = () => {
    deleteAllUnimportantMutation.mutate(
      { feedIds: selectedFeedIds },
      { onSuccess: () => setSelectedArticleIds(new Set()) }
    );
  };

  return (
    <div className="dashboard">
      {/* Header */}
      <header className="dashboard-header">
        <div className="container">
          <div className="header-content">
            <div className="header-text">
              <button
                type="button"
                className="header-logo-button"
                onClick={() => setActiveView('home')}
                aria-label="Ana sayfaya git"
              >
                <img src={logo} alt="Bülten" className="header-logo" />
              </button>
            </div>
            <nav className="header-nav">
              <button
                className={`header-nav-item${activeView === 'home' ? ' header-nav-item--active' : ''}`}
                onClick={() => setActiveView('home')}
              >
                Ana Sayfa
              </button>
              <button
                className={`header-nav-item${activeView === 'news' ? ' header-nav-item--active' : ''}`}
                onClick={() => setActiveView('news')}
              >
                Haberler
              </button>
              <button
                className={`header-nav-item${activeView === 'bulletin' ? ' header-nav-item--active' : ''}`}
                onClick={() => setActiveView('bulletin')}
              >
                Bülten
              </button>
              <button
                className={`header-nav-item${activeView === 'playground' ? ' header-nav-item--active' : ''}`}
                onClick={() => setActiveView('playground')}
              >
                Playground
              </button>
              <button
                className={`header-nav-item${activeView === 'analysis' ? ' header-nav-item--active' : ''}`}
                onClick={() => setActiveView('analysis')}
              >
                Analiz
              </button>
              <button
                className={`header-nav-item${activeView === 'settings' ? ' header-nav-item--active' : ''}`}
                onClick={() => setActiveView('settings')}
              >
                Ayarlar
              </button>
            </nav>
            <div className="header-buttons">
              <UserMenu email={currentUser.email} onLogout={onLogout} />
            </div>
          </div>
        </div>
      </header>

      {/* Main Content */}
      <div className="dashboard-content">
        <div className="container">
          <div className="dashboard-grid">
            {/* Left Sidebar — not shown for the Bülten view, which is a report
                generator, not an article browser, and has its own config form */}
            {activeView === 'news' && (
            <aside className="dashboard-sidebar">
              <h2 className="sidebar-section-title">
                <FunnelIcon className="sidebar-section-icon" /> Filtreleme
              </h2>
              <FeedSidebar
                feeds={feedsData || []}
                selectedFeedIds={selectedFeedIds}
                feedCounts={articleCounts?.by_feed ?? {}}
                onFeedToggle={(id) =>
                  setSelectedFeedIds(prev =>
                    prev.includes(id) ? prev.filter(f => f !== id) : [...prev, id]
                  )
                }
                onClearFeeds={() => setSelectedFeedIds([])}
              />
              <TopicFilter
                topics={topicsData || []}
                selectedTopics={selectedTopics}
                onTopicToggle={(topicId) => {
                  const nextTopics = selectedTopics.includes(topicId)
                    ? selectedTopics.filter((id) => id !== topicId)
                    : [...selectedTopics, topicId];
                  setSelectedTopics(nextTopics);
                  if (nextTopics.length > 0) {
                    setImportanceMode('important');
                  } else if (!selectedPriority) {
                    setImportanceMode(null);
                  }
                }}
                importanceMode={importanceMode}
                onImportanceModeChange={(mode) => {
                  setImportanceMode(mode);
                  if (mode === 'unimportant') {
                    setSelectedTopics([]);
                    setSelectedPriority(null);
                    setSelectedFeedIds([]);
                  }
                }}
                selectedPriority={selectedPriority}
                onPriorityChange={(p) => {
                  setSelectedPriority(p);
                  if (p) {
                    setImportanceMode('important');
                  } else if (selectedTopics.length === 0) {
                    setImportanceMode(null);
                  }
                }}
                priorityCounts={articleCounts?.by_priority ?? {}}
                unimportantCount={articleCounts?.unimportant_count}
              />
              <DateFilter
                publishedFilter={publishedFilter}
                onPublishedChange={setPublishedFilter}
                fetchedFilter={fetchedFilter}
                onFetchedChange={setFetchedFilter}
              />
            </aside>
            )}

            {activeView === 'settings' && (
            <aside className="dashboard-sidebar">
              <h2 className="sidebar-section-title">
                <Cog6ToothIcon className="sidebar-section-icon" /> Ayarlar
              </h2>
              <SettingsNav
                activeCategory={settingsCategory}
                onCategoryChange={setSettingsCategory}
                isAdmin={currentUser.role === 'admin'}
              />
            </aside>
            )}

            {/* Main Content Area */}
            <main className="dashboard-main">
              {activeView === 'home' && (
                <>
                  <HomeHero onViewAll={() => setActiveView('news')} />
                  <StatsPanel />
                </>
              )}

              {activeView === 'bulletin' && <BulletinPanel />}

              {activeView === 'playground' && <Playground />}

              {activeView === 'analysis' && <Analysis />}

              {activeView === 'settings' && (
                <Settings category={settingsCategory} currentUser={currentUser} />
              )}

              {activeView === 'news' && (
                <>
                  <div className="news-toolbar">
                    <div className="news-toolbar-search">
                      <SearchBar value={searchQuery} onChange={setSearchQuery} />
                    </div>
                    <div className="news-toolbar-refresh">
                      <button
                        className="btn btn-outline btn-icon"
                        onClick={() => {
                          if (refreshTargetFeedIds.length === 0) return;
                          setRefreshStatus('running');
                          Promise.all(refreshTargetFeedIds.map((id) => refreshFeedMutation.mutateAsync(id)))
                            .then(() => startPolling(refreshTargetFeedIds))
                            .catch(() => setRefreshStatus('idle'));
                        }}
                        disabled={refreshStatus === 'running'}
                        title="Haberleri Güncelle"
                      >
                        <ArrowPathIcon className={refreshStatus === 'running' ? 'spin-icon' : undefined} />
                      </button>
                      {refreshStatus === 'running' && (
                        <span className="refresh-message refresh-message--processing">
                          <ArrowPathIcon className="spin-icon" /> Makaleler işleniyor...
                        </span>
                      )}
                      {typeof refreshStatus === 'object' && (
                        <span className="refresh-message">
                          {refreshStatus.new_articles > 0 ? (
                            <><CheckCircleIcon /> {refreshStatus.new_articles} yeni makale eklendi ({refreshStatus.processed} işlendi)</>
                          ) : (
                            <><InformationCircleIcon /> {refreshStatus.processed} makale işlendi, yeni makale yok</>
                          )}
                        </span>
                      )}
                    </div>
                  </div>

                  <div className="section-tabs">
                    <button
                      className={`section-tab${activeSection === 'unread' ? ' section-tab--active' : ''}`}
                      onClick={() => handleSectionChange('unread')}
                      aria-label="Okunmamışlar"
                    >
                      <InboxIcon /> Okunmamışlar
                      {(articleCounts?.unread_count ?? 0) > 0 && (
                        <span className="section-tab-badge">{articleCounts!.unread_count}</span>
                      )}
                    </button>
                    <button
                      className={`section-tab${activeSection === 'archive' ? ' section-tab--active' : ''}`}
                      onClick={() => handleSectionChange('archive')}
                      aria-label="Arşiv"
                    >
                      <ArchiveBoxIcon /> Arşiv
                      {(articleCounts?.read_count ?? 0) > 0 && (
                        <span className="section-tab-badge section-tab-badge--archive">{articleCounts!.read_count}</span>
                      )}
                    </button>
                    <button
                      className={`section-tab${activeSection === 'important' ? ' section-tab--active' : ''}`}
                      onClick={() => handleSectionChange('important')}
                      aria-label="Favori"
                    >
                      <StarIcon /> Favori
                      {(articleCounts?.starred_count ?? 0) > 0 && (
                        <span className="section-tab-badge section-tab-badge--important">{articleCounts!.starred_count}</span>
                      )}
                    </button>
                    <button
                      className={`section-tab${activeSection === 'error' ? ' section-tab--active' : ''}`}
                      onClick={() => handleSectionChange('error')}
                      aria-label="Error"
                    >
                      <ExclamationTriangleIcon /> Error
                      {(articleCounts?.error_count ?? 0) > 0 && (
                        <span className="section-tab-badge section-tab-badge--error">{articleCounts!.error_count}</span>
                      )}
                    </button>
                  </div>

                  {(activeSection === 'error' || reprocessStatus?.status === 'running') && (
                    <div className="bulk-action-bar">
                      {activeSection === 'error' && articlesData && articlesData.articles.length > 0 && (
                        <>
                          <button
                            className="btn btn-outline btn-sm"
                            onClick={() => handleSelectAll(articlesData.articles.map((a) => a.id))}
                          >
                            <CheckCircleIcon /> Tümünü Seç
                          </button>
                          {selectedArticleIds.size > 0 && (
                            <button
                              className="btn btn-primary btn-sm"
                              onClick={handleReprocessSelected}
                              disabled={reprocessMutation.isPending}
                            >
                              <ArrowPathIcon /> Seçilenleri Tekrar Dene ({selectedArticleIds.size})
                            </button>
                          )}
                          <button
                            className="btn btn-outline btn-sm"
                            onClick={handleReprocessAll}
                            disabled={reprocessMutation.isPending}
                          >
                            <ArrowPathIcon /> Tümünü Tekrar Dene
                          </button>
                        </>
                      )}
                      {reprocessStatus?.status === 'running' && (
                        <span className="refresh-message refresh-message--processing">
                          <ArrowPathIcon className="spin-icon" /> Yeniden işleniyor: {reprocessStatus.done}/{reprocessStatus.total}
                        </span>
                      )}
                    </div>
                  )}

                  {activeSection === 'unread' && articlesData && articlesData.articles.length > 0 && (
                    <div className="bulk-action-bar">
                      <button
                        className="btn btn-outline btn-sm"
                        onClick={handleMarkAll}
                        disabled={markBulkReadMutation.isPending}
                      >
                        <ArchiveBoxArrowDownIcon /> Tümünü Arşive Gönder
                      </button>
                      {selectedArticleIds.size > 0 && (
                        <button
                          className="btn btn-primary btn-sm"
                          onClick={handleMarkSelected}
                          disabled={markBulkReadMutation.isPending}
                        >
                          <ArchiveBoxArrowDownIcon /> Seçilenleri Arşive Gönder ({selectedArticleIds.size})
                        </button>
                      )}
                    </div>
                  )}

                  {activeSection === 'unread' && (
                    <CategoryBulkActions
                      priorityCounts={articleCounts?.by_priority ?? {}}
                      unimportantCount={articleCounts?.unimportant_count ?? 0}
                      onDeleteAllByPriority={handleDeleteAllByPriority}
                      onArchiveAllByPriority={handleArchiveAllByPriority}
                      onDeleteAllUnimportant={handleDeleteAllUnimportant}
                      onArchiveAllUnimportant={handleArchiveAllUnimportant}
                      deletePending={deleteAllByPriorityMutation.isPending || deleteAllUnimportantMutation.isPending}
                      archivePending={archiveAllByPriorityMutation.isPending || archiveAllUnimportantMutation.isPending}
                    />
                  )}

                  {activeSection === 'important' && articlesData && articlesData.articles.length > 0 && (
                    <div className="bulk-action-bar">
                      <button
                        className="btn btn-outline btn-sm"
                        onClick={() => handleSelectAll(articlesData.articles.map((a) => a.id))}
                      >
                        <CheckCircleIcon /> Tümünü Seç
                      </button>
                      {selectedArticleIds.size > 0 && (
                        <button
                          className="btn btn-outline btn-sm"
                          onClick={() => setSelectedArticleIds(new Set())}
                        >
                          <XMarkIcon /> Seçimi Temizle ({selectedArticleIds.size})
                        </button>
                      )}
                      <button
                        className="btn btn-primary btn-sm"
                        onClick={handleExportWord}
                        disabled={selectedArticleIds.size === 0}
                        title="Seçili makaleleri özetleriyle birlikte Word olarak indir"
                      >
                        <DocumentArrowDownIcon /> Word indir
                      </button>
                      <button
                        className="btn btn-primary btn-sm"
                        onClick={handleExportWhatsApp}
                        disabled={selectedArticleIds.size === 0}
                        title="Seçili makaleleri özetleriyle WhatsApp mesajı olarak panoya kopyala"
                      >
                        <ChatBubbleLeftRightIcon /> WhatsApp
                      </button>
                      <button
                        className="btn btn-outline btn-sm"
                        onClick={handleClearImportant}
                        disabled={unstarAllMutation.isPending}
                        title="Favori listesini tamamen temizle"
                      >
                        <TrashIcon /> Listeyi Temizle
                      </button>
                      {exportNotice && <span className="refresh-message refresh-message--processing">{exportNotice}</span>}
                    </div>
                  )}

                  {error && (
                    <div className="error-message">
                      <p><ExclamationTriangleIcon /> Makaleler yüklenirken hata oluştu</p>
                    </div>
                  )}

                  {isLoading ? (
                    <div className="skeleton-list" role="status" aria-label="Makaleler yükleniyor">
                      {Array.from({ length: 4 }).map((_, i) => (
                        <div key={i} className="skeleton-card">
                          <div className="skeleton skeleton-line skeleton-line--title" />
                          <div className="skeleton skeleton-line skeleton-line--meta" />
                          <div className="skeleton skeleton-line skeleton-line--body" />
                          <div className="skeleton skeleton-line skeleton-line--body-short" />
                        </div>
                      ))}
                    </div>
                  ) : articlesData && articlesData.articles.length === 0 ? (
                    <div className="empty-state">
                      <InboxIcon className="empty-state-icon" />
                      <p>{activeSection === 'error' ? 'Hatalı haber yok' : 'Makale bulunamadı'}</p>
                      <p className="text-small text-muted">
                        {selectedTopics.length > 0 || searchQuery
                          ? 'Farklı filtreler deneyin'
                          : activeSection === 'error'
                            ? 'Tüm haberler bir önem etiketi almış.'
                            : 'Makaleler yükleniyor...'}
                      </p>
                    </div>
                  ) : (
                    articlesData && (
                      <>
                        <div className="results-count">
                          <p className="text-small text-muted">
                            {articlesData.total} makale bulundu
                          </p>
                        </div>
                        <ArticleList
                          articles={articlesData.articles}
                          selectedIds={selectedArticleIds}
                          onToggleSelect={handleToggleSelect}
                          onSelectAll={handleSelectAll}
                          onDeleted={handleArticleDeleted}
                          isArchiveView={activeSection === 'archive'}
                          selectable={activeSection !== 'archive'}
                        />
                        <Pagination
                          currentPage={page}
                          totalPages={totalPages}
                          onPageChange={goToPage}
                        />
                      </>
                    )
                  )}
                </>
              )}
            </main>
          </div>
        </div>
      </div>
    </div>
  );
}

export default Dashboard;
