import { useState, useEffect } from 'react';
import { useSettings, useUpdateSettings, useTopics, useCreateTopic, useUpdateTopic, useDeleteTopic, useUsers, useCreateUser, useDeleteUser, useFeeds, useCreateFeed, useDeleteFeed } from '../../hooks/useApi';
import PromptEditor from '../PromptEditor/PromptEditor';
import { Cog6ToothIcon, FolderIcon, DocumentTextIcon, SparklesIcon, PencilIcon, TrashIcon, CheckIcon, XMarkIcon, PlusIcon, ChevronDownIcon, ChevronRightIcon, UsersIcon, RssIcon } from '@heroicons/react/24/outline';
import type { AuthUser } from '../../types';
import './Settings.css';

interface SettingsProps {
  isOpen: boolean;
  onClose: () => void;
  currentUser: AuthUser;
}

function Settings({ isOpen, onClose, currentUser }: SettingsProps) {
  const { data: settings, isLoading: settingsLoading } = useSettings();
  const { data: topics } = useTopics();
  const { mutate: updateSettings, isPending: isSaving } = useUpdateSettings();
  const { mutate: createTopic, isPending: isCreatingTopic } = useCreateTopic();
  const { mutate: updateTopic, isPending: isUpdatingTopic } = useUpdateTopic();
  const { mutate: deleteTopic, isPending: isDeletingTopic } = useDeleteTopic();
  const { data: users } = useUsers();
  const { mutate: createUser, isPending: isCreatingUser } = useCreateUser();
  const { mutate: deleteUser, isPending: isDeletingUser } = useDeleteUser();
  const { data: feeds } = useFeeds();
  const { mutate: createFeed, isPending: isCreatingFeed } = useCreateFeed();
  const { mutate: deleteFeed, isPending: isDeletingFeed } = useDeleteFeed();

  const [enabledTopicIds, setEnabledTopicIds] = useState<number[]>([]);
  const [enabledSummaryTypes, setEnabledSummaryTypes] = useState<string[]>([]);
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

  // Accordion state for sections
  const [expandedSections, setExpandedSections] = useState<Record<string, boolean>>({
    feeds: false,
    topics: true,
    summaryTypes: false,
    prompts: false,
    users: false,
  });

  const toggleSection = (section: string) => {
    setExpandedSections(prev => ({
      ...prev,
      [section]: !prev[section]
    }));
  };

  // Initialize form when settings load
  useEffect(() => {
    if (settings) {
      // Parse enabled topics
      const topicIds = settings.enabled_topics
        ? settings.enabled_topics.split(',').map(id => parseInt(id.trim())).filter(id => !isNaN(id))
        : [];
      setEnabledTopicIds(topicIds);

      // Parse enabled summary types
      const summaryTypes = settings.enabled_summary_types
        ? settings.enabled_summary_types.split(',').map(t => t.trim())
        : ['brief', 'standard', 'detailed'];
      setEnabledSummaryTypes(summaryTypes);
    }
  }, [settings]);

  const handleTopicToggle = (topicId: number) => {
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

  const handleAddFeed = () => {
    if (!newFeedUrl.trim()) return;
    createFeed({ url: newFeedUrl.trim(), title: newFeedTitle.trim() || undefined }, {
      onSuccess: () => {
        setNewFeedUrl('');
        setNewFeedTitle('');
        setShowAddFeed(false);
      }
    });
  };

  const handleDeleteFeed = (feedId: number, feedUrl: string) => {
    if (confirm(`"${feedUrl}" beslemesini silmek istediğinizden emin misiniz?`)) {
      deleteFeed(feedId);
    }
  };

  const getFeedLabel = (feed: { title?: string; url: string }) => {
    if (feed.title) return feed.title;
    try { return new URL(feed.url).hostname.replace('www.', ''); } catch { return feed.url; }
  };

  const handleSave = () => {
    updateSettings({
      enabled_topics: enabledTopicIds.join(','),
      enabled_summary_types: enabledSummaryTypes.join(','),
      feed_refresh_interval: settings?.feed_refresh_interval || 1800
    }, {
      onSuccess: () => {
        onClose();
      }
    });
  };

  if (!isOpen) return null;

  return (
    <div className="settings-overlay" onClick={onClose}>
      <div className="settings-modal" onClick={(e) => e.stopPropagation()}>
        <div className="settings-header">
          <h2><Cog6ToothIcon className="header-icon" /> Ayarlar</h2>
          <button className="close-button" onClick={onClose}><XMarkIcon /></button>
        </div>

        <div className="settings-content">
          {settingsLoading ? (
            <div className="loading">Ayarlar yükleniyor...</div>
          ) : (
            <>
              {/* RSS Feeds Section */}
              <div className="settings-section">
                <div
                  className="section-header"
                  onClick={() => toggleSection('feeds')}
                >
                  <h3>
                    {expandedSections.feeds ? <ChevronDownIcon className="collapse-icon" /> : <ChevronRightIcon className="collapse-icon" />}
                    <RssIcon className="section-icon" /> RSS Beslemeleri
                  </h3>
                </div>
                {expandedSections.feeds && (
                  <div className="section-content">
                    <p className="section-description">
                      RSS besleme kaynaklarını yönetin.
                    </p>
                    <div className="user-list">
                      {feeds?.map(feed => (
                        <div key={feed.id} className="user-list-item">
                          <div className="user-list-info">
                            <span className="user-list-email">{getFeedLabel(feed)}</span>
                            <span className="user-role-badge" title={feed.url}>{new URL(feed.url).hostname}</span>
                          </div>
                          <button
                            className="delete-topic-button"
                            onClick={() => handleDeleteFeed(feed.id, getFeedLabel(feed))}
                            disabled={isDeletingFeed}
                            title="Beslemeyi sil"
                          >
                            <TrashIcon />
                          </button>
                        </div>
                      ))}
                    </div>
                    {!showAddFeed ? (
                      <button className="add-topic-button" onClick={() => setShowAddFeed(true)}>
                        <PlusIcon /> Yeni besleme ekle
                      </button>
                    ) : (
                      <div className="add-topic-form">
                        <input
                          type="url"
                          className="topic-input"
                          placeholder="RSS URL (ör. https://example.com/feed.xml)"
                          value={newFeedUrl}
                          onChange={(e) => setNewFeedUrl(e.target.value)}
                          disabled={isCreatingFeed}
                        />
                        <input
                          type="text"
                          className="topic-input"
                          placeholder="Ad (isteğe bağlı)"
                          value={newFeedTitle}
                          onChange={(e) => setNewFeedTitle(e.target.value)}
                          disabled={isCreatingFeed}
                        />
                        <div className="add-topic-buttons">
                          <button
                            className="cancel-add-button"
                            onClick={() => { setShowAddFeed(false); setNewFeedUrl(''); setNewFeedTitle(''); }}
                            disabled={isCreatingFeed}
                          >
                            İptal
                          </button>
                          <button
                            className="confirm-add-button"
                            onClick={handleAddFeed}
                            disabled={isCreatingFeed || !newFeedUrl.trim()}
                          >
                            {isCreatingFeed ? 'Ekleniyor...' : 'Ekle'}
                          </button>
                        </div>
                      </div>
                    )}
                  </div>
                )}
              </div>

              {/* Topics Section */}
              <div className="settings-section">
                <div 
                  className="section-header" 
                  onClick={() => toggleSection('topics')}
                >
                  <h3>
                    {expandedSections.topics ? <ChevronDownIcon className="collapse-icon" /> : <ChevronRightIcon className="collapse-icon" />}
                    <FolderIcon className="section-icon" /> Kategoriler
                  </h3>
                </div>
                {expandedSections.topics && (
                <div className="section-content">
                <p className="section-description">
                  Sınıflandırma için kullanılacak kategorileri seçin.
                  Boş seçim = tüm kategoriler.
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
                )}
              </div>

              {/* Summary Types Section */}
              <div className="settings-section">
                <div 
                  className="section-header" 
                  onClick={() => toggleSection('summaryTypes')}
                >
                  <h3>
                    {expandedSections.summaryTypes ? <ChevronDownIcon className="collapse-icon" /> : <ChevronRightIcon className="collapse-icon" />}
                    <DocumentTextIcon className="section-icon" /> Özet Türleri
                  </h3>
                </div>
                {expandedSections.summaryTypes && (
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
                    />
                    <span className="checkbox-text">
                      <strong>Detaylı</strong> - Birden fazla paragraf (daha yüksek maliyet)
                    </span>
                  </label>
                </div>
                {enabledSummaryTypes.length === 0 && (
                  <p className="warning-text">⚠️ En az bir tür seçilmelidir</p>
                )}
                </div>
                )}
              </div>

              {/* System Prompts Section */}
              <div className="settings-section">
                <div
                  className="section-header"
                  onClick={() => toggleSection('prompts')}
                >
                  <h3>
                    {expandedSections.prompts ? <ChevronDownIcon className="collapse-icon" /> : <ChevronRightIcon className="collapse-icon" />}
                    <SparklesIcon className="section-icon" /> Sistem Promptları
                  </h3>
                </div>
                {expandedSections.prompts && (
                <div className="section-content">
                <p className="section-description">
                  Yapay zeka sınıflandırma ve özetleme için kullanılan sistem promptlarını düzenleyin.
                </p>

                <PromptEditor
                  promptType="classification"
                  label="Sınıflandırma Promptu"
                  description="Bu prompt makaleleri otomatik olarak kategorilere ayırmak için kullanılır."
                />

                <PromptEditor
                  promptType="summarization"
                  label="Özetleme Promptu"
                  description="Bu prompt makale özetleri oluşturmak için kullanılır."
                />
                </div>
                )}
              </div>

              {/* User Management Section - Admin Only */}
              {currentUser.role === 'admin' && (
                <div className="settings-section">
                  <div
                    className="section-header"
                    onClick={() => toggleSection('users')}
                  >
                    <h3>
                      {expandedSections.users ? <ChevronDownIcon className="collapse-icon" /> : <ChevronRightIcon className="collapse-icon" />}
                      <UsersIcon className="section-icon" /> Kullanıcı Yönetimi
                    </h3>
                  </div>
                  {expandedSections.users && (
                    <div className="section-content">
                      <p className="section-description">
                        Kullanıcı hesaplarını yönetin. Yalnızca yöneticiler bu ayarları görebilir.
                      </p>

                      {/* Existing users list */}
                      <div className="user-list">
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
                        {userError && <p className="warning-text">⚠️ {userError}</p>}
                        <button
                          className="confirm-add-button"
                          onClick={handleAddUser}
                          disabled={isCreatingUser || !newUserEmail.trim() || !newUserPassword.trim()}
                        >
                          {isCreatingUser ? 'Oluşturuluyor...' : 'Kullanıcı oluştur'}
                        </button>
                      </div>
                    </div>
                  )}
                </div>
              )}
            </>
          )}
        </div>

        <div className="settings-footer">
          <button className="cancel-button" onClick={onClose}>
            İptal
          </button>
          <button
            className="save-button"
            onClick={handleSave}
            disabled={isSaving || enabledSummaryTypes.length === 0}
          >
            {isSaving ? 'Kaydediliyor...' : 'Ayarları kaydet'}
          </button>
        </div>
      </div>
    </div>
  );
}

export default Settings;
