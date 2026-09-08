import { useState } from 'react';
import { PRIORITIES, type PriorityOption } from '../../constants/priorities';
import './CategoryBulkActions.css';

interface CategoryBulkActionsProps {
  priorityCounts: Record<string, number>;
  unimportantCount: number;
  onDeleteAllByPriority: (priority: string) => void;
  onArchiveAllByPriority: (priority: string) => void;
  onDeleteAllUnimportant: () => void;
  onArchiveAllUnimportant: () => void;
  deletePending?: boolean;
  archivePending?: boolean;
}

function CategoryBulkActions({
  priorityCounts,
  unimportantCount,
  onDeleteAllByPriority,
  onArchiveAllByPriority,
  onDeleteAllUnimportant,
  onArchiveAllUnimportant,
  deletePending = false,
  archivePending = false,
}: CategoryBulkActionsProps) {
  const [confirmPriority, setConfirmPriority] = useState<PriorityOption | null>(null);
  const [confirmUnimportant, setConfirmUnimportant] = useState(false);

  return (
    <div className="category-bulk-actions">
      <p className="category-bulk-actions-title">Önem seviyesi bazlı toplu işlemler</p>
      <div className="category-bulk-actions-list">
        {PRIORITIES.map((p) => {
          const count = priorityCounts[p.value] ?? 0;
          const empty = count === 0;
          return (
            <div key={p.value} className="category-bulk-row">
              <span className="category-bulk-name">
                {p.label}
                <span className="category-bulk-count">{count}</span>
              </span>
              <div className="category-bulk-buttons">
                <button
                  className="btn btn-outline btn-sm"
                  onClick={() => onArchiveAllByPriority(p.value)}
                  disabled={empty || archivePending}
                  title={`${p.label} önceliğindeki tüm haberleri arşive gönder`}
                >
                  📦 Tümünü Arşive Gönder
                </button>
                <button
                  className="btn btn-outline btn-sm category-bulk-delete"
                  onClick={() => setConfirmPriority(p)}
                  disabled={empty || deletePending}
                  title={`${p.label} önceliğindeki tüm haberleri sil`}
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

      {confirmPriority && (
        <div className="category-bulk-confirm-overlay">
          <div className="category-bulk-confirm-box">
            <p>
              &quot;{confirmPriority.label}&quot; önceliğindeki tüm okunmamış haberleri
              {` (${priorityCounts[confirmPriority.value] ?? 0} adet)`} silmek
              istediğinize emin misiniz?
            </p>
            <button
              className="category-bulk-confirm-delete"
              onClick={() => {
                onDeleteAllByPriority(confirmPriority.value);
                setConfirmPriority(null);
              }}
              disabled={deletePending}
            >
              Sil
            </button>
            <button className="category-bulk-confirm-cancel" onClick={() => setConfirmPriority(null)}>
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
