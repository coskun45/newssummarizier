import { useState, useEffect, useMemo, useRef } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useArticles, useArticleCounts, useTopics, useFeeds, useRefreshFeed, useMarkArticlesBulkRead, useUnstarAll, useDeleteAllArticlesByTopic, useArchiveAllArticlesByTopic, useDeleteAllUnimportant, useArchiveAllUnimportant } from '../../hooks/useApi';
import { appApi, feedsApi, articlesApi, summariesApi } from '../../services/api';
import { downloadArticlesAsWord, buildWhatsAppMessage, copyToClipboard } from '../../utils/exportArticles';
import ArticleList from '../ArticleList/ArticleList';
import TopicFilter from '../TopicFilter/TopicFilter';
import CategoryBulkActions from '../CategoryBulkActions/CategoryBulkActions';
import FeedSidebar from '../FeedSidebar/FeedSidebar';
import DateFilter from '../DateFilter/DateFilter';
import SearchBar from '../SearchBar/SearchBar';
import Pagination from '../Pagination/Pagination';
import Settings from '../Settings/Settings';
import { Cog6ToothIcon, ArrowPathIcon, ArrowRightStartOnRectangleIcon, FunnelIcon } from '@heroicons/react/24/outline';
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
  const [showSettings, setShowSettings] = useState(false);
  const [selectedFeedIds, setSelectedFeedIds] = useState<number[]>([]);
  const emptyDate: DateFilterState = { preset: null, customFrom: '', customTo: '' };
  const [publishedFilter, setPublishedFilter] = useState<DateFilterState>(emptyDate);
  const [fetchedFilter, setFetchedFilter] = useState<DateFilterState>(emptyDate);
  const [activeSection, setActiveSection] = useState<'unread' | 'archive' | 'important'>('unread');
  const [selectedArticleIds, setSelectedArticleIds] = useState<Set<number>>(new Set());
  const [exportNotice, setExportNotice] = useState<string | null>(null);
  const exportNoticeTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const unstarAllMutation = useUnstarAll();
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
  const deleteAllByTopicMutation = useDeleteAllArticlesByTopic();
  const archiveAllByTopicMutation = useArchiveAllArticlesByTopic();
  const deleteAllUnimportantMutation = useDeleteAllUnimportant();
  const archiveAllUnimportantMutation = useArchiveAllUnimportant();

  // Stop polling on unmount
  useEffect(() => {
    return () => {
      if (pollingIntervalRef.current) clearInterval(pollingIntervalRef.current);
      if (refreshStatusTimerRef.current) clearTimeout(refreshStatusTimerRef.current);
      if (exportNoticeTimerRef.current) clearTimeout(exportNoticeTimerRef.current);
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
      feed_ids: selectedFeedIds.length > 0 ? selectedFeedIds.join(',') : undefined,
      status: importanceMode === 'unimportant' ? 'filtered' : (importanceMode === 'important' ? 'summarized' : undefined),
      priority: selectedPriority ?? undefined,
      published_from: pubRange.from,
      published_to: pubRange.to,
      fetched_from: fetchRange.from,
      fetched_to: fetchRange.to,
      // "Önemli" shows the starred group regardless of read state
      is_read: activeSection === 'important' ? undefined : activeSection === 'unread' ? false : true,
      is_starred: activeSection === 'important' ? true : undefined,
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

  const handleSectionChange = (section: 'unread' | 'archive' | 'important') => {
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
    showExportNotice(`📄 ${items.length} makale Word olarak indirildi.`);
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
        ? `💬 ${items.length} makale panoya kopyalandı — WhatsApp'a yapıştırabilirsiniz.`
        : 'Panoya kopyalanamadı.'
    );
  };

  const handleClearImportant = () => {
    if (confirm('Tüm favorileri kaldırmak istediğinizden emin misiniz?')) {
      unstarAllMutation.mutate(undefined, { onSuccess: () => setSelectedArticleIds(new Set()) });
    }
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

  const handleArchiveAllCategory = (topicId: number) => {
    archiveAllByTopicMutation.mutate(
      { topicId, feedIds: selectedFeedIds },
      { onSuccess: () => setSelectedArticleIds(new Set()) }
    );
  };

  const handleDeleteAllCategory = (topicId: number) => {
    deleteAllByTopicMutation.mutate(
      { topicId, feedIds: selectedFeedIds },
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
                <button
                  className={`section-tab${activeSection === 'important' ? ' section-tab--active' : ''}`}
                  onClick={() => handleSectionChange('important')}
                >
                  ⭐ Favori
                  {(articleCounts?.starred_count ?? 0) > 0 && (
                    <span className="section-tab-badge section-tab-badge--important">{articleCounts!.starred_count}</span>
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

              {activeSection === 'unread' && topicsData && topicsData.length > 0 && (
                <CategoryBulkActions
                  topics={topicsData}
                  unimportantCount={articleCounts?.unimportant_count ?? 0}
                  onDeleteAll={handleDeleteAllCategory}
                  onArchiveAll={handleArchiveAllCategory}
                  onDeleteAllUnimportant={handleDeleteAllUnimportant}
                  onArchiveAllUnimportant={handleArchiveAllUnimportant}
                  deletePending={deleteAllByTopicMutation.isPending || deleteAllUnimportantMutation.isPending}
                  archivePending={archiveAllByTopicMutation.isPending || archiveAllUnimportantMutation.isPending}
                />
              )}

              {activeSection === 'important' && articlesData && articlesData.articles.length > 0 && (
                <div className="bulk-action-bar">
                  <button
                    className="btn btn-outline btn-sm"
                    onClick={() => handleSelectAll(articlesData.articles.map((a) => a.id))}
                  >
                    ☑️ Tümünü Seç
                  </button>
                  {selectedArticleIds.size > 0 && (
                    <button
                      className="btn btn-outline btn-sm"
                      onClick={() => setSelectedArticleIds(new Set())}
                    >
                      ✖ Seçimi Temizle ({selectedArticleIds.size})
                    </button>
                  )}
                  <button
                    className="btn btn-primary btn-sm"
                    onClick={handleExportWord}
                    disabled={selectedArticleIds.size === 0}
                    title="Seçili makaleleri özetleriyle birlikte Word olarak indir"
                  >
                    📄 Word indir
                  </button>
                  <button
                    className="btn btn-primary btn-sm"
                    onClick={handleExportWhatsApp}
                    disabled={selectedArticleIds.size === 0}
                    title="Seçili makaleleri özetleriyle WhatsApp mesajı olarak panoya kopyala"
                  >
                    💬 WhatsApp
                  </button>
                  <button
                    className="btn btn-outline btn-sm"
                    onClick={handleClearImportant}
                    disabled={unstarAllMutation.isPending}
                    title="Favori listesini tamamen temizle"
                  >
                    🗑️ Listeyi Temizle
                  </button>
                  {exportNotice && <span className="refresh-message refresh-message--processing">{exportNotice}</span>}
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
            </main>
          </div>
        </div>
      </div>
    </div>
  );
}

export default Dashboard;
