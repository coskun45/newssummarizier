import { useState, useEffect } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { useArticles, useTopics, useFeeds, useRefreshFeed, useCheckNewArticles, useAddArticlesToFeed, useCreateFeed, useDeleteFeed } from '../../hooks/useApi';
import ArticleList from '../ArticleList/ArticleList';
import TopicFilter from '../TopicFilter/TopicFilter';
import FeedSidebar from '../FeedSidebar/FeedSidebar';
import SearchBar from '../SearchBar/SearchBar';
import Settings from '../Settings/Settings';
import { Cog6ToothIcon, MagnifyingGlassIcon, ChartBarIcon, ArrowPathIcon, XMarkIcon, ArrowRightStartOnRectangleIcon } from '@heroicons/react/24/outline';
import type { AuthUser } from '../../types';
import './Dashboard.css';

interface DashboardProps {
  currentUser: AuthUser;
  onLogout: () => void;
}

function Dashboard({ currentUser, onLogout }: DashboardProps) {
  const [selectedTopics, setSelectedTopics] = useState<number[]>([]);
  const [searchQuery, setSearchQuery] = useState('');
  const [debouncedSearch, setDebouncedSearch] = useState('');
  const [notification, setNotification] = useState<string | null>(null);
  const [showNewArticlesList, setShowNewArticlesList] = useState(false);
  const [selectedNewIndexes, setSelectedNewIndexes] = useState<number[]>([]);
  const [showSettings, setShowSettings] = useState(false);
  const [processingUrls, setProcessingUrls] = useState<string[]>([]);
  const [selectedFeedId, setSelectedFeedId] = useState<number | null>(null);
  const queryClient = useQueryClient();

  const { data: topicsData } = useTopics(selectedFeedId);
  const { data: feedsData } = useFeeds();
  const { isPending: isRefreshing } = useRefreshFeed();
  const createFeedMutation = useCreateFeed();
  const deleteFeedMutation = useDeleteFeed();

  // Use selected feed for "check new" or fall back to the first feed
  const activeFeedId = selectedFeedId ?? (feedsData && feedsData.length > 0 ? feedsData[0].id : null);

  const { data: newArticlesData, refetch: checkNewArticles, isFetching: isChecking } = useCheckNewArticles(activeFeedId);
  const addArticlesMutation = useAddArticlesToFeed();

  // Debounce search
  useEffect(() => {
    const timer = setTimeout(() => {
      setDebouncedSearch(searchQuery);
    }, 300);
    return () => clearTimeout(timer);
  }, [searchQuery]);

  const filters = {
    topic_ids: selectedTopics.length > 0 ? selectedTopics.join(',') : undefined,
    search: debouncedSearch || undefined,
    limit: 50,
    feed_id: selectedFeedId ?? undefined,
  };

  const { data: articlesData, isLoading, error } = useArticles(filters);

  // Reset selected topics when feed changes
  useEffect(() => {
    setSelectedTopics([]);
  }, [selectedFeedId]);

  const handleDeleteFeed = (feedId: number) => {
    deleteFeedMutation.mutate(feedId);
    if (selectedFeedId === feedId) setSelectedFeedId(null);
  };

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
        newArticlesData.new_articles_list.map((_: any, i: number) => i)
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
      setNotification('Artikel erfolgreich verarbeitet!');
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
              <h3><ChartBarIcon /> {newArticlesData.new_articles} Neue Artikel</h3>
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
                        setSelectedNewIndexes(newArticlesData?.new_articles_list ? newArticlesData.new_articles_list.map((_: any, i: number) => i) : []);
                      } else {
                        setSelectedNewIndexes([]);
                      }
                    }}
                  />
                  Alle auswählen
                </label>
              </div>
              <ul className="new-articles-list">
                {newArticlesData.new_articles_list?.map((article: any, index: number) => (
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
                          {new Date(article.published_at).toLocaleDateString('de-DE', { 
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
                Abbrechen
              </button>
              <button
                className="load-button"
                disabled={addArticlesMutation.isPending}
                onClick={() => {
                  if (!activeFeedId) return;
                  const feedId = activeFeedId;
                  const selected = (newArticlesData?.new_articles_list || []).filter((_: any, i: number) => selectedNewIndexes.includes(i));
                  if (selected.length === 0) {
                    setNotification('Keine Artikel ausgewählt.');
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
                          setNotification(`${res.created} Artikel werden verarbeitet...`);
                          queryClient.invalidateQueries({ queryKey: ['articles'] });
                        } else {
                          setNotification(`Keine neuen Artikel. ${res.skipped} bereits vorhanden.`);
                          setTimeout(() => setNotification(null), 5000);
                        }
                      },
                      onError: () => {
                        setNotification('Fehler beim Hinzufügen der Artikel.');
                        setTimeout(() => setNotification(null), 5000);
                      }
                    }
                  );
                }}
              >
                {addArticlesMutation.isPending ? 'Wird hinzugefügt...' : `${selectedNewIndexes.length} Artikel verarbeiten`}
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
              <h1><ChartBarIcon className="header-icon" /> News Summarizer</h1>
              <p className="text-muted">Deutsche Welle - Intelligente Nachrichtenzusammenfassungen</p>
            </div>
            <div className="header-buttons">

              <button
                className="check-button"
                onClick={handleCheckNewArticles}
                disabled={isChecking || isRefreshing}
              >
                {isChecking ? (
                  <><ArrowPathIcon className="spin-icon" /> Prüfe...</>
                ) : newArticlesData ? (
                  <><ChartBarIcon /> {newArticlesData.new_articles} neue Artikel verfügbar</>
                ) : (
                  <><MagnifyingGlassIcon /> Neue Artikel prüfen</>
                )}
              </button>

              <button
                className="settings-button"
                onClick={() => setShowSettings(true)}
                title="Einstellungen"
              >
                <Cog6ToothIcon />
              </button>

              <div className="user-info">
                <span className="user-email" title={currentUser.email}>{currentUser.email}</span>
                <button
                  className="logout-button"
                  onClick={onLogout}
                  title="Abmelden"
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
            {/* Feed Sidebar */}
            <aside className="dashboard-feed-sidebar">
              <FeedSidebar
                feeds={feedsData || []}
                selectedFeedId={selectedFeedId}
                onSelectFeed={setSelectedFeedId}
                onCreateFeed={(url, title) => createFeedMutation.mutate({ url, title })}
                onDeleteFeed={handleDeleteFeed}
                isCreating={createFeedMutation.isPending}
              />
            </aside>

            {/* Topic Sidebar */}
            <aside className="dashboard-sidebar">
              <TopicFilter
                topics={topicsData || []}
                selectedTopics={selectedTopics}
                onTopicToggle={(topicId) => {
                  setSelectedTopics((prev) =>
                    prev.includes(topicId)
                      ? prev.filter((id) => id !== topicId)
                      : [...prev, topicId]
                  );
                }}
              />
            </aside>

            {/* Main Content Area */}
            <main className="dashboard-main">
              <SearchBar value={searchQuery} onChange={setSearchQuery} />

              {error && (
                <div className="error-message">
                  <p>⚠️ Fehler beim Laden der Artikel</p>
                </div>
              )}

              {isLoading ? (
                <div className="loading-state">
                  <p>⏳ Lade Artikel...</p>
                </div>
              ) : articlesData && articlesData.articles.length === 0 ? (
                <div className="empty-state">
                  <p>📭 Keine Artikel gefunden</p>
                  <p className="text-small text-muted">
                    {selectedTopics.length > 0 || searchQuery
                      ? 'Versuchen Sie andere Filter'
                      : 'Artikel werden gerade geladen...'}
                  </p>
                </div>
              ) : (
                articlesData && (
                  <>
                    <div className="results-count">
                      <p className="text-small text-muted">
                        {articlesData.total} Artikel gefunden
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
