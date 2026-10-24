import { useState, useEffect } from 'react';
import { useSettings, useUpdateSettings, useTopics, useCreateTopic, useUpdateTopic, useDeleteTopic, useUsers, useCreateUser, useDeleteUser, useFeeds, useCreateFeed, useUpdateFeed, useDeleteFeed, useTestFeedConnection } from '../../hooks/useApi';
import PromptEditor from '../PromptEditor/PromptEditor';
import Features from '../Features/Features';
import ModelPicker from '../ModelPicker/ModelPicker';
import { FolderIcon, DocumentTextIcon, SparklesIcon, PencilIcon, TrashIcon, CheckIcon, XMarkIcon, PlusIcon, UsersIcon, RssIcon, ExclamationTriangleIcon, SignalIcon, CpuChipIcon } from '@heroicons/react/24/outline';
import type { AuthUser } from '../../types';
import './Settings.css';

export type SettingsCategory = 'feeds' | 'topics' | 'summaryTypes' | 'models' | 'prompts' | 'features' | 'users';

interface SettingsProps {
  category: SettingsCategory;
  currentUser: AuthUser;
}

// Choices for the automatic refresh of all feeds (seconds). The backend accepts 5 min – 24 h.
const REFRESH_INTERVAL_OPTIONS: { value: number; label: string }[] = [
  { value: 900, label: '15 dakika' },
  { value: 1800, label: '30 dakika' },
  { value: 3600, label: '1 saat' },
  { value: 7200, label: '2 saat' },
  { value: 21600, label: '6 saat' },
  { value: 43200, label: '12 saat' },
  { value: 86400, label: '24 saat' },
];

// RSS entries published longer ago than this are not ingested (hours; 0 = no limit).
const MAX_ARTICLE_AGE_OPTIONS: { value: number; label: string }[] = [
  { value: 24, label: '24 saat' },
  { value: 48, label: '48 saat' },
  { value: 72, label: '72 saat' },
  { value: 168, label: '1 hafta' },
  { value: 0, label: 'Sınır yok' },
];

const ADMIN_ONLY_NOTE = 'Bu ayarları yalnızca yöneticiler değiştirebilir.';

