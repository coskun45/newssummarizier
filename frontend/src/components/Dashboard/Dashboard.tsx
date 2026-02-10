import { useState, useEffect } from 'react';
import { useArticles, useTopics, useFeeds, useRefreshFeed, useCheckNewArticles } from '../../hooks/useApi';
import ArticleList from '../ArticleList/ArticleList';
import TopicFilter from '../TopicFilter/TopicFilter';
import SearchBar from '../SearchBar/SearchBar';
import Settings from '../Settings/Settings';
import { Cog6ToothIcon, MagnifyingGlassIcon, ChartBarIcon, ArrowPathIcon, CheckCircleIcon, XMarkIcon } from '@heroicons/react/24/outline';
import './Dashboard.css';

function Dashboard() {
  const [selectedTopics, setSelectedTopics] = useState<number[]>([]);
  const [searchQuery, setSearchQuery] = useState('');
  const [debouncedSearch, setDebouncedSearch] = useState('');
  const [notification, setNotification] = useState<string | null>(null);
  const [expectedNewArticles, setExpectedNewArticles] = useState<number | null>(null);
  const [showNewArticlesList, setShowNewArticlesList] = useState(false);
  const [showSettings, setShowSettings] = useState(false);

  const { data: topicsData } = useTopics();
  const { data: feedsData } = useFeeds();
  const { mutate: refreshFeed, isPending: isRefreshing } = useRefreshFeed();
  const { data: newArticlesData, refetch: checkNewArticles, isFetching: isChecking } = useCheckNewArticles(
    feedsData && feedsData.length > 0 ? feedsData[0].id : null
  );

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
  };

  const { data: articlesData, isLoading, error } = useArticles(filters);

  const handleRefreshNews = () => {
    if (feedsData && feedsData.length > 0) {
      const newCount = newArticlesData?.new_articles || 0;
      setExpectedNewArticles(newCount);
      
      // Refresh the first active feed
      refreshFeed(feedsData[0].id, {
        onSuccess: () => {
          if (newCount > 0) {
            setNotification(`${newCount} neue Artikel werden verarbeitet (kategorisiert & zusammengefasst)...`);
          } else {
            setNotification('Nachrichten werden verarbeitet...');
          }
          setTimeout(() => {
            if (newCount > 0) {
              setNotification(`${newCount} neue Artikel erfolgreich verarbeitet!`);
            } else {
              setNotification('Verarbeitung abgeschlossen. Keine neuen Artikel gefunden.');
            }
            setTimeout(() => setNotification(null), 5000);
          }, 5000);
        },
        onError: () => {
          setNotification('Fehler beim Laden der Nachrichten');
          setTimeout(() => setNotification(null), 5000);
        }
      });
    }
  };

  const handleCheckNewArticles = async () => {
    if (feedsData && feedsData.length > 0) {
      await checkNewArticles();
      setShowNewArticlesList(true);
    }
  };

  // Auto-hide notification
  useEffect(() => {
    if (notification) {
      const timer = setTimeout(() => setNotification(null), 5000);
      return () => clearTimeout(timer);
    }
  }, [notification]);

  return (
    <div className="dashboard">
      <Settings isOpen={showSettings} onClose={() => setShowSettings(false)} />

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
              <ul className="new-articles-list">
                {newArticlesData.new_articles_list?.map((article: any, index: number) => (
                  <li key={index}>
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
                  </li>
                ))}
              </ul>
              {newArticlesData.new_articles > 10 && (
                <p className="more-articles">...und {newArticlesData.new_articles - 10} weitere</p>
              )}
            </div>
            <div className="modal-footer">
              <button className="cancel-button" onClick={() => setShowNewArticlesList(false)}>
                Abbrechen
              </button>
              <button 
                className="load-button" 
                onClick={() => {
                  setShowNewArticlesList(false);
                  handleRefreshNews();
                }}
              >
                Alle {newArticlesData.new_articles} Artikel laden
              </button>
            </div>
          </div>
        </div>
      )}

      {/* 
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
            </div>
          </div>
        </div>
      </header>

      {/* Main Content */}
      <div className="dashboard-content">
        <div className="container">
          <div className="dashboard-grid">
            {/* Sidebar */}
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
