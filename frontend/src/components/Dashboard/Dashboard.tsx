import { useState, useEffect, useMemo, useRef } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useArticles, useArticleCounts, useTopics, useFeeds, useRefreshFeed, useMarkArticlesBulkRead } from '../../hooks/useApi';
import { appApi, feedsApi } from '../../services/api';
import ArticleList from '../ArticleList/ArticleList';
import TopicFilter from '../TopicFilter/TopicFilter';
import FeedSidebar from '../FeedSidebar/FeedSidebar';
import DateFilter from '../DateFilter/DateFilter';
import SearchBar from '../SearchBar/SearchBar';
import Settings from '../Settings/Settings';
import { Cog6ToothIcon, ArrowPathIcon, ArrowRightStartOnRectangleIcon, FunnelIcon } from '@heroicons/react/24/outline';
import type { AuthUser, DateFilterState } from '../../types';
import './Dashboard.css';

interface DashboardProps {
  currentUser: AuthUser;
  onLogout: () => void;
}

function Dashboard({ currentUser, onLogout }: DashboardProps) {
  const [selectedTopics, setSelectedTopics] = useState<number[]>([]);
  const [importanceMode, setImportanceMode] = useState<'important' | 'unimportant' | null>(null);
  const [selectedPriority, setSelectedPriority] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState('');
  const [debouncedSearch, setDebouncedSearch] = useState('');
  const [showSettings, setShowSettings] = useState(false);
  const [selectedFeedIds, setSelectedFeedIds] = useState<number[]>([]);
  const emptyDate: DateFilterState = { preset: null, customFrom: '', customTo: '' };
  const [publishedFilter, setPublishedFilter] = useState<DateFilterState>(emptyDate);
  const [fetchedFilter, setFetchedFilter] = useState<DateFilterState>(emptyDate);
  const [activeSection, setActiveSection] = useState<'unread' | 'archive'>('unread');
  const [selectedArticleIds, setSelectedArticleIds] = useState<Set<number>>(new Set());
  type RefreshStatus = 'idle' | 'running' | { new_articles: number; processed: number };
  const [refreshStatus, setRefreshStatus] = useState<RefreshStatus>('idle');
  const pollingIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const refreshStatusTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const queryClient = useQueryClient();

  const { data: appInfo } = useQuery({ queryKey: ['appInfo'], queryFn: appApi.getInfo, staleTime: Infinity });

  const { data: feedsData } = useFeeds();
  const { data: articleCounts } = useArticleCounts();
  const refreshFeedMutation = useRefreshFeed();
  const markBulkReadMutation = useMarkArticlesBulkRead();

  // Stop polling on unmount
  useEffect(() => {
    return () => {
      if (pollingIntervalRef.current) clearInterval(pollingIntervalRef.current);
      if (refreshStatusTimerRef.current) clearTimeout(refreshStatusTimerRef.current);
    };
  }, []);

  const startPolling = (feedId: number) => {
    if (pollingIntervalRef.current) clearInterval(pollingIntervalRef.current);
    pollingIntervalRef.current = setInterval(async () => {
      try {
        const result = await feedsApi.getRefreshStatus(feedId);
        if (result.status === 'done' || result.status === 'error') {
          clearInterval(pollingIntervalRef.current!);
          pollingIntervalRef.current = null;
          queryClient.invalidateQueries({ queryKey: ['articles'] });
          queryClient.invalidateQueries({ queryKey: ['articleCounts'] });
          setRefreshStatus({ new_articles: result.new_articles ?? 0, processed: result.processed ?? 0 });
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

  // Use first selected feed for manual refresh, or fall back to first feed
  const activeFeedId = selectedFeedIds[0] ?? (feedsData && feedsData.length > 0 ? feedsData[0].id : null);

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
      limit: 50,
      feed_ids: selectedFeedIds.length > 0 ? selectedFeedIds.join(',') : undefined,
      status: importanceMode === 'unimportant' ? 'filtered' : (importanceMode === 'important' ? 'summarized' : undefined),
      priority: selectedPriority ?? undefined,
      published_from: pubRange.from,
      published_to: pubRange.to,
      fetched_from: fetchRange.from,
      fetched_to: fetchRange.to,
      is_read: activeSection === 'unread' ? false : true,
    };
  }, [selectedTopics, debouncedSearch, selectedFeedIds, importanceMode, selectedPriority, publishedFilter, fetchedFilter, activeSection]);

  const { data: articlesData, isLoading, error } = useArticles(filters);

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

  const handleSectionChange = (section: 'unread' | 'archive') => {
    setActiveSection(section);
    setSelectedArticleIds(new Set());
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
    markBulkReadMutation.mutate(ids, { onSuccess: () => setSelectedArticleIds(new Set()) });
  };

  const handleMarkAll = () => {
    markBulkReadMutation.mutate(undefined, { onSuccess: () => setSelectedArticleIds(new Set()) });
  };

  return (
    <div className="dashboard">
      <Settings isOpen={showSettings} onClose={() => setShowSettings(false)} currentUser={currentUser} />

      {/* Header */}
      <header className="dashboard-header">
        <div className="container">
          <div className="header-content">
            <div className="header-text">
              <h1>Haber Özetleyici</h1>
              {appInfo && <span className="app-version">v{appInfo.version}</span>}
            </div>
            <div className="header-buttons">

              <button
                className="check-button"
                onClick={() => {
                  if (!activeFeedId) return;
                  setRefreshStatus('running');
                  refreshFeedMutation.mutate(activeFeedId, {
                    onSuccess: () => startPolling(activeFeedId),
                    onError: () => setRefreshStatus('idle'),
                  });
                }}
                disabled={refreshStatus === 'running'}
              >
                {refreshStatus === 'running' ? (
                  <><ArrowPathIcon className="spin-icon" /> İşleniyor...</>
                ) : (
                  <><ArrowPathIcon /> Şimdi Yenile</>
                )}
              </button>
              {refreshStatus === 'running' && (
                <span className="refresh-message refresh-message--processing">⏳ Makaleler işleniyor...</span>
              )}
              {typeof refreshStatus === 'object' && (
                <span className="refresh-message">
                  {refreshStatus.new_articles > 0
                    ? `✅ ${refreshStatus.new_articles} yeni makale eklendi (${refreshStatus.processed} işlendi)`
                    : `ℹ️ ${refreshStatus.processed} makale işlendi, yeni makale yok`}
                </span>
              )}

              <button
                className="settings-button"
                onClick={() => setShowSettings(true)}
                title="Ayarlar"
              >
                <Cog6ToothIcon />
              </button>

              <div className="user-info">
                <span className="user-email" title={currentUser.email}>{currentUser.email}</span>
                <button
                  className="logout-button"
                  onClick={onLogout}
                  title="Çıkış Yap"
                >
                  <ArrowRightStartOnRectangleIcon />
                </button>
              </div>
            </div>
          </div>
        </div>
      </header>

      {/* Main Content */}
      <div className="dashboard-content">
        <div className="container">
          <div className="dashboard-grid">
            {/* Left Sidebar */}
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

            {/* Main Content Area */}
            <main className="dashboard-main">
              <SearchBar value={searchQuery} onChange={setSearchQuery} />

              <div className="section-tabs">
                <button
                  className={`section-tab${activeSection === 'unread' ? ' section-tab--active' : ''}`}
                  onClick={() => handleSectionChange('unread')}
                >
                  📥 Okunmamışlar
                  {(articleCounts?.unread_count ?? 0) > 0 && (
                    <span className="section-tab-badge">{articleCounts!.unread_count}</span>
                  )}
                </button>
                <button
                  className={`section-tab${activeSection === 'archive' ? ' section-tab--active' : ''}`}
                  onClick={() => handleSectionChange('archive')}
                >
                  🗄️ Arşiv
                  {(articleCounts?.read_count ?? 0) > 0 && (
                    <span className="section-tab-badge section-tab-badge--archive">{articleCounts!.read_count}</span>
                  )}
                </button>
              </div>

              {activeSection === 'unread' && articlesData && articlesData.articles.length > 0 && (
                <div className="bulk-action-bar">
                  <button
                    className="btn btn-outline btn-sm"
                    onClick={handleMarkAll}
                    disabled={markBulkReadMutation.isPending}
                  >
                    📦 Tümünü Arşive Gönder
                  </button>
                  {selectedArticleIds.size > 0 && (
                    <button
                      className="btn btn-primary btn-sm"
                      onClick={handleMarkSelected}
                      disabled={markBulkReadMutation.isPending}
                    >
                      📦 Seçilenleri Arşive Gönder ({selectedArticleIds.size})
                    </button>
                  )}
                </div>
              )}

              {error && (
                <div className="error-message">
                  <p>⚠️ Makaleler yüklenirken hata oluştu</p>
                </div>
              )}

              {isLoading ? (
                <div className="loading-state">
                  <p>⏳ Makaleler yükleniyor...</p>
                </div>
              ) : articlesData && articlesData.articles.length === 0 ? (
                <div className="empty-state">
                  <p>📭 Makale bulunamadı</p>
                  <p className="text-small text-muted">
                    {selectedTopics.length > 0 || searchQuery
                      ? 'Farklı filtreler deneyin'
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
                      isArchiveView={activeSection === 'archive'}
                    />
                  </>
                )
              )}
            </main>
          </div>
        </div>
      </div>
    </div>
  );
}

export default Dashboard;