function Settings({ category, currentUser }: SettingsProps) {
  // Settings steer the pipeline (and its cost) for everyone — only admins may change them.
  const isAdmin = currentUser.role === 'admin';
  const { data: settings, isLoading: settingsLoading } = useSettings();
  const { data: topics } = useTopics();
  const { mutate: updateSettings, isPending: isSaving } = useUpdateSettings();
  const { mutate: createTopic, isPending: isCreatingTopic } = useCreateTopic();
  const { mutate: updateTopic, isPending: isUpdatingTopic } = useUpdateTopic();
  const { mutate: deleteTopic, isPending: isDeletingTopic } = useDeleteTopic();
  const { data: users, isLoading: isLoadingUsers, error: usersError } = useUsers();
  const { mutate: createUser, isPending: isCreatingUser } = useCreateUser();
  const { mutate: deleteUser, isPending: isDeletingUser } = useDeleteUser();
  const { data: feeds } = useFeeds();
  const { mutate: createFeed, isPending: isCreatingFeed } = useCreateFeed();
  const { mutate: updateFeed, isPending: isUpdatingFeed } = useUpdateFeed();
  const { mutate: deleteFeed, isPending: isDeletingFeed } = useDeleteFeed();
  const { mutate: testFeedConnection, isPending: isTestingFeed } = useTestFeedConnection();

  const [enabledTopicIds, setEnabledTopicIds] = useState<number[]>([]);
  const [enabledSummaryTypes, setEnabledSummaryTypes] = useState<string[]>([]);
  const [refreshInterval, setRefreshInterval] = useState<number>(3600);
  const [maxArticleAge, setMaxArticleAge] = useState<number>(72);
  const [classificationModel, setClassificationModel] = useState<string | null>(null);
  const [summaryModel, setSummaryModel] = useState<string | null>(null);
  const [showAddTopic, setShowAddTopic] = useState(false);
  const [newTopicName, setNewTopicName] = useState('');
  const [newTopicDescription, setNewTopicDescription] = useState('');
  const [editingTopicId, setEditingTopicId] = useState<number | null>(null);
  const [editTopicName, setEditTopicName] = useState('');
  const [editTopicDescription, setEditTopicDescription] = useState('');
  
  // User management form state
  const [newUserEmail, setNewUserEmail] = useState('');
  const [newUserPassword, setNewUserPassword] = useState('');
  const [newUserRole, setNewUserRole] = useState<'admin' | 'user'>('user');
  const [userError, setUserError] = useState('');

  // Feed management form state
  const [showAddFeed, setShowAddFeed] = useState(false);
  const [newFeedUrl, setNewFeedUrl] = useState('');
  const [newFeedTitle, setNewFeedTitle] = useState('');
  const [editingFeedId, setEditingFeedId] = useState<number | null>(null);
  const [editFeedUrl, setEditFeedUrl] = useState('');
  const [editFeedTitle, setEditFeedTitle] = useState('');
  const [feedError, setFeedError] = useState('');
  const [addFeedTested, setAddFeedTested] = useState(false);
  const [editFeedTested, setEditFeedTested] = useState(false);

  // Initialize form when settings load
  // Each tab's form syncs only when ITS server value changes (deps are the primitive values, not
  // the settings object): tabs save separately, and the refetch after saving one tab must not
  // wipe unsaved edits in another.
  const serverTopics = settings?.enabled_topics;
  const serverSummaryTypes = settings?.enabled_summary_types;
  const serverRefreshInterval = settings?.feed_refresh_interval;
  const serverMaxArticleAge = settings?.max_article_age_hours;
  const serverClassificationModel = settings?.classification_model;
  const serverSummaryModel = settings?.summary_model;

  useEffect(() => {
    if (serverTopics === undefined) return;
    setEnabledTopicIds(serverTopics
      ? serverTopics.split(',').map(id => parseInt(id.trim())).filter(id => !isNaN(id))
      : []);
  }, [serverTopics]);

  useEffect(() => {
    if (serverSummaryTypes === undefined) return;
    setEnabledSummaryTypes(serverSummaryTypes
      ? serverSummaryTypes.split(',').map(t => t.trim())
      : ['brief', 'standard', 'detailed']);
  }, [serverSummaryTypes]);

  useEffect(() => {
    if (serverRefreshInterval !== undefined) setRefreshInterval(serverRefreshInterval);
  }, [serverRefreshInterval]);

  useEffect(() => {
    if (serverMaxArticleAge !== undefined) setMaxArticleAge(serverMaxArticleAge);
  }, [serverMaxArticleAge]);

  useEffect(() => {
    if (serverClassificationModel !== undefined) setClassificationModel(serverClassificationModel);
  }, [serverClassificationModel]);

  useEffect(() => {
    if (serverSummaryModel !== undefined) setSummaryModel(serverSummaryModel);
  }, [serverSummaryModel]);

  // Empty = all topics. Unchecking the last checked topic would therefore silently re-enable
  // every topic, so the last one stays checked instead.
  const isLastCheckedTopic = (topicId: number) =>
    enabledTopicIds.length === 0
      ? (topics?.length ?? 0) === 1
      : enabledTopicIds.length === 1 && enabledTopicIds[0] === topicId;

  const handleTopicToggle = (topicId: number) => {
    if (isLastCheckedTopic(topicId)) return;
    if (enabledTopicIds.length === 0) {
      // Empty = all topics selected. Deselect one → select all others explicitly.
      setEnabledTopicIds((topics || []).map(t => t.id).filter(id => id !== topicId));
    } else {
      setEnabledTopicIds(prev =>
        prev.includes(topicId)
          ? prev.filter(id => id !== topicId)
          : [...prev, topicId]
      );
    }
  };

  const handleSummaryTypeToggle = (type: string) => {
    setEnabledSummaryTypes(prev =>
      prev.includes(type)
        ? prev.filter(t => t !== type)
        : [...prev, type]
    );
  };

  const handleAddTopic = () => {
    if (newTopicName.trim()) {
      createTopic({
        name: newTopicName.trim(),
        description: newTopicDescription.trim() || undefined
      }, {
        onSuccess: () => {
          setNewTopicName('');
          setNewTopicDescription('');
          setShowAddTopic(false);
        }
      });
    }
  };

  const handleEditTopic = (topicId: number, name: string, description?: string) => {
    setEditingTopicId(topicId);
    setEditTopicName(name);
    setEditTopicDescription(description || '');
  };

  const handleSaveEdit = () => {
    if (editingTopicId && editTopicName.trim()) {
      updateTopic({
        topicId: editingTopicId,
        name: editTopicName.trim(),
        description: editTopicDescription.trim() || undefined
      }, {
        onSuccess: () => {
          setEditingTopicId(null);
          setEditTopicName('');
          setEditTopicDescription('');
        }
      });
    }
  };

  const handleCancelEdit = () => {
    setEditingTopicId(null);
    setEditTopicName('');
    setEditTopicDescription('');
  };

  const handleDeleteTopic = (topicId: number, topicName: string) => {
    if (confirm(`"${topicName}" kategorisini silmek istediğinizden emin misiniz? Tüm makale atamaları kaldırılacak.`)) {
      deleteTopic(topicId);
    }
  };

  const handleAddUser = () => {
    setUserError('');
    if (!newUserEmail.trim() || !newUserPassword.trim()) return;
    createUser(
      { email: newUserEmail.trim(), password: newUserPassword, role: newUserRole },
      {
        onSuccess: () => {
          setNewUserEmail('');
          setNewUserPassword('');
          setNewUserRole('user');
        },
        onError: (err: unknown) => {
          const axiosErr = err as { response?: { data?: { detail?: string } } };
          setUserError(axiosErr.response?.data?.detail ?? 'Kullanıcı oluşturulurken hata oluştu.');
        },
      }
    );
  };

  const handleDeleteUser = (userId: number, userEmail: string) => {
    if (confirm(`"${userEmail}" kullanıcısını silmek istediğinizden emin misiniz?`)) {
      deleteUser(userId);
    }
  };

  const handleTestAddFeedConnection = () => {
    if (!newFeedUrl.trim()) return;
    setFeedError('');
    testFeedConnection(newFeedUrl.trim(), {
      onSuccess: () => setAddFeedTested(true),
      onError: (err: unknown) => {
        setAddFeedTested(false);
        const axiosErr = err as { response?: { data?: { detail?: string } } };
        setFeedError(axiosErr.response?.data?.detail ?? 'Bağlantı testi başarısız oldu.');
      },
    });
  };

  const handleAddFeed = () => {
    if (!newFeedUrl.trim() || !newFeedTitle.trim() || !addFeedTested) return;
    setFeedError('');
    createFeed({ url: newFeedUrl.trim(), title: newFeedTitle.trim() }, {
      onSuccess: () => {
        setNewFeedUrl('');
        setNewFeedTitle('');
        setAddFeedTested(false);
        setShowAddFeed(false);
      },
      onError: (err: unknown) => {
        const axiosErr = err as { response?: { data?: { detail?: string } } };
        setFeedError(axiosErr.response?.data?.detail ?? 'Besleme eklenirken hata oluştu.');
      },
    });
  };

  const handleDeleteFeed = (feedId: number, feedUrl: string) => {
    if (confirm(`"${feedUrl}" beslemesini silmek istediğinizden emin misiniz?`)) {
      deleteFeed(feedId);
    }
  };

  const handleEditFeed = (feedId: number, url: string, title?: string | null) => {
    setFeedError('');
    setEditFeedTested(false);
    setEditingFeedId(feedId);
    setEditFeedUrl(url);
    setEditFeedTitle(title || '');
  };

  const handleCancelFeedEdit = () => {
    setFeedError('');
    setEditFeedTested(false);
    setEditingFeedId(null);
    setEditFeedUrl('');
    setEditFeedTitle('');
  };

  const handleTestEditFeedConnection = () => {
    if (!editFeedUrl.trim()) return;
    setFeedError('');
    testFeedConnection(editFeedUrl.trim(), {
      onSuccess: () => setEditFeedTested(true),
      onError: (err: unknown) => {
        setEditFeedTested(false);
        const axiosErr = err as { response?: { data?: { detail?: string } } };
        setFeedError(axiosErr.response?.data?.detail ?? 'Bağlantı testi başarısız oldu.');
      },
    });
  };

  const handleSaveFeedEdit = () => {
    const editingFeed = feeds?.find(f => f.id === editingFeedId);
    const urlChanged = !editingFeed || editFeedUrl.trim() !== editingFeed.url;
    if (editingFeedId && editFeedUrl.trim() && editFeedTitle.trim() && (!urlChanged || editFeedTested)) {
      setFeedError('');
      updateFeed({
        feedId: editingFeedId,
        url: editFeedUrl.trim(),
        title: editFeedTitle.trim()
      }, {
        onSuccess: handleCancelFeedEdit,
        onError: (err: unknown) => {
          const axiosErr = err as { response?: { data?: { detail?: string } } };
          setFeedError(axiosErr.response?.data?.detail ?? 'Besleme güncellenirken hata oluştu.');
        },
      });
    }
  };

  const getFeedLabel = (feed: { title?: string | null; url: string }) => {
    if (feed.title) return feed.title;
    try { return new URL(feed.url).hostname.replace('www.', ''); } catch { return feed.url; }
  };

  // Each tab saves only its own fields (PUT /settings is partial): saving one tab must never put
  // an unsaved edit from another tab live — e.g. an expensive model picked but not saved.
  const saveRefreshInterval = () => updateSettings({ feed_refresh_interval: refreshInterval });
  const saveMaxArticleAge = () => updateSettings({ max_article_age_hours: maxArticleAge });
  const saveTopics = () => updateSettings({ enabled_topics: enabledTopicIds.join(',') });
  const saveSummaryTypes = () => updateSettings({ enabled_summary_types: enabledSummaryTypes.join(',') });
  const modelsChanged =
    classificationModel !== (settings?.classification_model ?? null)
    || summaryModel !== (settings?.summary_model ?? null);
  // Only the changed model is sent; "" clears a choice (back to the server default).
  const saveModels = () => updateSettings({
    ...(classificationModel !== (settings?.classification_model ?? null)
      ? { classification_model: classificationModel ?? '' } : {}),
    ...(summaryModel !== (settings?.summary_model ?? null) ? { summary_model: summaryModel ?? '' } : {}),
  });

  if (settingsLoading) {
    return <div className="loading">Ayarlar yükleniyor...</div>;
  }

  return (
    <div className="settings-page-content">
      {category === 'feeds' && (
        <div className="settings-category">
          <h2 className="settings-content-title"><RssIcon className="section-icon" /> RSS Beslemeleri</h2>
          <div className="section-content">
                    <p className="section-description">
                      RSS besleme kaynaklarını yönetin.
                    </p>
                    <div className="refresh-interval-row">
                      <label htmlFor="feed-refresh-interval" className="checkbox-text">
                        Otomatik yenileme aralığı
                      </label>
                      <select
                        id="feed-refresh-interval"
                        className="topic-input"
                        value={refreshInterval}
                        onChange={(e) => setRefreshInterval(Number(e.target.value))}
                        disabled={!isAdmin || isSaving}
                      >
                        {!REFRESH_INTERVAL_OPTIONS.some(o => o.value === refreshInterval) && (
                          <option value={refreshInterval}>{Math.round(refreshInterval / 60)} dakika</option>
                        )}
                        {REFRESH_INTERVAL_OPTIONS.map(o => (
                          <option key={o.value} value={o.value}>{o.label}</option>
                        ))}
                      </select>
                      {isAdmin ? (
                        <button
                          className="save-button"
                          onClick={saveRefreshInterval}
                          disabled={isSaving || refreshInterval === settings?.feed_refresh_interval}
                        >
                          {isSaving ? 'Kaydediliyor...' : 'Aralığı kaydet'}
                        </button>
                      ) : (
                        <p className="section-description">{ADMIN_ONLY_NOTE}</p>
                      )}
                    </div>
                    <div className="refresh-interval-row">
                      <label htmlFor="max-article-age" className="checkbox-text">
                        En fazla haber yaşı
                      </label>
                      <select
                        id="max-article-age"
                        className="topic-input"
                        value={maxArticleAge}
                        onChange={(e) => setMaxArticleAge(Number(e.target.value))}
                        disabled={!isAdmin || isSaving}
                      >
                        {!MAX_ARTICLE_AGE_OPTIONS.some(o => o.value === maxArticleAge) && (
                          <option value={maxArticleAge}>{maxArticleAge} saat</option>
                        )}
                        {MAX_ARTICLE_AGE_OPTIONS.map(o => (
                          <option key={o.value} value={o.value}>{o.label}</option>
                        ))}
                      </select>
                      {isAdmin && (
                        <button
                          className="save-button"
                          onClick={saveMaxArticleAge}
                          disabled={isSaving || maxArticleAge === settings?.max_article_age_hours}
                        >
                          {isSaving ? 'Kaydediliyor...' : 'Yaş sınırını kaydet'}
                        </button>
                      )}
                      <p className="section-description">
                        Bundan eski yayın tarihli RSS kayıtları alınmaz.
                      </p>
                    </div>
                    <div className="user-list">
                      {feeds?.map(feed => (
                        editingFeedId === feed.id ? (
                          <div key={feed.id} className="add-topic-form">
                            <input
                              type="url"
                              className="topic-input"
                              placeholder="RSS URL"
                              value={editFeedUrl}
                              onChange={(e) => { setEditFeedUrl(e.target.value); setEditFeedTested(false); }}
                              disabled={isUpdatingFeed}
                            />
                            <input
                              type="text"
                              className="topic-input"
                              placeholder="Ad (zorunlu, haberlerde Kaynak olarak görünür)"
                              aria-label="Besleme adı"
                              required
                              value={editFeedTitle}
                              onChange={(e) => setEditFeedTitle(e.target.value)}
                              disabled={isUpdatingFeed}
                            />
                            <button
                              type="button"
                              className="test-connection-button"
                              onClick={handleTestEditFeedConnection}
                              disabled={isTestingFeed || isUpdatingFeed || !editFeedUrl.trim()}
                            >
                              <SignalIcon /> {isTestingFeed ? 'Test ediliyor...' : 'Bağlantıyı Test Et'}
                            </button>
                            {editFeedTested && !feedError && (
                              <p className="success-text"><CheckIcon /> Bağlantı başarılı</p>
                            )}
                            {feedError && (
                              <p className="warning-text"><ExclamationTriangleIcon /> {feedError}</p>
                            )}
                            <div className="add-topic-buttons">
                              <button
                                className="cancel-add-button"
                                onClick={handleCancelFeedEdit}
                                disabled={isUpdatingFeed}
                              >
                                İptal
                              </button>
                              <button
                                className="confirm-add-button"
                                onClick={handleSaveFeedEdit}
                                disabled={
                                  isUpdatingFeed ||
                                  !editFeedUrl.trim() ||
                                  !editFeedTitle.trim() ||
                                  (editFeedUrl.trim() !== feed.url && !editFeedTested)
                                }
                              >
                                {isUpdatingFeed ? 'Kaydediliyor...' : 'Kaydet'}
                              </button>
                            </div>
                          </div>
                        ) : (
                          <div key={feed.id} className="user-list-item">
                            <div className="user-list-info">
                              <span className="user-list-email">{getFeedLabel(feed)}</span>
                              <span className="user-role-badge" title={feed.url}>{new URL(feed.url).hostname}</span>
                            </div>
                            <div className="topic-actions">
                              <button
                                className="edit-topic-button"
                                onClick={() => handleEditFeed(feed.id, feed.url, feed.title)}
                                title="Beslemeyi düzenle"
                              >
                                <PencilIcon />
                              </button>
                              <button
                                className="delete-topic-button"
                                onClick={() => handleDeleteFeed(feed.id, getFeedLabel(feed))}
                                disabled={isDeletingFeed}
                                title="Beslemeyi sil"
                              >
                                <TrashIcon />
                              </button>
                            </div>
                          </div>
                        )
                      ))}
                    </div>
                    {!showAddFeed ? (
                      <button className="add-topic-button" onClick={() => { setFeedError(''); setAddFeedTested(false); setShowAddFeed(true); }}>
                        <PlusIcon /> Yeni besleme ekle
                      </button>
                    ) : (
                      <div className="add-topic-form">
                        <input
                          type="url"
                          className="topic-input"
                          placeholder="RSS URL (ör. https://example.com/feed.xml)"
                          value={newFeedUrl}
                          onChange={(e) => { setNewFeedUrl(e.target.value); setAddFeedTested(false); }}
                          disabled={isCreatingFeed}
                        />
                        <input
                          type="text"
                          className="topic-input"
                          placeholder="Ad (zorunlu, haberlerde Kaynak olarak görünür)"
                          aria-label="Besleme adı"
                          required
                          value={newFeedTitle}
                          onChange={(e) => setNewFeedTitle(e.target.value)}
                          disabled={isCreatingFeed}
                        />
                        <button
                          type="button"
                          className="test-connection-button"
                          onClick={handleTestAddFeedConnection}
                          disabled={isTestingFeed || isCreatingFeed || !newFeedUrl.trim()}
                        >
                          <SignalIcon /> {isTestingFeed ? 'Test ediliyor...' : 'Bağlantıyı Test Et'}
                        </button>
                        {addFeedTested && !feedError && (
                          <p className="success-text"><CheckIcon /> Bağlantı başarılı</p>
                        )}
                        {feedError && (
                          <p className="warning-text"><ExclamationTriangleIcon /> {feedError}</p>
                        )}
                        <div className="add-topic-buttons">
                          <button
                            className="cancel-add-button"
                            onClick={() => { setFeedError(''); setAddFeedTested(false); setShowAddFeed(false); setNewFeedUrl(''); setNewFeedTitle(''); }}
                            disabled={isCreatingFeed}
                          >
                            İptal
                          </button>
                          <button
                            className="confirm-add-button"
                            onClick={handleAddFeed}
                            disabled={isCreatingFeed || !newFeedUrl.trim() || !newFeedTitle.trim() || !addFeedTested}
                            title={!newFeedTitle.trim() ? 'Besleme adı zorunlu' : !addFeedTested ? 'Önce bağlantıyı test edin' : undefined}
                          >
                            {isCreatingFeed ? 'Ekleniyor...' : 'Ekle'}
                          </button>
                        </div>
                      </div>
                    )}
          </div>
        </div>
      )}

      {category === 'topics' && (
        <div className="settings-category">
          <h2 className="settings-content-title"><FolderIcon className="section-icon" /> Kategoriler</h2>
          <div className="section-content">
            <p className="section-description">
              Yapay zeka haberleri yalnızca seçili kategorilere atar.
              En az bir kategori seçili kalmalıdır.
            </p>
                <div className="checkbox-group">
                  {topics?.map(topic => (
                    <div key={topic.id} className="topic-item">
                      {editingTopicId === topic.id ? (
                        <div className="edit-topic-form">
                          <input
                            type="text"
                            className="topic-input"
                            value={editTopicName}
                            onChange={(e) => setEditTopicName(e.target.value)}
                            disabled={isUpdatingTopic}
                          />
                          <input
                            type="text"
                            className="topic-input"
                            placeholder="Açıklama (isteğe bağlı)"
                            value={editTopicDescription}
                            onChange={(e) => setEditTopicDescription(e.target.value)}
                            disabled={isUpdatingTopic}
                          />
                          <div className="edit-topic-buttons">
                            <button 
                              className="cancel-edit-button"
                              onClick={handleCancelEdit}
                              disabled={isUpdatingTopic}
                            >
                              <XMarkIcon />
                            </button>
                            <button 
                              className="save-edit-button"
                              onClick={handleSaveEdit}
                              disabled={isUpdatingTopic || !editTopicName.trim()}
                            >
                              <CheckIcon />
                            </button>
                          </div>
                        </div>
                      ) : (
                        <label className="checkbox-label">
                          <input
                            type="checkbox"
                            checked={enabledTopicIds.length === 0 || enabledTopicIds.includes(topic.id)}
                            onChange={() => handleTopicToggle(topic.id)}
                            disabled={!isAdmin || isLastCheckedTopic(topic.id)}
                            title={isLastCheckedTopic(topic.id) ? 'En az bir kategori seçili kalmalı' : undefined}
                          />
                          <span className="checkbox-text">
                            {topic.name} ({topic.article_count || 0})
                          </span>
                          <div className="topic-actions">
                            <button
                              className="edit-topic-button"
                              onClick={(e) => {
                                e.preventDefault();
                                handleEditTopic(topic.id, topic.name, topic.description || '');
                              }}
                              title="Düzenle"
                            >
                              <PencilIcon />
                            </button>
                            <button
                              className="delete-topic-button"
                              onClick={(e) => {
                                e.preventDefault();
                                handleDeleteTopic(topic.id, topic.name);
                              }}
                              disabled={isDeletingTopic}
                              title="Sil"
                            >
                              <TrashIcon />
                            </button>
                          </div>
                        </label>
                      )}
                    </div>
                  ))}
                </div>
                {enabledTopicIds.length > 0 && (
                  <button 
                    className="clear-selection-button"
                    onClick={() => setEnabledTopicIds([])}
                  >
                    Tümünü seç
                  </button>
                )}
                
                {/* Add New Topic Section */}
                {!showAddTopic ? (
                  <button 
                    className="add-topic-button"
                    onClick={() => setShowAddTopic(true)}
                  >
                    <PlusIcon /> Yeni kategori ekle
                  </button>
                ) : (
                  <div className="add-topic-form">
                    <input
                      type="text"
                      className="topic-input"
                      placeholder="Kategori adı (ör. Teknoloji)"
                      value={newTopicName}
                      onChange={(e) => setNewTopicName(e.target.value)}
                      disabled={isCreatingTopic}
                    />
                    <input
                      type="text"
                      className="topic-input"
                      placeholder="Açıklama (isteğe bağlı)"
                      value={newTopicDescription}
                      onChange={(e) => setNewTopicDescription(e.target.value)}
                      disabled={isCreatingTopic}
                    />
                    <div className="add-topic-buttons">
                      <button 
                        className="cancel-add-button"
                        onClick={() => {
                          setShowAddTopic(false);
                          setNewTopicName('');
                          setNewTopicDescription('');
                        }}
                        disabled={isCreatingTopic}
                      >
                        İptal
                      </button>
                      <button
                        className="confirm-add-button"
                        onClick={handleAddTopic}
                        disabled={isCreatingTopic || !newTopicName.trim()}
                      >
                        {isCreatingTopic ? 'Oluşturuluyor...' : 'Oluştur'}
                      </button>
                    </div>
                  </div>
                )}
            </div>
            <div className="settings-save-row">
              {isAdmin ? (
                <button
                  className="save-button"
                  onClick={saveTopics}
                  disabled={isSaving}
                >
                  {isSaving ? 'Kaydediliyor...' : 'Ayarları kaydet'}
                </button>
              ) : (
                <p className="section-description">{ADMIN_ONLY_NOTE}</p>
              )}
            </div>
          </div>
      )}

      {category === 'summaryTypes' && (
        <div className="settings-category">
          <h2 className="settings-content-title"><DocumentTextIcon className="section-icon" /> Özet Türleri</h2>
          <div className="section-content">
            <p className="section-description">
              Hangi özet türlerinin oluşturulacağını seçin.
              Birden fazla seçim mümkün.
            </p>
                <div className="checkbox-group">
                  <label className="checkbox-label">
                    <input
                      type="checkbox"
                      checked={enabledSummaryTypes.includes('brief')}
                      onChange={() => handleSummaryTypeToggle('brief')}
                      disabled={!isAdmin}
                    />
                    <span className="checkbox-text">
                      <strong>Kısa</strong> - 2-3 cümle
                    </span>
                  </label>
                  <label className="checkbox-label">
                    <input
                      type="checkbox"
                      checked={enabledSummaryTypes.includes('standard')}
                      onChange={() => handleSummaryTypeToggle('standard')}
                      disabled={!isAdmin}
                    />
                    <span className="checkbox-text">
                      <strong>Standart</strong> - Bir paragraf
                    </span>
                  </label>
                  <label className="checkbox-label">
                    <input
                      type="checkbox"
                      checked={enabledSummaryTypes.includes('detailed')}
                      onChange={() => handleSummaryTypeToggle('detailed')}
                      disabled={!isAdmin}
                    />
                    <span className="checkbox-text">
                      <strong>Detaylı</strong> - Birden fazla paragraf (daha yüksek maliyet)
                    </span>
                  </label>
                </div>
                {enabledSummaryTypes.length === 0 && (
                  <p className="warning-text"><ExclamationTriangleIcon /> En az bir tür seçilmelidir</p>
                )}
            </div>
            <div className="settings-save-row">
              {isAdmin ? (
                <button
                  className="save-button"
                  onClick={saveSummaryTypes}
                  disabled={isSaving || enabledSummaryTypes.length === 0}
                >
                  {isSaving ? 'Kaydediliyor...' : 'Ayarları kaydet'}
                </button>
              ) : (
                <p className="section-description">{ADMIN_ONLY_NOTE}</p>
              )}
            </div>
          </div>
      )}

      {category === 'models' && (
        <div className="settings-category">
          <h2 className="settings-content-title"><CpuChipIcon className="section-icon" /> Yapay Zekâ Modelleri</h2>
          <div className="section-content">
            <p className="section-description">
              Sınıflandırma ve özetler için kullanılacak OpenAI modelini seçin.
              Fiyatı görmek için bir modelin üzerine gelin.
            </p>
            <ModelPicker
              name="classification-model"
              label="Sınıflandırma modeli"
              hint="Her haber için önem, öncelik ve kategoriyi belirler; bülten de bu modelle hazırlanır."
              models={settings?.available_models ?? []}
              value={classificationModel}
              defaultIds={settings ? [settings.default_models.classification] : []}
              onChange={setClassificationModel}
              disabled={!isAdmin || isSaving}
            />
            <ModelPicker
              name="summary-model"
              label="Özet modeli"
              hint="Kısa, standart ve detaylı özetlerin hepsi bu modelle yazılır."
              models={settings?.available_models ?? []}
              value={summaryModel}
              defaultIds={settings ? [settings.default_models.summary, settings.default_models.detailed_summary] : []}
              onChange={setSummaryModel}
              disabled={!isAdmin || isSaving}
            />
          </div>
          <div className="settings-save-row">
            {isAdmin ? (
              <button
                className="save-button"
                onClick={saveModels}
                disabled={isSaving || !modelsChanged}
              >
                {isSaving ? 'Kaydediliyor...' : 'Modelleri kaydet'}
              </button>
            ) : (
              <p className="section-description">{ADMIN_ONLY_NOTE}</p>
            )}
          </div>
        </div>
      )}

      {category === 'prompts' && (
        <div className="settings-category">
          <h2 className="settings-content-title"><SparklesIcon className="section-icon" /> Sistem Promptları</h2>
          <div className="section-content">
            <p className="section-description">
              Yapay zeka sınıflandırma ve özetleme için kullanılan sistem promptlarını düzenleyin.
            </p>

            <PromptEditor
              promptType="classification"
              label="Sınıflandırma Promptu"
              description="Makalelerin önem ve öncelik kriterlerini belirler. Konu listesi ve JSON çıktı formatı sistem tarafından otomatik eklenir; aşağıda kilitli olarak görünür."
              showLockedPart
            />

            <PromptEditor
              promptType="summarization"
              label="Özetleme Promptu"
              description="Bu prompt makale özetleri oluşturmak için kullanılır. Etkin özet türlerinin (Özet Türleri ayarı) talimatları sistem tarafından otomatik eklenir; aşağıda kilitli olarak görünür."
              showLockedPart
            />
          </div>
        </div>
      )}

      {category === 'features' && <Features />}

      {category === 'users' && currentUser.role === 'admin' && (
                <div className="settings-category">
                  <h2 className="settings-content-title"><UsersIcon className="section-icon" /> Kullanıcı Yönetimi</h2>
                    <div className="section-content">
                      <p className="section-description">
                        Kullanıcı hesaplarını yönetin. Yalnızca yöneticiler bu ayarları görebilir.
                      </p>

                      {/* Existing users list */}
                      <div className="user-list">
                        {isLoadingUsers && <p className="section-description">Kullanıcılar yükleniyor...</p>}
                        {usersError && <p className="error-message">Kullanıcılar yüklenemedi.</p>}
                        {users?.map(user => (
                          <div key={user.id} className="user-list-item">
                            <div className="user-list-info">
                              <span className="user-list-email">{user.email}</span>
                              <span className={`user-role-badge user-role-${user.role}`}>{user.role}</span>
                            </div>
                            {user.id !== currentUser.id && (
                              <button
                                className="delete-topic-button"
                                onClick={() => handleDeleteUser(user.id, user.email)}
                                disabled={isDeletingUser}
                                title="Kullanıcıyı sil"
                              >
                                <TrashIcon />
                              </button>
                            )}
                          </div>
                        ))}
                      </div>

                      {/* Add new user form */}
                      <div className="add-user-form">
                        <h4 className="add-user-title"><PlusIcon className="inline-icon" /> Yeni Kullanıcı</h4>
                        <input
                          type="email"
                          className="topic-input"
                          placeholder="E-Posta Adresi"
                          value={newUserEmail}
                          onChange={(e) => setNewUserEmail(e.target.value)}
                          disabled={isCreatingUser}
                        />
                        <input
                          type="password"
                          className="topic-input"
                          placeholder="Şifre"
                          value={newUserPassword}
                          onChange={(e) => setNewUserPassword(e.target.value)}
                          disabled={isCreatingUser}
                        />
                        <select
                          className="topic-input"
                          value={newUserRole}
                          onChange={(e) => setNewUserRole(e.target.value as 'admin' | 'user')}
                          disabled={isCreatingUser}
                        >
                          <option value="user">user</option>
                          <option value="admin">admin</option>
                        </select>
                        {userError && <p className="warning-text"><ExclamationTriangleIcon /> {userError}</p>}
                        <button
                          className="confirm-add-button"
                          onClick={handleAddUser}
                          disabled={isCreatingUser || !newUserEmail.trim() || !newUserPassword.trim()}
                        >
                          {isCreatingUser ? 'Oluşturuluyor...' : 'Kullanıcı oluştur'}
                        </button>
                      </div>
                    </div>
                </div>
      )}
    </div>
  );
}

export default Settings;
