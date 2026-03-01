import React, { useState, useEffect, useRef } from 'react';
import { promptsApi } from '../../services/api';
import type { SystemPrompt } from '../../types';
import { PencilIcon, CheckIcon, XMarkIcon } from '@heroicons/react/24/outline';
import './PromptEditor.css';

interface PromptEditorProps {
    promptType: string;
    label: string;
    description: string;
}

const PromptEditor: React.FC<PromptEditorProps> = ({ promptType, label, description }) => {
    const [prompt, setPrompt] = useState<SystemPrompt | null>(null);
    const [editedText, setEditedText] = useState('');
    const [isActive, setIsActive] = useState(true);
    const [isEditing, setIsEditing] = useState(false);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const [successMessage, setSuccessMessage] = useState<string | null>(null);
    const successTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

    useEffect(() => {
        loadPrompt();
        return () => {
            if (successTimeoutRef.current) clearTimeout(successTimeoutRef.current);
        };
    }, [promptType]);

    const loadPrompt = async () => {
        try {
            setLoading(true);
            setError(null);
            const data = await promptsApi.get(promptType);
            setPrompt(data);
            setEditedText(data.prompt_text);
            setIsActive(data.is_active);
        } catch (err: any) {
            if (err?.response?.status === 404) {
                // Prompt does not exist yet — allow creation without showing an error
                setPrompt(null);
            } else {
                console.error('Error loading prompt:', err);
                setError('Prompt yüklenemedi');
            }
        } finally {
            setLoading(false);
        }
    };

    const handleSave = async () => {
        try {
            setLoading(true);
            setError(null);
            setSuccessMessage(null);

            if (prompt) {
                // Update existing prompt
                await promptsApi.update(promptType, editedText, isActive);
            } else {
                // Create new prompt
                await promptsApi.create(promptType, editedText, isActive);
            }

            setSuccessMessage('Prompt başarıyla kaydedildi!');
            setIsEditing(false);
            await loadPrompt();

            // Clear success message after 3 seconds
            if (successTimeoutRef.current) clearTimeout(successTimeoutRef.current);
            successTimeoutRef.current = setTimeout(() => setSuccessMessage(null), 3000);
        } catch (err) {
            console.error('Error saving prompt:', err);
            setError('Prompt kaydedilirken hata oluştu');
        } finally {
            setLoading(false);
        }
    };

    const handleCancel = () => {
        if (prompt) {
            setEditedText(prompt.prompt_text);
            setIsActive(prompt.is_active);
        }
        setIsEditing(false);
        setError(null);
    };

    if (loading && !prompt) {
        return <div className="prompt-editor loading">Yükleniyor...</div>;
    }

    return (
        <div className="prompt-editor">
            <div className="prompt-header">
                <div className="prompt-title">
                    <h3>{label}</h3>
                    <p className="prompt-description">{description}</p>
                </div>
                <div className="prompt-actions">
                    {!isEditing ? (
                        <button
                            className="btn btn-edit"
                            onClick={() => setIsEditing(true)}
                            disabled={loading}
                        >
                            <PencilIcon /> Düzenle
                        </button>
                    ) : (
                        <>
                            <button
                                className="btn btn-save"
                                onClick={handleSave}
                                disabled={loading || !editedText.trim()}
                            >
                                <CheckIcon /> Kaydet
                            </button>
                            <button
                                className="btn btn-cancel"
                                onClick={handleCancel}
                                disabled={loading}
                            >
                                <XMarkIcon /> İptal
                            </button>
                        </>
                    )}
                </div>
            </div>

            {error && <div className="error-message">{error}</div>}
            {successMessage && <div className="success-message">{successMessage}</div>}

            <div className="prompt-content">
                {isEditing ? (
                    <>
                        <div className="form-group">
                            <label className="checkbox-label">
                                <input
                                    type="checkbox"
                                    checked={isActive}
                                    onChange={(e) => setIsActive(e.target.checked)}
                                />
                                <span>Aktif</span>
                            </label>
                        </div>
                        <div className="form-group">
                            <label>Prompt Metni:</label>
                            <textarea
                                className="prompt-textarea"
                                value={editedText}
                                onChange={(e) => setEditedText(e.target.value)}
                                rows={15}
                                placeholder="Sistem promptunu girin..."
                            />
                            <div className="char-count">
                                {editedText.length} karakter
                            </div>
                        </div>
                    </>
                ) : (
                    <div className="prompt-display">
                        <div className="status-badge">
                            <span className={`badge ${isActive ? 'active' : 'inactive'}`}>
                                {isActive ? <><CheckIcon /> Aktif</> : <><XMarkIcon /> Pasif</>}
                            </span>
                        </div>
                        <pre className="prompt-text">{prompt?.prompt_text || 'Prompt belirlenmemiş'}</pre>
                        {prompt && (
                            <div className="prompt-meta">
                                <small>
                                    Son güncelleme: {new Date(prompt.updated_at).toLocaleString('tr-TR')}
                                </small>
                            </div>
                        )}
                    </div>
                )}
            </div>
        </div>
    );
};

export default PromptEditor;
