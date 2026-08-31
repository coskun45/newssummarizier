import { useState } from 'react';
import type { Topic } from '../../types';
import './CategoryBulkActions.css';

interface CategoryBulkActionsProps {
  topics: Topic[];
  unimportantCount: number;
  onDeleteAll: (topicId: number) => void;
  onArchiveAll: (topicId: number) => void;
  onDeleteAllUnimportant: () => void;
  onArchiveAllUnimportant: () => void;
  deletePending?: boolean;
  archivePending?: boolean;
}

function CategoryBulkActions({
  topics,
  unimportantCount,
  onDeleteAll,
  onArchiveAll,
  onDeleteAllUnimportant,
  onArchiveAllUnimportant,
  deletePending = false,
  archivePending = false,
}: CategoryBulkActionsProps) {
  const [confirmTopic, setConfirmTopic] = useState<Topic | null>(null);
  const [confirmUnimportant, setConfirmUnimportant] = useState(false);

  return (
    <div className="category-bulk-actions">
      <p className="category-bulk-actions-title">Kategori bazlı toplu işlemler</p>
      <div className="category-bulk-actions-list">
        {topics.map((topic) => {
          const empty = (topic.unread_count ?? 0) === 0;
          return (
            <div key={topic.id} className="category-bulk-row">
              <span className="category-bulk-name">
                {topic.name}
                {topic.unread_count !== undefined && (
                  <span className="category-bulk-count">{topic.unread_count}</span>
                )}
              </span>
              <div className="category-bulk-buttons">
                <button
                  className="btn btn-outline btn-sm"
                  onClick={() => onArchiveAll(topic.id)}
                  disabled={empty || archivePending}
                  title={`${topic.name} kategorisindeki tüm haberleri arşive gönder`}
                >
                  📦 Tümünü Arşive Gönder
                </button>
                <button
                  className="btn btn-outline btn-sm category-bulk-delete"
                  onClick={() => setConfirmTopic(topic)}
                  disabled={empty || deletePending}
                  title={`${topic.name} kategorisindeki tüm haberleri sil`}
                >
                  🗑️ Tümünü Sil
                </button>
              </div>
            </div>
          );
        })}

        <div className="category-bulk-row">
          <span className="category-bulk-name">
            Önemsiz
            <span className="category-bulk-count">{unimportantCount}</span>
          </span>
          <div className="category-bulk-buttons">
            <button
              className="btn btn-outline btn-sm"
              onClick={onArchiveAllUnimportant}
              disabled={unimportantCount === 0 || archivePending}
              title="Tüm önemsiz haberleri arşive gönder"
            >
              📦 Tümünü Arşive Gönder
            </button>
            <button
              className="btn btn-outline btn-sm category-bulk-delete"
              onClick={() => setConfirmUnimportant(true)}
              disabled={unimportantCount === 0 || deletePending}
              title="Tüm önemsiz haberleri sil"
            >
              🗑️ Tümünü Sil
            </button>
          </div>
        </div>
      </div>

      {confirmTopic && (
        <div className="category-bulk-confirm-overlay">
          <div className="category-bulk-confirm-box">
            <p>
              &quot;{confirmTopic.name}&quot; kategorisindeki tüm okunmamış haberleri
              {confirmTopic.unread_count !== undefined ? ` (${confirmTopic.unread_count} adet)` : ''} silmek
              istediğinize emin misiniz?
            </p>
            <button
              className="category-bulk-confirm-delete"
              onClick={() => {
                onDeleteAll(confirmTopic.id);
                setConfirmTopic(null);
              }}
              disabled={deletePending}
            >
              Sil
            </button>
            <button className="category-bulk-confirm-cancel" onClick={() => setConfirmTopic(null)}>
              Vazgeç
            </button>
          </div>
        </div>
      )}

      {confirmUnimportant && (
        <div className="category-bulk-confirm-overlay">
          <div className="category-bulk-confirm-box">
            <p>
              Tüm okunmamış önemsiz haberleri ({unimportantCount} adet) silmek istediğinize emin
              misiniz?
            </p>
            <button
              className="category-bulk-confirm-delete"
              onClick={() => {
                onDeleteAllUnimportant();
                setConfirmUnimportant(false);
              }}
              disabled={deletePending}
            >
              Sil
            </button>
            <button className="category-bulk-confirm-cancel" onClick={() => setConfirmUnimportant(false)}>
              Vazgeç
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

export default CategoryBulkActions;
