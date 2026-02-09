import { useState, useEffect } from 'react';
import { useSettings, useUpdateSettings, useTopics, useCreateTopic, useUpdateTopic, useDeleteTopic } from '../../hooks/useApi';
import PromptEditor from '../PromptEditor/PromptEditor';
import { Cog6ToothIcon, FolderIcon, DocumentTextIcon, SparklesIcon, PencilIcon, TrashIcon, CheckIcon, XMarkIcon, PlusIcon, ChevronDownIcon, ChevronRightIcon } from '@heroicons/react/24/outline';
import './Settings.css';

interface SettingsProps {
  isOpen: boolean;
  onClose: () => void;
}

function Settings({ isOpen, onClose }: SettingsProps) {
  const { data: settings, isLoading: settingsLoading } = useSettings();
  const { data: topics } = useTopics();
  const { mutate: updateSettings, isPending: isSaving } = useUpdateSettings();
  const { mutate: createTopic, isPending: isCreatingTopic } = useCreateTopic();
  const { mutate: updateTopic, isPending: isUpdatingTopic } = useUpdateTopic();
  const { mutate: deleteTopic, isPending: isDeletingTopic } = useDeleteTopic();

  const [enabledTopicIds, setEnabledTopicIds] = useState<number[]>([]);
  const [enabledSummaryTypes, setEnabledSummaryTypes] = useState<string[]>([]);
  const [showAddTopic, setShowAddTopic] = useState(false);
  const [newTopicName, setNewTopicName] = useState('');
  const [newTopicDescription, setNewTopicDescription] = useState('');
  const [editingTopicId, setEditingTopicId] = useState<number | null>(null);
  const [editTopicName, setEditTopicName] = useState('');
  const [editTopicDescription, setEditTopicDescription] = useState('');
  
  // Accordion state for sections
  const [expandedSections, setExpandedSections] = useState<Record<string, boolean>>({
    topics: true,
    summaryTypes: false,
    prompts: false
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
    setEnabledTopicIds(prev => 
      prev.includes(topicId)
        ? prev.filter(id => id !== topicId)
        : [...prev, topicId]
    );
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
    if (confirm(`Möchten Sie die Kategorie "${topicName}" wirklich löschen? Alle Zuordnungen zu Artikeln werden entfernt.`)) {
      deleteTopic(topicId);
    }
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
          <h2><Cog6ToothIcon className="header-icon" /> Einstellungen</h2>
          <button className="close-button" onClick={onClose}><XMarkIcon /></button>
        </div>

        <div className="settings-content">
          {settingsLoading ? (
            <div className="loading">Lade Einstellungen...</div>
          ) : (
            <>
              {/* Topics Section */}
              <div className="settings-section">
                <div 
                  className="section-header" 
                  onClick={() => toggleSection('topics')}
                >
                  <h3>
                    {expandedSections.topics ? <ChevronDownIcon className="collapse-icon" /> : <ChevronRightIcon className="collapse-icon" />}
                    <FolderIcon className="section-icon" /> Kategorien
                  </h3>
                </div>
                {expandedSections.topics && (
                <div className="section-content">
                <p className="section-description">
                  Wählen Sie die Kategorien aus, die für die Klassifizierung verwendet werden sollen.
                  Leere Auswahl = alle Kategorien.
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
                            placeholder="Beschreibung (optional)"
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
                              title="Bearbeiten"
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
                              title="Löschen"
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
                    Alle auswählen
                  </button>
                )}
                
                {/* Add New Topic Section */}
                {!showAddTopic ? (
                  <button 
                    className="add-topic-button"
                    onClick={() => setShowAddTopic(true)}
                  >
                    <PlusIcon /> Neue Kategorie hinzufügen
                  </button>
                ) : (
                  <div className="add-topic-form">
                    <input
                      type="text"
                      className="topic-input"
                      placeholder="Kategoriename (z.B. Technologie)"
                      value={newTopicName}
                      onChange={(e) => setNewTopicName(e.target.value)}
                      disabled={isCreatingTopic}
                    />
                    <input
                      type="text"
                      className="topic-input"
                      placeholder="Beschreibung (optional)"
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
                        Abbrechen
                      </button>
                      <button 
                        className="confirm-add-button"
                        onClick={handleAddTopic}
                        disabled={isCreatingTopic || !newTopicName.trim()}
                      >
                        {isCreatingTopic ? 'Erstellen...' : 'Erstellen'}
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
                    <DocumentTextIcon className="section-icon" /> Zusammenfassungstypen
                  </h3>
                </div>
                {expandedSections.summaryTypes && (
                <div className="section-content">
                <p className="section-description">
                  Wählen Sie, welche Zusammenfassungstypen generiert werden sollen.
                  Mehrfachauswahl möglich.
                </p>
                <div className="checkbox-group">
                  <label className="checkbox-label">
                    <input
                      type="checkbox"
                      checked={enabledSummaryTypes.includes('brief')}
                      onChange={() => handleSummaryTypeToggle('brief')}
                    />
                    <span className="checkbox-text">
                      <strong>Kurz (Brief)</strong> - 2-3 Sätze
                    </span>
                  </label>
                  <label className="checkbox-label">
                    <input
                      type="checkbox"
                      checked={enabledSummaryTypes.includes('standard')}
                      onChange={() => handleSummaryTypeToggle('standard')}
                    />
                    <span className="checkbox-text">
                      <strong>Standard</strong> - Ein Absatz
                    </span>
                  </label>
                  <label className="checkbox-label">
                    <input
                      type="checkbox"
                      checked={enabledSummaryTypes.includes('detailed')}
                      onChange={() => handleSummaryTypeToggle('detailed')}
                    />
                    <span className="checkbox-text">
                      <strong>Detailliert (Detailed)</strong> - Mehrere Absätze (höhere Kosten)
                    </span>
                  </label>
                </div>
                {enabledSummaryTypes.length === 0 && (
                  <p className="warning-text">⚠️ Mindestens ein Typ muss ausgewählt werden</p>
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
                    <SparklesIcon className="section-icon" /> System Prompts
                  </h3>
                </div>
                {expandedSections.prompts && (
                <div className="section-content">
                <p className="section-description">
                  Bearbeiten Sie die System-Prompts, die für die KI-Klassifizierung und Zusammenfassung verwendet werden.
                </p>
                
                <PromptEditor
                  promptType="classification"
                  label="Klassifizierungs-Prompt"
                  description="Dieser Prompt wird verwendet, um Artikel automatisch in Kategorien einzuordnen."
                />
                
                <PromptEditor
                  promptType="summarization"
                  label="Zusammenfassungs-Prompt"
                  description="Dieser Prompt wird verwendet, um Artikel-Zusammenfassungen zu erstellen."
                />
                </div>
                )}
              </div>
            </>
          )}
        </div>

        <div className="settings-footer">
          <button className="cancel-button" onClick={onClose}>
            Abbrechen
          </button>
          <button 
            className="save-button" 
            onClick={handleSave}
            disabled={isSaving || enabledSummaryTypes.length === 0}
          >
            {isSaving ? 'Speichern...' : 'Einstellungen speichern'}
          </button>
        </div>
      </div>
    </div>
  );
}

export default Settings;
