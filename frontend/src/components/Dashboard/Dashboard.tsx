import { useState, useEffect, useMemo } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { useArticles, useArticleCounts, useTopics, useFeeds, useRefreshFeed, useCheckNewArticles, useAddArticlesToFeed } from '../../hooks/useApi';
import ArticleList from '../ArticleList/ArticleList';
import TopicFilter from '../TopicFilter/TopicFilter';
import FeedSidebar from '../FeedSidebar/FeedSidebar';
import DateFilter from '../DateFilter/DateFilter';
import SearchBar from '../SearchBar/SearchBar';
import Settings from '../Settings/Settings';
import { Cog6ToothIcon, MagnifyingGlassIcon, ChartBarIcon, ArrowPathIcon, XMarkIcon, ArrowRightStartOnRectangleIcon, FunnelIcon } from '@heroicons/react/24/outline';
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
  const [notification, setNotification] = useState<string | null>(null);
  const [showNewArticlesList, setShowNewArticlesList] = useState(false);
  const [selectedNewIndexes, setSelectedNewIndexes] = useState<number[]>([]);
  const [showSettings, setShowSettings] = useState(false);
  const [processingUrls, setProcessingUrls] = useState<string[]>([]);
  const [selectedFeedIds, setSelectedFeedIds] = useState<number[]>([]);
  const emptyDate: DateFilterState = { preset: null, customFrom: '', customTo: '' };
  const [publishedFilter, setPublishedFilter] = useState<DateFilterState>(emptyDate);
  const [fetchedFilter, setFetchedFilter] = useState<DateFilterState>(emptyDate);
  const queryClient = useQueryClient();

  const { data: feedsData } = useFeeds();
  const { data: articleCounts } = useArticleCounts();
  const { isPending: isRefreshing } = useRefreshFeed();

  // For topic counts: use single feed if exactly one selected, else null (all)
  const topicFeedId = selectedFeedIds.length === 1 ? selectedFeedIds[0] : null;
  const { data: topicsData } = useTopics(topicFeedId);

  // Use first selected feed for "check new", or fall back to first feed
  const activeFeedId = selectedFeedIds[0] ?? (feedsData && feedsData.length > 0 ? feedsData[0].id : null);

  const { data: newArticlesData, refetch: checkNewArticles, isFetching: isChecking } = useCheckNewArticles(activeFeedId);
  const addArticlesMutation = useAddArticlesToFeed();

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
    };
  }, [selectedTopics, debouncedSearch, selectedFeedIds, importanceMode, selectedPriority, publishedFilter, fetchedFilter]);

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
  }, [feedsData]);

  const handleCheckNewArticles = async () => {
    if (activeFeedId) {
      await checkNewArticles();
      setShowNewArticlesList(true);
      // selectedNewIndexes is set via useEffect when newArticlesData updates
    }
  };

  // Auto-select all articles when newArticlesData updates (fixes timing bug)
  useEffect(() => {
    if (newArticlesData?.new_articles_list) {
      setSelectedNewIndexes(
        newArticlesData.new_articles_list.map((_,  i: number) => i)
      );
    }
  }, [newArticlesData]);

  // Auto-hide notification
  useEffect(() => {
    if (notification) {
      const timer = setTimeout(() => setNotification(null), 5000);
      return () => clearTimeout(timer);
    }
  }, [notification]);

  // Poll every 5 seconds while articles are being processed
  useEffect(() => {
    if (processingUrls.length === 0) return;
    const interval = setInterval(() => {
      queryClient.invalidateQueries({ queryKey: ['articles'] });
    }, 5000);
    const timeout = setTimeout(() => {
      clearInterval(interval);
      setProcessingUrls([]);
      setNotification(null);
    }, 180000); // 3 min safety limit
    return () => { clearInterval(interval); clearTimeout(timeout); };
  }, [processingUrls]);

  // Check processing completion when articlesData updates
  useEffect(() => {
    if (processingUrls.length === 0 || !articlesData?.articles) return;
    const allDone = processingUrls.every(url => {
      const article = articlesData.articles.find((a) => a.url === url);
      return article && article.status !== 'queued';
    });
    if (allDone) {
      setProcessingUrls([]);
      setNotification('Makaleler başarıyla işlendi!');
      setTimeout(() => setNotification(null), 5000);
    }
  }, [articlesData]);

  return (
    <div className="dashboard">
      <Settings isOpen={showSettings} onClose={() => setShowSettings(false)} currentUser={currentUser} />

      {/* Notification */}
      {notification && (
        <div className="notification">
          {notification}
        </div>
      )}

      {/* New Articles List */}
      {showNewArticlesList && newArticlesData && newArticlesData.new_articles > 0 && (
        <div className="new-articles-overlay" onClick={() => setShowNewArticlesList(false)}>
          <div className="new-articles-modal" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <h3><ChartBarIcon /> {newArticlesData.new_articles} Yeni Makale</h3>
              <button className="close-button" onClick={() => setShowNewArticlesList(false)}><XMarkIcon /></button>
            </div>
              <div className="modal-content">
              <div style={{ marginBottom: 8 }}>
                <label style={{ display: 'inline-flex', alignItems: 'center', gap: 8 }}>
                  <input
                    type="checkbox"
                    checked={
                      !!newArticlesData?.new_articles_list && selectedNewIndexes.length === newArticlesData.new_articles_list.length
                    }
                    onChange={(e) => {
                      if (e.target.checked) {
                        setSelectedNewIndexes(newArticlesData?.new_articles_list ? newArticlesData.new_articles_list.map((_, i: number) => i) : []);
                      } else {
                        setSelectedNewIndexes([]);
                      }
                    }}
                  />
                  Tümünü seç
                </label>
              </div>
              <ul className="new-articles-list">
                {newArticlesData.new_articles_list?.map((article, index: number) => (
                  <li key={index} style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                    <input
                      type="checkbox"
                      checked={selectedNewIndexes.includes(index)}
                      onChange={(e) => {
                        if (e.target.checked) {
                          setSelectedNewIndexes((prev) => Array.from(new Set([...prev, index])));
                        } else {
                          setSelectedNewIndexes((prev) => prev.filter((i) => i !== index));
                        }
                      }}
                    />
                    <div>
                      <div className="article-title">{article.title}</div>
                      {article.published_at && (
                        <div className="article-date">
                          {new Date(article.published_at).toLocaleDateString('tr-TR', {
                            day: '2-digit', 
                            month: '2-digit', 
                            year: 'numeric',
                            hour: '2-digit',
                            minute: '2-digit'
                          })}
                        </div>
                      )}
                    </div>
                  </li>
                ))}
              </ul>
            </div>
            <div className="modal-footer">
              <button className="cancel-button" onClick={() => setShowNewArticlesList(false)}>
                İptal
              </button>
              <button
                className="load-button"
                disabled={addArticlesMutation.isPending}
                onClick={() => {
                  if (!activeFeedId) return;
                  const feedId = activeFeedId;
                  const selected = (newArticlesData?.new_articles_list || []).filter((_, i: number) => selectedNewIndexes.includes(i));
                  if (selected.length === 0) {
                    setNotification('Makale seçilmedi.');
                    setTimeout(() => setNotification(null), 3000);
                    return;
                  }

                  addArticlesMutation.mutate(
                    { feedId, articles: selected },
                    {
                      onSuccess: (res) => {
                        setShowNewArticlesList(false);
                        if (res.created > 0) {
                          setProcessingUrls(res.created_list ?? []);
                          setNotification(`${res.created} makale işleniyor...`);
                          queryClient.invalidateQueries({ queryKey: ['articles'] });
                        } else {
                          setNotification(`Yeni makale yok. ${res.skipped} zaten mevcut.`);
                          setTimeout(() => setNotification(null), 5000);
                        }
                      },
                      onError: () => {
                        setNotification('Makaleler eklenirken hata oluştu.');
                        setTimeout(() => setNotification(null), 5000);
                      }
                    }
                  );
                }}
              >
                {addArticlesMutation.isPending ? 'Ekleniyor...' : `${selectedNewIndexes.length} makaleyi işle`}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Header */}
      <header className="dashboard-header">
        <div className="container">
          <div className="header-content">
            <div className="header-text">
              <h1><ChartBarIcon className="header-icon" /> Haber Özetleyici</h1>
            
            </div>
            <div className="header-buttons">

              <button
                className="check-button"
                onClick={handleCheckNewArticles}
                disabled={isChecking || isRefreshing}
              >
                {isChecking ? (
                  <><ArrowPathIcon className="spin-icon" /> Kontrol ediliyor...</>
                ) : newArticlesData ? (
                  <><ChartBarIcon /> {newArticlesData.new_articles} yeni makale mevcut</>
                ) : (
                  <><MagnifyingGlassIcon /> Yeni makaleleri kontrol et</>
                )}
              </button>

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
                  setImportanceMode('important');
                  setSelectedTopics((prev) =>
                    prev.includes(topicId)
                      ? prev.filter((id) => id !== topicId)
                      : [...prev, topicId]
                  );
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
                  if (p) setImportanceMode('important');
                }}
                priorityCounts={articleCounts?.by_priority ?? {}}
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
                    <ArticleList articles={articlesData.articles} />
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
